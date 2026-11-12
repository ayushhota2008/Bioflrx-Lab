"""
Review Service for BioFlex Lab.
Manages promotion of AI-drafted production routes to human_verified,
editing, and rejection with backend authorization enforcement.
"""

from typing import Any, Dict, List, Optional
import config
from services.database_service import (
    get_routes_by_review_status,
    update_route_review_status,
)


def verify_admin_password(password: str) -> bool:
    """Verify administrator password against configuration; rejects if unconfigured."""
    expected = (config.ADMIN_PASSWORD or "").strip()
    return bool(expected and password and password.strip() == expected)


def promote_route_to_verified(
    route_id: int,
    reviewer_name: str,
    admin_password: str,
    edited_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Promote an AI-drafted production route to 'human_verified'.
    Enforces authorization check before committing update.
    """
    if not verify_admin_password(admin_password):
        return {
            "success": False,
            "error": "Unauthorized: Invalid administrator password.",
        }

    reviewer = reviewer_name.strip() if reviewer_name and reviewer_name.strip() else "Domain Expert"
    success = update_route_review_status(
        route_id=route_id,
        new_status="human_verified",
        reviewer_name=reviewer,
        edited_data=edited_data,
    )
    if success:
        return {
            "success": True,
            "error": None,
            "message": f"Route #{route_id} promoted to human_verified by {reviewer}.",
        }
    return {"success": False, "error": "Database update failed."}


def reject_route(
    route_id: int,
    admin_password: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reject an AI-drafted production route.
    Enforces authorization check before committing update.
    """
    if not verify_admin_password(admin_password):
        return {
            "success": False,
            "error": "Unauthorized: Invalid administrator password.",
        }

    success = update_route_review_status(
        route_id=route_id,
        new_status="rejected",
        reviewer_name=f"Rejected: {reason or 'Unspecified'}",
    )
    if success:
        return {
            "success": True,
            "error": None,
            "message": f"Route #{route_id} marked as rejected.",
        }
    return {"success": False, "error": "Database update failed."}


def get_pending_drafts(admin_password: str) -> List[Dict[str, Any]]:
    """Retrieve all pending AI drafts if authorized."""
    if not verify_admin_password(admin_password):
        return []
    return get_routes_by_review_status("ai_draft")

