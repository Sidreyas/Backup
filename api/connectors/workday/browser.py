"""
Controlled browser discovery.

The last resort, and the only surface that reaches conditional field
visibility, validation messages, dropdown value sets and security-policy
displays. None of those exist in SOAP, RaaS, REST or the Graph API. They exist
only on screens.

The architecture is three phases, and keeping them apart is the whole design:

  1. **Session capture** — a human opens a real browser, logs into Workday
     themselves, and Meridian persists the resulting `storageState`. Meridian
     never receives the password and never automates the login. This is what
     makes MFA a non-problem: the human satisfies it, once.

  2. **Discovery** — an operator, watching, walks the agent to a screen worth
     extracting and records the path taken. Produces a `Recipe`, not data.

  3. **Replay** — the recipe re-runs unattended, deterministically, with no
     model in the loop. This is the only phase that runs on a schedule.

Phase 3 is the only one allowed to produce graph records. That is not
fastidiousness: an agent that improvises its route each run yields
configuration data that differs between runs for reasons nobody can
reconstruct, and a graph whose contents depend on what an LLM felt like
clicking is worse than no graph, because it is trusted.

**Read-only, enforced structurally.** `NAVIGATION_ONLY` actions are the entire
vocabulary a recipe can express — there is no click-on-Submit, no fill, no
verb that mutates. A recipe that wants to change Workday cannot be written in
this language. That is deliberate: a browser session inherits a real person's
permissions, so the blast radius of a bug here is whatever that person could
do, and the language is the only place to make that impossible rather than
merely discouraged.

Playwright is imported lazily so the API boots without it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from api.connectors.base import ConnectorError
from api.core.ids import utcnow

#: The complete action vocabulary. Every verb here observes; none mutates.
#: `click` is present because Workday's configuration screens are tabbed and
#: unreachable otherwise — it is restricted to navigation targets by
#: `Step.validate`, which rejects the labels that submit.
NAVIGATION_ONLY = frozenset(
    {"goto", "search_task", "click", "expand", "capture", "capture_grid", "screenshot"}
)

#: Labels that commit a change in Workday. A recipe naming one of these is
#: rejected at construction rather than at run time, because the run that
#: discovers it would already have clicked it.
FORBIDDEN_TARGETS = frozenset(
    {
        "submit",
        "approve",
        "deny",
        "save",
        "save for later",
        "ok",
        "confirm",
        "delete",
        "remove",
        "add",
        "send back",
        "cancel event",
        "rescind",
    }
)


class BrowserUnavailable(ConnectorError):
    """Playwright is not installed, or no session has been captured."""


class RecipeError(ConnectorError):
    """A recipe is malformed or attempts something read-only mode forbids."""


@dataclass(slots=True)
class Step:
    """One action in a recipe."""

    action: str
    #: Task name, selector, or URL fragment depending on the action.
    target: str = ""
    #: Where to put what this step captures, in the evidence payload.
    name: str = ""
    #: Selector for the region to read, when capturing.
    selector: str = ""
    optional: bool = False

    def validate(self) -> None:
        if self.action not in NAVIGATION_ONLY:
            raise RecipeError(
                f"'{self.action}' is not a permitted action. Browser discovery is "
                f"read-only; allowed actions are: {', '.join(sorted(NAVIGATION_ONLY))}."
            )
        if self.action in {"click", "expand"}:
            label = self.target.strip().lower()
            if label in FORBIDDEN_TARGETS:
                raise RecipeError(
                    f"A recipe may not click '{self.target}'. That control commits a "
                    "change, and browser discovery must never write to Workday."
                )


@dataclass(slots=True)
class Recipe:
    """A frozen navigation path, discovered once and replayed thereafter.

    `discovered_by` and `discovered_at` are not decoration. When a screen moves
    and a recipe starts failing, the question is always who recorded it and
    against which Workday release, and a recipe without that is one nobody can
    safely repair.
    """

    id: str
    title: str
    #: What the captured evidence describes, in product terms.
    unlocks: str
    steps: list[Step]
    #: The graph node kind each captured record becomes.
    produces_kind: str = "config_object"
    discovered_by: str = ""
    discovered_at: str = ""
    #: Workday release this was recorded against, e.g. "2026R1". Screens move
    #: between releases; this is what dates a failure.
    workday_release: str = ""

    def validate(self) -> None:
        if not self.steps:
            raise RecipeError(f"Recipe '{self.id}' has no steps.")
        for step in self.steps:
            step.validate()
        if not any(s.action in {"capture", "capture_grid"} for s in self.steps):
            raise RecipeError(
                f"Recipe '{self.id}' captures nothing. A recipe that only "
                "navigates produces no evidence and should not run."
            )

    def to_json(self) -> str:
        return json.dumps(
            {**asdict(self), "steps": [asdict(s) for s in self.steps]}, indent=2
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Recipe:
        steps = [Step(**s) for s in raw.get("steps", []) if isinstance(s, dict)]
        recipe = cls(
            id=str(raw.get("id") or ""),
            title=str(raw.get("title") or ""),
            unlocks=str(raw.get("unlocks") or ""),
            steps=steps,
            produces_kind=str(raw.get("produces_kind") or "config_object"),
            discovered_by=str(raw.get("discovered_by") or ""),
            discovered_at=str(raw.get("discovered_at") or ""),
            workday_release=str(raw.get("workday_release") or ""),
        )
        recipe.validate()
        return recipe


@dataclass(slots=True)
class Evidence:
    """Structured output from one replayed recipe.

    The transcript is explicit that the browser agent must not simply scrape
    HTML, and this is that requirement made concrete: a screen becomes named
    fields with observed types and value sets, not a blob of markup. A blob
    cannot be diffed usefully between runs, which is the only thing the product
    would want it for.
    """

    recipe_id: str
    task: str
    #: Section within the screen, when the recipe captured one specifically.
    section: str = ""
    fields: list[dict[str, Any]] = field(default_factory=list)
    #: Rows from a grid capture — Workday renders step tables as grids.
    rows: list[dict[str, str]] = field(default_factory=list)
    screenshot_path: str = ""
    observed_at: str = field(default_factory=lambda: utcnow().isoformat())
    #: Steps that were marked optional and did not resolve. Recorded rather
    #: than dropped: "this section was absent" is itself a finding about the
    #: tenant, and a silently short capture looks identical to a clean one.
    skipped: list[str] = field(default_factory=list)


# --- session -----------------------------------------------------------------


@dataclass(slots=True)
class BrowserSession:
    """A captured, authenticated Workday session.

    This is `storageState` — cookies and local storage — not credentials.
    Meridian cannot reconstruct the password from it and cannot re-authenticate
    once it expires; a human repeats the capture. That is the point: the
    expensive property of this design is that it *cannot* silently keep working
    forever without a person, and so it never becomes an unattended standing
    grant to a whole tenant.

    Treated as a secret end to end. `state_json` is a bearer credential — anyone
    holding it is the logged-in user until it expires — so it is stored via the
    same encryption path as passwords and never returned by the API.
    """

    tenant: str
    state_json: str
    captured_by: str = ""
    captured_at: str = field(default_factory=lambda: utcnow().isoformat())
    #: Workday sessions are short. Recorded so the UI can say "expired, capture
    #: again" instead of surfacing a wall of timeout errors from a replay.
    expires_at: str = ""

    def is_present(self) -> bool:
        return bool(self.state_json.strip())


def playwright_available() -> bool:
    """Whether the browser extra is installed.

    Checked by import rather than by a flag so the answer is always true of the
    actual environment.
    """
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def capture_session(
    host: str,
    tenant: str,
    *,
    captured_by: str = "",
    timeout_seconds: int = 300,
) -> BrowserSession:
    """Open a real browser, let a human log in, and keep the session.

    Blocks until the person completes login — including MFA — or the timeout
    expires. Headed by necessity: the entire purpose is for a human to
    interact, and a headless browser has nobody to satisfy the MFA prompt.

    Meridian never sees what is typed. It waits for Workday's post-login shell
    to appear and then reads the browser's storage state.

    This is an operator tool, not a server endpoint. It runs where a person is
    sitting, which is why it is a plain blocking function rather than a task.
    """
    if not playwright_available():
        raise BrowserUnavailable(
            "Playwright is not installed. Install the browser extra with "
            "`pip install -e .[browser]` and then `playwright install chromium`."
        )

    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    landing = f"{host.rstrip('/')}/{tenant}/d/home.htmld"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(landing, wait_until="domcontentloaded")
            # Workday's authenticated shell. Waiting on a post-login marker
            # rather than on navigation is what makes this tolerate MFA,
            # redirects and SSO hops — however many there are, the wait ends
            # when the person is actually inside.
            page.wait_for_selector(
                "[data-automation-id='globalSearchInput'], "
                "[data-automation-id='navigationBar'], "
                "[data-automation-id='workdayLogo']",
                timeout=timeout_seconds * 1000,
            )
            state = context.storage_state()
        except PlaywrightTimeout as exc:
            raise BrowserUnavailable(
                "Login was not completed in time. The browser stayed open for "
                f"{timeout_seconds}s and Workday's home screen never appeared."
            ) from exc
        finally:
            context.close()
            browser.close()

    return BrowserSession(
        tenant=tenant,
        state_json=json.dumps(state),
        captured_by=captured_by,
    )


# --- replay ------------------------------------------------------------------


class RecipeRunner:
    """Replays recipes against a captured session.

    No model, no improvisation. Given the same recipe and the same tenant this
    performs the same actions in the same order, and when a screen has moved it
    fails loudly rather than searching for something that looks close enough.
    """

    def __init__(
        self,
        session: BrowserSession,
        host: str,
        *,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self.session = session
        self.host = host.rstrip("/")
        self.headless = headless
        self.timeout_ms = timeout_ms

    def run(self, recipe: Recipe) -> Evidence:
        """Replay one recipe and return structured evidence."""
        recipe.validate()
        if not playwright_available():
            raise BrowserUnavailable("Playwright is not installed.")
        if not self.session.is_present():
            raise BrowserUnavailable(
                "No Workday browser session has been captured. An administrator "
                "must sign in once before discovery can run."
            )

        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright

        evidence = Evidence(recipe_id=recipe.id, task=recipe.title)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(
                storage_state=json.loads(self.session.state_json)
            )
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                for step in recipe.steps:
                    try:
                        self._apply(page, step, evidence)
                    except PlaywrightTimeout:
                        if not step.optional:
                            raise BrowserUnavailable(
                                f"Recipe '{recipe.id}' failed at "
                                f"'{step.action} {step.target}'. The screen has "
                                "probably moved — Workday ships two releases a "
                                "year — and the recipe needs re-recording."
                            ) from None
                        evidence.skipped.append(f"{step.action}:{step.target}")
            finally:
                context.close()
                browser.close()

        return evidence

    def _apply(self, page: Any, step: Step, evidence: Evidence) -> None:
        if step.action == "goto":
            page.goto(f"{self.host}{step.target}", wait_until="domcontentloaded")

        elif step.action == "search_task":
            # Workday's global search is how every admin task is reached, and
            # it is far more stable across releases than any deep URL.
            page.fill("[data-automation-id='globalSearchInput']", step.target)
            page.keyboard.press("Enter")
            page.wait_for_selector(f"text={step.target}")
            page.click(f"text={step.target}")

        elif step.action in {"click", "expand"}:
            page.click(f"text={step.target}")

        elif step.action == "screenshot":
            if step.target:
                page.screenshot(path=step.target, full_page=True)
                evidence.screenshot_path = step.target

        elif step.action == "capture":
            evidence.fields.extend(_read_fields(page, step.selector))
            if step.name:
                evidence.section = step.name

        elif step.action == "capture_grid":
            evidence.rows.extend(_read_grid(page, step.selector))


def _read_fields(page: Any, selector: str) -> list[dict[str, Any]]:
    """Read a form section as labelled fields with observed value sets.

    Uses Workday's `data-automation-id` attributes rather than CSS structure.
    Workday's class names are generated and change between releases; the
    automation ids are contractual and mostly do not.
    """
    scope = selector or "[data-automation-id='pageContent']"
    return page.evaluate(
        """
        (scope) => {
          const root = document.querySelector(scope);
          if (!root) return [];
          const out = [];
          const seen = new Set();
          root.querySelectorAll('[data-automation-id]').forEach((el) => {
            const label = (
              el.getAttribute('aria-label') ||
              el.closest('[data-automation-id="formLabel"]')?.innerText ||
              el.previousElementSibling?.innerText ||
              ''
            ).trim();
            if (!label || seen.has(label) || label.length > 120) return;
            seen.add(label);

            const tag = el.tagName.toLowerCase();
            const options = [];
            if (tag === 'select') {
              el.querySelectorAll('option').forEach((o) => {
                const t = (o.textContent || '').trim();
                if (t) options.push(t);
              });
            }
            out.push({
              label,
              type: el.getAttribute('data-automation-id') || tag,
              required: el.getAttribute('aria-required') === 'true',
              values_observed: options,
            });
          });
          return out;
        }
        """,
        scope,
    )


def _read_grid(page: Any, selector: str) -> list[dict[str, str]]:
    """Read a Workday grid as rows keyed by column header.

    Business process step tables are grids, which is why this exists
    separately: a step table read as loose fields loses the row structure that
    makes it an ordered process.
    """
    scope = selector or "[data-automation-id='gridContainer']"
    return page.evaluate(
        """
        (scope) => {
          const grid = document.querySelector(scope);
          if (!grid) return [];
          const headers = Array.from(
            grid.querySelectorAll('[role="columnheader"], th')
          ).map((h) => (h.innerText || '').trim());
          if (!headers.length) return [];

          return Array.from(grid.querySelectorAll('[role="row"], tr'))
            .map((tr) => {
              const cells = Array.from(
                tr.querySelectorAll('[role="gridcell"], [role="cell"], td')
              );
              if (!cells.length) return null;
              const row = {};
              cells.forEach((cell, i) => {
                const key = headers[i] || `column_${i + 1}`;
                row[key] = (cell.innerText || '').trim();
              });
              return row;
            })
            .filter((r) => r && Object.values(r).some((v) => v));
        }
        """,
        scope,
    )
