"""Default org RBAC permissions (mirrors public.get_default_permissions)."""

from __future__ import annotations

import base64
import secrets
from typing import Any, Dict

DEFAULT_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    "admin": {
        "can_create_projects": True,
        "can_edit_projects": True,
        "can_delete_projects": True,
        "can_view_reports": True,
        "can_manage_users": True,
        "can_manage_organizations": True,
        "can_invite_users": True,
        "can_remove_users": True,
        "can_edit_permissions": True,
    },
    "user": {
        "can_create_projects": True,
        "can_edit_projects": True,
        "can_delete_projects": False,
        "can_view_reports": True,
        "can_manage_users": False,
        "can_manage_organizations": False,
        "can_invite_users": False,
        "can_remove_users": False,
        "can_edit_permissions": False,
    },
    "editor": {
        "can_create_projects": True,
        "can_edit_projects": True,
        "can_delete_projects": False,
        "can_view_reports": True,
        "can_manage_users": False,
        "can_manage_organizations": False,
        "can_invite_users": False,
        "can_remove_users": False,
        "can_edit_permissions": False,
    },
    "viewer": {
        "can_create_projects": False,
        "can_edit_projects": False,
        "can_delete_projects": False,
        "can_view_reports": True,
        "can_manage_users": False,
        "can_manage_organizations": False,
        "can_invite_users": False,
        "can_remove_users": False,
        "can_edit_permissions": False,
    },
}


def get_default_permissions(role: str) -> Dict[str, Any]:
    return dict(DEFAULT_PERMISSIONS.get((role or "").lower(), {}))


def generate_invitation_token() -> str:
    """Opaque token; mirrors encode(gen_random_bytes(32), 'base64')."""
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")
