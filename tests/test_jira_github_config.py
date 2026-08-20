"""
Jira and GitHub: configuration supplied through the connection form.

Both connectors predate the credential form and originally read only from
environment variables. These tests cover the path a real user takes — values
typed into the UI, stored encrypted, handed back as a config dict — and the
normalisation that path needs, because a form produces strings where the
connector wants lists and produces pasted URLs where it wants a site root.
"""

from __future__ import annotations

import pytest

from api.connectors import registry
from api.connectors.github import GitHubConnector
from api.connectors.jira import JiraConnector
from api.core import secrets
from api.services import connections as service


# --- GitHub ---------------------------------------------------------------


def test_github_accepts_the_comma_separated_string_the_form_produces():
    """Left as a raw string this reads as one repo literally named
    'acme/one, acme/two', which 404s in a way that looks like a permissions
    problem rather than a parsing one."""
    conn = GitHubConnector({"token": "T", "repos": "acme/one, acme/two"})
    assert conn.repos == ["acme/one", "acme/two"]


def test_github_still_accepts_a_list():
    assert GitHubConnector({"token": "T", "repos": ["a/b"]}).repos == ["a/b"]


def test_github_ignores_empty_repo_entries():
    conn = GitHubConnector({"token": "T", "repos": "a/b, , c/d,"})
    assert conn.repos == ["a/b", "c/d"]


def test_github_org_is_trimmed():
    assert GitHubConnector({"token": "T", "org": "  acme  "}).org == "acme"


def test_github_unconfigured_without_a_token():
    assert GitHubConnector({}).is_configured() is False
    assert GitHubConnector({"token": "T"}).is_configured() is True


# --- Jira -----------------------------------------------------------------


@pytest.mark.parametrize(
    "pasted",
    [
        "https://acme.atlassian.net",
        "https://acme.atlassian.net/",
        "https://acme.atlassian.net/browse/HCM-1",
        "https://acme.atlassian.net/secure/Dashboard.jspa",
    ],
)
def test_jira_site_url_is_normalised_to_the_site_root(pasted):
    """People paste the URL of whatever page they are looking at."""
    conn = JiraConnector({"base_url": pasted, "email": "a@b.c", "api_token": "T"})
    assert conn.base_url == "https://acme.atlassian.net"


def test_jira_needs_all_three_values():
    assert JiraConnector({"base_url": "https://x.atlassian.net"}).is_configured() is False
    assert (
        JiraConnector(
            {"base_url": "https://x.atlassian.net", "email": "a@b.c", "api_token": "T"}
        ).is_configured()
        is True
    )


# --- what the connection form declares ------------------------------------


@pytest.mark.parametrize("connector_id", ["cx-jira", "cx-github"])
def test_connector_declares_a_connection_form(connector_id):
    """Without credential fields the connect wizard has nothing to ask for and
    the connector is only configurable through environment variables."""
    entry = registry.get(connector_id)
    assert entry.credential_fields, f"{connector_id} declares no credential fields"
    assert entry.setup_steps, f"{connector_id} declares no setup steps"
    assert entry.limitations, f"{connector_id} declares no limitations"


@pytest.mark.parametrize(
    ("connector_id", "secret_id"),
    [("cx-jira", "api_token"), ("cx-github", "token")],
)
def test_the_credential_is_declared_as_a_secret(connector_id, secret_id):
    """Encryption follows the declared kind, so getting this wrong writes a
    live token into a plaintext JSON column."""
    entry = registry.get(connector_id)
    field = next(f for f in entry.credential_fields if f.id == secret_id)
    assert field.kind == "password"
    assert field.id in secrets.SENSITIVE_FIELDS


@pytest.mark.parametrize(
    ("connector_id", "values", "secret_id"),
    [
        (
            "cx-jira",
            {
                "base_url": "https://acme.atlassian.net",
                "email": "a@b.c",
                "api_token": "REAL-JIRA-TOKEN",
            },
            "api_token",
        ),
        (
            "cx-github",
            {"token": "REAL-GITHUB-TOKEN", "org": "acme"},
            "token",
        ),
    ],
)
def test_secret_never_reaches_the_plaintext_settings_column(
    connector_id, values, secret_id
):
    """The split that keeps a database dump from being a credential leak."""
    secret_values, settings_values = service.split_credentials(connector_id, values)

    assert secret_id in secret_values
    assert secret_id not in settings_values
    assert "REAL-" not in str(settings_values)


@pytest.mark.parametrize("connector_id", ["cx-jira", "cx-github"])
def test_required_fields_are_reported_by_label(connector_id):
    missing = service.validate_required(connector_id, {})
    assert missing, "an empty form should report what it needs"
    # Labels, not field ids — these are shown to a person.
    assert all(m[0].isupper() for m in missing), missing


def test_optional_fields_are_not_demanded():
    """Jira's JQL filter and GitHub's org are genuinely optional."""
    assert "Issue filter (JQL)" not in service.validate_required(
        "cx-jira",
        {
            "base_url": "https://acme.atlassian.net",
            "email": "a@b.c",
            "api_token": "T",
        },
    )
    assert service.validate_required("cx-github", {"token": "T"}) == []


@pytest.mark.parametrize("connector_id", ["cx-jira", "cx-github"])
def test_no_declared_scope_grants_write(connector_id):
    entry = registry.get(connector_id)
    assert not [s for s in entry.scopes if s.writes]


def test_github_setup_flags_the_two_permission_traps():
    """Actions alone lists a workflow's name; reading its YAML needs Contents.
    Granting only the obvious one produces pipelines with no visible steps."""
    steps = registry.get("cx-github").setup_steps
    permissions = next(s for s in steps if s["id"] == "permissions")
    assert permissions.get("critical") is True
    assert "Contents" in permissions["detail"]
    assert "Actions" in permissions["detail"]

    token_step = next(s for s in steps if s["id"] == "token")
    assert token_step.get("critical") is True
    assert "classic" in token_step["why"].lower()


def test_jira_setup_flags_token_expiry():
    """Atlassian caps tokens at a year, so this is an operational fact rather
    than a one-off setup detail."""
    steps = registry.get("cx-jira").setup_steps
    expiry = next(s for s in steps if s["id"] == "expiry")
    assert expiry.get("critical") is True
    text = f"{expiry['title']} {expiry['detail']} {expiry['why']}".lower()
    assert "one year" in text
    assert "expir" in text  # expire / expiry / non-expiring
