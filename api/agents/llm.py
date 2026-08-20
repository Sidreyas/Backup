"""
The LLM boundary.

Every model call in the product goes through here, for three reasons that are
product requirements rather than engineering preferences:

  1. **Provenance is mandatory.** Every call returns the pinned model version,
     a prompt hash and token counts. EU AI Act Art. 12 asks which system
     version produced an output; that question is unanswerable if calls are
     scattered and some of them forget to record it.

  2. **Cost is attributed.** Every call writes a `CostEvent`. The product
     claims to account for what AI work cost per requirement, per test case,
     per bug — that claim needs a row behind it, not an estimate.

  3. **Absence degrades, it does not fail.** With no API key, calls return a
     clearly-labelled stub so the whole application still runs end-to-end on a
     fresh clone. The label matters more than the fallback: output that came
     from a stub is marked `source="stub"` everywhere it lands, so nothing
     downstream mistakes placeholder reasoning for a real analysis.

The temperature is pinned low. These are extraction and analysis tasks where
reproducibility is worth more than variety, and a governance record produced at
high temperature is one nobody can reproduce.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from api.core.config import settings
from api.core.ids import new_id, utcnow
from api.domain.governance import CostEvent

# Published per-million-token pricing for the pinned model. Held here rather
# than fetched so a cost figure is never silently wrong because a network call
# failed; when pricing changes this constant changes with it, in a diff someone
# reviews.
_USD_PER_MTOK_IN = 5.0
_USD_PER_MTOK_OUT = 25.0


@dataclass(slots=True)
class LlmResult:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str
    model_version: str
    prompt_hash: str
    #: "llm" when a real call was made, "stub" when the key was absent.
    source: str = "llm"
    grounded_node_ids: list[str] = field(default_factory=list)

    def provenance(self) -> dict:
        """The `AiProvenance` shape the frontend and the audit chain expect."""
        return {
            "model": self.model,
            "modelVersion": self.model_version,
            "promptHash": self.prompt_hash,
            "tokensIn": self.tokens_in,
            "tokensOut": self.tokens_out,
            "temperature": settings.meridian_temperature,
            "groundedNodeIds": self.grounded_node_ids,
        }


def _price(tokens_in: int, tokens_out: int) -> float:
    """Cost of one call, in USD.

    Priced per provider. Applying Anthropic's rate to an NVIDIA call would
    overstate spend by orders of magnitude and make the unit-economics view
    fiction — and a cost series nobody trusts is one nobody looks at.

    NVIDIA's build tier is free at the time of writing, so its calls cost
    nothing. Recorded as zero rather than skipped: a gap in the series is
    indistinguishable from work that never happened.

    Foundry is billed per token at rates that vary by deployment and agreement,
    so its price is configuration rather than a constant. Left at zero when
    unset — an invented figure would be worse than an honest blank, because
    unlike a blank it gets quoted.
    """
    provider = settings.llm_provider
    if provider == "nvidia":
        return 0.0
    if provider == "foundry":
        return round(
            tokens_in / 1_000_000 * settings.foundry_usd_per_mtok_in
            + tokens_out / 1_000_000 * settings.foundry_usd_per_mtok_out,
            6,
        )
    return round(
        tokens_in / 1_000_000 * _USD_PER_MTOK_IN
        + tokens_out / 1_000_000 * _USD_PER_MTOK_OUT,
        6,
    )


def prompt_hash(prompt: str) -> str:
    """Hash rather than store.

    The record needs to attest what the input was without the audit log
    becoming a second copy of potentially sensitive requirement text.
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class LlmClient:
    """Wraps the Anthropic SDK, or stands in for it."""

    def __init__(self) -> None:
        self._client: Any = None
        self.provider = settings.llm_provider

        # Imported lazily so neither SDK is a hard dependency of merely
        # importing the app — a deployment with no LLM configured should not
        # need either installed to boot.
        if self.provider == "anthropic":
            from anthropic import Anthropic

            self._client = Anthropic(api_key=settings.anthropic_api_key)
        elif self.provider in {"nvidia", "foundry"}:
            # Both speak the OpenAI protocol — NVIDIA's build API natively,
            # Azure AI Foundry through its `/openai/v1` surface — so the OpenAI
            # SDK talks to either with only a base_url change. Using httpx
            # directly would mean reimplementing retries and streaming for no
            # gain.
            from openai import OpenAI

            self._client = OpenAI(
                api_key=(
                    settings.foundry_api_key
                    if self.provider == "foundry"
                    else settings.nvidia_build_api_key
                ),
                base_url=(
                    settings.foundry_base_url
                    if self.provider == "foundry"
                    else settings.nvidia_base_url
                ),
                # The SDK defaults to 600s with 2 retries — up to half an hour
                # before a caller learns anything went wrong, which reaches a
                # user as a spinner that never resolves. A bounded failure is
                # more useful than an unbounded wait: the request can be
                # retried, and the UI can say what happened.
                timeout=settings.llm_timeout_seconds,
                max_retries=1,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def uses_openai_protocol(self) -> bool:
        """Whether completions go through the OpenAI-shaped client.

        Two providers share that path, so branching on `== "nvidia"` silently
        excluded Foundry and sent its calls to Anthropic's client instead.
        """
        return self.provider in {"nvidia", "foundry"}

    @property
    def openai_model(self) -> str:
        """The deployment name to request on the OpenAI-protocol path."""
        return (
            settings.foundry_model
            if self.provider == "foundry"
            else settings.nvidia_model
        )

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        grounded_node_ids: list[str] | None = None,
        stub: str | None = None,
    ) -> LlmResult:
        """One completion, with provenance.

        `stub` is the text returned when no key is configured. Callers pass
        something structurally valid for their use — a stub that fails the
        caller's own parsing would turn "no API key" into a crash three frames
        away from the cause.
        """
        phash = prompt_hash(f"{system}\n\n{prompt}")
        grounded = grounded_node_ids or []

        if not self.enabled:
            body = stub if stub is not None else _DEFAULT_STUB
            return LlmResult(
                text=body,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model=settings.meridian_model,
                model_version=settings.meridian_model_version,
                prompt_hash=phash,
                source="stub",
                grounded_node_ids=grounded,
            )

        if self.uses_openai_protocol:
            text, tin, tout = self._complete_openai(system, prompt, max_tokens)
        else:
            text, tin, tout = self._complete_anthropic(system, prompt, max_tokens)

        return LlmResult(
            text=text,
            tokens_in=tin,
            tokens_out=tout,
            cost_usd=_price(tin, tout),
            # The model that actually answered, not the pinned default. An
            # audit record naming a model that did not produce the output is
            # worse than none — it looks authoritative and is wrong.
            model=settings.active_model,
            model_version=settings.meridian_model_version,
            prompt_hash=phash,
            source="llm",
            grounded_node_ids=grounded,
        )

    def stream(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
        grounded_node_ids: list[str] | None = None,
        stub: str | None = None,
    ) -> Iterator[str | LlmResult]:
        """The same completion, delivered as it is generated.

        Yields text fragments, then a final `LlmResult` carrying the assembled
        text and the usage counts. The mixed yield type is deliberate: usage
        totals only exist once the stream ends, and a caller that needs both
        the tokens *and* the accounting should not have to make two calls.

        Streaming exists for one reason — perceived latency. A grounded answer
        on a reasoning model takes 45–90 seconds to finish, and a user watching
        a spinner for that long assumes it has hung. The same wait with text
        arriving from the second onward reads as work in progress.
        """
        phash = prompt_hash(f"{system}\n\n{prompt}")
        grounded = grounded_node_ids or []

        if not self.enabled:
            body = stub if stub is not None else _DEFAULT_STUB
            yield body
            yield LlmResult(
                text=body,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model=settings.meridian_model,
                model_version=settings.meridian_model_version,
                prompt_hash=phash,
                source="stub",
                grounded_node_ids=grounded,
            )
            return

        chunks: list[str] = []
        tin = tout = 0

        if self.uses_openai_protocol:
            response = self._client.chat.completions.create(
                model=self.openai_model,
                max_tokens=max_tokens,
                temperature=settings.meridian_temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                stream=True,
                # Usage is not sent with a streamed response unless asked for.
                # Without it every streamed turn records zero tokens and the
                # cost ledger quietly stops being able to answer "what did
                # this cost".
                stream_options={"include_usage": True},
            )
            for event in response:
                usage = getattr(event, "usage", None)
                if usage:
                    tin = getattr(usage, "prompt_tokens", 0) or 0
                    tout = getattr(usage, "completion_tokens", 0) or 0
                # The final usage-only event carries no choices.
                for choice in getattr(event, "choices", None) or []:
                    piece = getattr(choice.delta, "content", None)
                    if piece:
                        chunks.append(piece)
                        yield piece
        else:
            with self._client.messages.stream(
                model=settings.meridian_model,
                max_tokens=max_tokens,
                temperature=settings.meridian_temperature,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for piece in stream.text_stream:
                    chunks.append(piece)
                    yield piece
                final = stream.get_final_message()
                tin = final.usage.input_tokens
                tout = final.usage.output_tokens

        yield LlmResult(
            text="".join(chunks),
            tokens_in=tin,
            tokens_out=tout,
            cost_usd=_price(tin, tout),
            model=settings.active_model,
            model_version=settings.meridian_model_version,
            prompt_hash=phash,
            source="llm",
            grounded_node_ids=grounded,
        )

    def _complete_anthropic(
        self, system: str, prompt: str, max_tokens: int
    ) -> tuple[str, int, int]:
        message = self._client.messages.create(
            model=settings.meridian_model,
            max_tokens=max_tokens,
            temperature=settings.meridian_temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", "") == "text"
        )
        return text, message.usage.input_tokens, message.usage.output_tokens

    def _complete_openai(
        self, system: str, prompt: str, max_tokens: int
    ) -> tuple[str, int, int]:
        """OpenAI-protocol completion, used for NVIDIA's build API.

        The system prompt becomes a system *message* rather than a separate
        parameter — the protocol's shape, not a workaround.
        """
        response = self._client.chat.completions.create(
            model=self.openai_model,
            max_tokens=max_tokens,
            temperature=settings.meridian_temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        return (
            text,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )


_DEFAULT_STUB = (
    "No language model is configured, so this output is a placeholder. "
    "Set ANTHROPIC_API_KEY to enable grounded analysis."
)


def record_cost(
    db: Session,
    result: LlmResult,
    *,
    kind: str,
    requirement_id: str | None = None,
    workspace_id: str | None = None,
    detail: str = "",
) -> CostEvent:
    """Write the unit-economics row for one call.

    Stub calls are recorded too, at zero cost. A gap in the cost series is
    indistinguishable from work that was never done; a zero is legible.
    """
    event = CostEvent(
        id=new_id("ce"),
        at=utcnow(),
        kind=kind,
        requirement_id=requirement_id,
        model=result.model if result.source == "llm" else None,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        llm_usd=result.cost_usd,
        compute_usd=0.0,
        detail=detail,
        workspace_id=workspace_id,
    )
    db.add(event)
    return event


def extract_json(text: str) -> Any:
    """Pull a JSON value out of a model response.

    Models wrap JSON in prose or fences even when told not to. This tries the
    whole string, then a fenced block, then the outermost brace/bracket span.
    Returns None rather than raising: the caller decides whether unparseable
    output is a hard failure or a reason to fall back, and that decision
    differs per endpoint.
    """
    text = text.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    return None


llm = LlmClient()
