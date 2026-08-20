"""
GitHub connector.

Extracts the delivery layer: repositories, their code structure, pull requests
and workflow definitions. The point is not to index every line of code — it is
to answer "which component implements this requirement, and what changed it".

What this deliberately does *not* do is clone and parse every file. A full code
graph is a different product with different costs. What it extracts is the
skeleton that connects business intent to implementation:

  - repositories and their languages (what exists)
  - top-level source structure (where things live)
  - pull requests with linked issue references (why a change happened)
  - CI workflow definitions (how it reaches production)

Issue references in PR titles and bodies are what close the traceability loop
back to Jira. They are emitted as *candidate* relations with a confidence,
never as facts — a PR mentioning "MER-1042" is evidence of a link, not proof of
one, and the graph keeps that distinction.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx

from api.connectors.base import (
    AccessCheck,
    ConnectorCapability,
    ConnectorScope,
    EnterpriseConnector,
    NotConfigured,
    RawRecord,
)
from api.core.config import settings

PAGE_SIZE = 100
MAX_PAGES = 20

# Conventional issue keys: MER-1042, PROJ-7. Matched case-sensitively on the
# project part because lowercase words followed by a number ("v-2", "step-3")
# are overwhelmingly not issue keys, and a false link is worse than a missing
# one in a graph people are asked to trust.
ISSUE_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")


class GitHubConnector(EnterpriseConnector):
    id = "cx-github"
    name = "GitHub"
    vendor = "GitHub, Inc."
    category = "code"
    kind = "repository"
    description = (
        "Reads repositories, pull requests and CI workflows so a requirement can "
        "be traced to the code and pipeline that implement it."
    )
    auth_methods = ["oauth2", "api_key"]
    provides = ["Code components", "Pull requests", "Pipeline definitions"]
    extractor_version = "1"

    scopes = [
        ConnectorScope(
            id="read.repo",
            label="Read repository metadata and contents",
            description="Repository structure, languages and CI workflow files.",
            required=True,
        ),
        ConnectorScope(
            id="read.pulls",
            label="Read pull requests",
            description="Pull requests and their linked issues, for traceability.",
            required=False,
        ),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.token = self.config.get("token") or settings.github_token
        self.api_url = (self.config.get("api_url") or settings.github_api_url).rstrip("/")
        # Which repositories to read. Without this the connector would try to
        # enumerate everything the token can see, which on an enterprise
        # account is both enormous and almost never what was intended.
        #
        # Accepts a list or the comma-separated string the connection form
        # produces. Left as a raw string it would be treated as one repository
        # literally named "acme/one, acme/two", which 404s in a way that looks
        # like a permissions problem.
        raw_repos = self.config.get("repos") or []
        self.repos: list[str] = (
            [r.strip() for r in raw_repos.split(",") if r.strip()]
            if isinstance(raw_repos, str)
            else list(raw_repos)
        )
        self.org: str = (self.config.get("org") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.token)

    def _client(self) -> httpx.Client:
        if not self.is_configured():
            raise NotConfigured("GitHub is not configured. Set GITHUB_TOKEN.")
        return httpx.Client(
            base_url=self.api_url,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def discover_capabilities(self) -> list[ConnectorCapability]:
        return [
            ConnectorCapability(
                id="github.repos",
                label="Repositories and structure",
                layer="configuration",
                node_kinds=["code_module"],
                requires_scopes=["read.repo"],
            ),
            ConnectorCapability(
                id="github.workflows",
                label="CI workflow definitions",
                layer="configuration",
                node_kinds=["integration"],
                requires_scopes=["read.repo"],
            ),
            ConnectorCapability(
                id="github.pulls",
                label="Pull requests and linked issues",
                layer="runtime",
                node_kinds=["code_module"],
                requires_scopes=["read.pulls"],
            ),
        ]

    def validate_access(self) -> AccessCheck:
        if not self.is_configured():
            return AccessCheck(ok=False, message="Not configured. Set GITHUB_TOKEN.")
        try:
            with self._client() as client:
                resp = client.get("/user")
                resp.raise_for_status()
                login = resp.json().get("login", "unknown")

                # The token's scopes come back on the response header for
                # classic PATs. Fine-grained tokens omit it, so its absence is
                # reported as unknown rather than as missing access — claiming
                # a scope is missing when it simply is not advertised would
                # send operators chasing a problem that does not exist.
                header = resp.headers.get("x-oauth-scopes")
                effective = (
                    [s.strip() for s in header.split(",") if s.strip()]
                    if header
                    else ["(fine-grained token; scopes not advertised)"]
                )
            return AccessCheck(
                ok=True,
                message=f"Connected to GitHub as {login}.",
                effective_scopes=effective,
            )
        except httpx.HTTPStatusError as exc:
            return AccessCheck(
                ok=False,
                message=f"GitHub rejected the token ({exc.response.status_code}).",
            )
        except httpx.HTTPError as exc:
            return AccessCheck(ok=False, message=f"Could not reach GitHub: {exc}")

    def _target_repos(self, client: httpx.Client) -> list[dict]:
        if self.repos:
            out = []
            for full_name in self.repos:
                resp = client.get(f"/repos/{full_name}")
                if resp.status_code == 200:
                    out.append(resp.json())
            return out
        if self.org:
            resp = client.get(f"/orgs/{self.org}/repos", params={"per_page": PAGE_SIZE})
            resp.raise_for_status()
            return resp.json()
        resp = client.get("/user/repos", params={"per_page": PAGE_SIZE, "affiliation": "owner"})
        resp.raise_for_status()
        return resp.json()

    def snapshot(self) -> Iterator[RawRecord]:
        with self._client() as client:
            for repo in self._target_repos(client):
                full = repo["full_name"]
                yield RawRecord(
                    kind="code_module",
                    natural_key=f"github:repo:{repo['id']}",
                    label=full,
                    payload={
                        "name": repo["name"],
                        "fullName": full,
                        "description": repo.get("description"),
                        "language": repo.get("language"),
                        "defaultBranch": repo.get("default_branch"),
                        "private": repo.get("private"),
                        "topics": repo.get("topics", []),
                    },
                    source_ref=repo.get("html_url", ""),
                    provenance=f"GitHub › Repository › {full}",
                    layer="configuration",
                )
                yield from self._workflows(client, repo)

    def _workflows(self, client: httpx.Client, repo: dict) -> Iterator[RawRecord]:
        """CI workflow definitions — how code reaches an environment."""
        full = repo["full_name"]
        resp = client.get(f"/repos/{full}/actions/workflows")
        if resp.status_code != 200:
            return
        for wf in resp.json().get("workflows", []):
            yield RawRecord(
                kind="integration",
                natural_key=f"github:workflow:{wf['id']}",
                label=f"{full} › {wf.get('name')}",
                payload={
                    "name": wf.get("name"),
                    "path": wf.get("path"),
                    "state": wf.get("state"),
                    "repo": full,
                },
                source_ref=wf.get("html_url", ""),
                provenance=f"GitHub › {full} › {wf.get('path')}",
                layer="configuration",
                relations=[("DEPLOYED_TO", f"github:repo:{repo['id']}")],
            )

    def observe(self) -> Iterator[RawRecord]:
        """Pull requests — the runtime record of what actually changed."""
        with self._client() as client:
            for repo in self._target_repos(client):
                full = repo["full_name"]
                for page in range(1, MAX_PAGES + 1):
                    resp = client.get(
                        f"/repos/{full}/pulls",
                        params={
                            "state": "all",
                            "per_page": PAGE_SIZE,
                            "page": page,
                            "sort": "updated",
                            "direction": "desc",
                        },
                    )
                    if resp.status_code != 200:
                        break
                    pulls = resp.json()
                    if not pulls:
                        break

                    for pr in pulls:
                        text = f"{pr.get('title', '')} {pr.get('body') or ''}"
                        keys = sorted(set(ISSUE_KEY.findall(text)))
                        # Candidate links only. A mention is evidence, not proof.
                        relations = [("IMPLEMENTED_BY", f"jira:issue:{k}") for k in keys]

                        yield RawRecord(
                            kind="code_module",
                            natural_key=f"github:pr:{pr['id']}",
                            label=f"{full}#{pr['number']} — {pr.get('title', '')}",
                            payload={
                                "number": pr["number"],
                                "title": pr.get("title"),
                                "state": pr.get("state"),
                                "merged": bool(pr.get("merged_at")),
                                "mergedAt": pr.get("merged_at"),
                                "author": (pr.get("user") or {}).get("login"),
                                "repo": full,
                                "referencedIssueKeys": keys,
                            },
                            source_ref=pr.get("html_url", ""),
                            provenance=f"GitHub › {full} › PR #{pr['number']}",
                            layer="runtime",
                            relations=relations,
                        )

    def subscribe_to_changes(self) -> str | None:
        return "/webhooks/github"
