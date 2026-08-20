"""
Runtime configuration.

Every setting has a working default except credentials. That is deliberate: the
whole application must run on a fresh clone with no secrets, because a backend
you cannot start is a backend nobody reviews. Where a credential is absent the
owning subsystem degrades to a labelled stub rather than raising — see
`api/agents/llm.py` and `api/connectors/base.py` for the two places that matters.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Port 5433, not 5432 — see the note in docker-compose.yml about a locally
    # installed Postgres shadowing the container's published port.
    database_url: str = (
        "postgresql+psycopg://meridian:meridian@localhost:5433/meridian"
    )
    redis_url: str = "redis://localhost:6379/0"
    frontend_origin: str = "http://localhost:5173"

    # --- LLM ---------------------------------------------------------------
    anthropic_api_key: str = ""

    # NVIDIA's build API, which is OpenAI-compatible. Used when no Anthropic
    # key is present, so a developer can run the whole system on a free tier
    # without the agents silently degrading to stubs.
    nvidia_build_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "openai/gpt-oss-120b"

    # Azure AI Foundry. Also OpenAI-compatible via its `/openai/v1` surface, so
    # it reuses the same client path as NVIDIA — only the base URL, key and
    # model name differ.
    #
    # Preferred over NVIDIA when both are configured: measured at 2.2s against
    # 60s for the same trivial prompt, because the free-tier reasoning model
    # spends the whole minute reasoning before emitting anything.
    #
    # `FOUNDRY_ENDPOINT` is pasted from the Azure portal, which gives the full
    # `/chat/completions` URL. The client wants the base, so the suffix is
    # trimmed rather than requiring someone to edit what they copied.
    foundry_api_key: str = ""
    foundry_endpoint: str = ""
    foundry_model: str = "DeepSeek-V4-Pro"

    #: Per-million-token pricing for the Foundry deployment.
    #:
    #: Configuration rather than a constant: Azure rates vary by model, region
    #: and agreement, and a hardcoded guess would make the cost dashboard
    #: confidently wrong. Zero until set — an honest blank, unlike an invented
    #: figure, does not get quoted in a meeting.
    foundry_usd_per_mtok_in: float = 0.0
    foundry_usd_per_mtok_out: float = 0.0

    # Pinned, not "latest". Under EU AI Act Art. 12 a provider must be able to
    # tell whether an output came from a different system version, and that
    # question is unanswerable if the version floats. Mirrors ACTIVE_MODEL in
    # the frontend's provenance.ts — the two must agree.
    meridian_model: str = "claude-opus-5"
    meridian_model_version: str = "2026-07-14"
    meridian_temperature: float = 0.2

    #: How long to wait for a completion before failing.
    #:
    #: Generous, because reasoning models on a free tier are genuinely slow —
    #: measured between 40s and 130s for a trivial prompt. But bounded: the
    #: OpenAI SDK's own default is 600s with retries, which reaches a user as
    #: a spinner that never resolves.
    llm_timeout_seconds: float = 180.0

    # --- Secrets -----------------------------------------------------------
    # Encrypts connector credentials at rest (api/core/secrets.py). Absent, the
    # app still runs but refuses to store credentials rather than writing them
    # in plaintext. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(32))"
    meridian_secret_key: str = ""

    # --- Connectors --------------------------------------------------------
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    github_token: str = ""
    github_api_url: str = "https://api.github.com"

    azure_devops_org: str = ""
    azure_devops_pat: str = ""

    @property
    def llm_provider(self) -> str:
        """Which provider is configured, most capable first.

        Anthropic wins when both keys are present: the pinned model is what
        the provenance records claim, and silently answering from a different
        provider would make those records wrong.
        """
        if self.anthropic_api_key:
            return "anthropic"
        if self.foundry_api_key and self.foundry_endpoint:
            return "foundry"
        if self.nvidia_build_api_key:
            return "nvidia"
        return "none"

    @property
    def foundry_base_url(self) -> str:
        """The endpoint with any `/chat/completions` suffix removed.

        The Azure portal hands out the full operation URL. The OpenAI client
        appends the path itself, so passing it verbatim produces
        `/chat/completions/chat/completions` and a 404 that reads like a bad
        deployment name.
        """
        return self.foundry_endpoint.rstrip("/").removesuffix("/chat/completions")

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none"

    @property
    def active_model(self) -> str:
        """The model actually answering, which provenance must record.

        Not `meridian_model` unconditionally: an audit record naming a model
        that did not produce the output is worse than no record, because it
        looks authoritative.
        """
        provider = self.llm_provider
        if provider == "anthropic":
            return self.meridian_model
        if provider == "foundry":
            return self.foundry_model
        return self.nvidia_model


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
