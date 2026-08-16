"""What each OFM role is allowed to do.

Deliberately the single place where capability decisions live. Today the only
distinction is that the owner may delete the OFM — everything else is open to
every member. A richer permission system is expected, so callers ask
``can(role, Action.X)`` rather than comparing role strings, and new roles or
actions can be added here without touching route handlers.
"""

from __future__ import annotations

from enum import Enum

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"

#: Roles that may be handed out via an invitation.
ASSIGNABLE_ROLES = (ROLE_EDITOR,)


class Action(str, Enum):
    VIEW_OFM = "view_ofm"
    RENAME_OFM = "rename_ofm"
    DELETE_OFM = "delete_ofm"
    EDIT_PIECES = "edit_pieces"
    INVITE_MEMBERS = "invite_members"
    REMOVE_MEMBERS = "remove_members"


#: Actions denied to non-owners. Everything absent from this map is allowed to
#: any member, which matches "only the owner can remove it".
_OWNER_ONLY: frozenset[Action] = frozenset({Action.DELETE_OFM})


def can(role: str | None, action: Action) -> bool:
    if role is None:
        return False
    if action in _OWNER_ONLY:
        return role == ROLE_OWNER
    return True


def describe_denial(action: Action) -> str:
    if action is Action.DELETE_OFM:
        return "Only the owner of this OFM can delete it."
    return "You do not have permission to perform this action."
