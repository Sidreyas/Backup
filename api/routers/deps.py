"""
Shared request dependencies.

Authentication is not built. Rather than pretend otherwise with a fake token
check, the current actor comes from a header with a documented default, and the
gap is stated in one place instead of being implied across twenty endpoints.

This matters more than usual here: every governance record names an actor, and
an actor the system cannot actually authenticate is an actor an auditor cannot
rely on. When auth lands, this module is the only thing that changes — and the
audit chain written before that point should be understood as attributing
actions to a claimed identity rather than a verified one.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header

# The seeded demonstration user. Matches CURRENT_USER in the frontend so the
# two agree about who is acting until real sessions exist.
DEFAULT_ACTOR = ("Sathish Kumar", "sathish.kumar@acme.example", "QA Lead")

# Default governance scope, matching the seeded workspace.
DEFAULT_WORKSPACE = "ws-acme"


@dataclass(slots=True)
class Actor:
    name: str
    email: str
    role: str

    @property
    def unverified(self) -> bool:
        """True while no authentication exists.

        Read by the audit layer so the record can be honest about the fact that
        this identity was asserted by the client rather than proven.
        """
        return True


def current_actor(
    x_actor_name: str | None = Header(default=None),
    x_actor_email: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
) -> Actor:
    name, email, role = DEFAULT_ACTOR
    return Actor(
        name=x_actor_name or name,
        email=x_actor_email or email,
        role=x_actor_role or role,
    )


def current_workspace(x_workspace_id: str | None = Header(default=None)) -> str:
    return x_workspace_id or DEFAULT_WORKSPACE
