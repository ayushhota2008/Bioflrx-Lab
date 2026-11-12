"""
Unit and integration tests for auto-adding feedstocks, structured route drafting,
and the human review / promotion workflow (Step 7 requirements).
"""

from unittest.mock import patch
import pytest

import config
from services.openalex_service import (
    normalize_material_name,
    is_plausible_renewable_material,
)
from services.database_service import (
    get_material_by_name,
    get_routes_for_material,
    save_route_with_steps,
    get_saved_paper_count,
)
from services.feedstock_service import classify_feedstock
from services.review_service import (
    verify_admin_password,
    promote_route_to_verified,
    reject_route,
)


def test_seed_verified_materials_unchanged():
    """Sugarcane and banana peel show human_verified routes unchanged without adding duplicate rows."""
    res_cane = classify_feedstock("sugarcane", search_api=False, generate_route=False)
    assert res_cane["category"] == "A"
    assert res_cane["route_status"] == "human_verified"
    assert "Verified route: reviewed by a human" in res_cane["banner_text"]
    assert len(res_cane["routes"]) >= 1
    assert res_cane["routes"][0]["reviewed_by_human"] is True

    res_banana = classify_feedstock("banana peels", search_api=False, generate_route=False)
    assert res_banana["category"] == "A"
    assert res_banana["route_status"] == "human_verified"
    assert res_banana["material"] == "banana peel"


def test_spacing_and_plural_normalization():
    """Verify 'potato  starch' and 'Potato Starches' normalize to 'potato starch'."""
    assert normalize_material_name("potato  starch") == "potato starch"
    assert normalize_material_name("Potato Starches") == "potato starch"
    assert normalize_material_name("  Banana Peels  ") == "banana peel"
    assert normalize_material_name("rice husks") == "rice husk"


def test_relevance_gate_fails_on_sand_and_xyzfoo():
    """Relevance gate fails for sand and xyzfoo without creating database records."""
    assert is_plausible_renewable_material("sand") is False
    assert is_plausible_renewable_material("laptop") is False

    res_sand = classify_feedstock("sand", search_api=False, generate_route=False)
    assert res_sand["category"] == "C"
    assert "did not find sufficiently relevant research" in res_sand["banner_text"]
    assert len(res_sand["routes"]) == 0

    # Ensure no raw_material record was created for sand
    assert get_material_by_name("sand") is None

    # Test xyzfoo: passes preliminary plausibility but returns 0 relevant papers
    with patch("services.feedstock_service.search_papers_multi_query") as mock_search:
        mock_search.return_value = {
            "material": "xyzfoo",
            "total_results": 0,
            "papers": [],
            "relevant_papers": [],
            "error": None,
        }
        res_xyz = classify_feedstock("xyzfoo", search_api=True, generate_route=True)
        assert res_xyz["category"] == "C"
        assert get_material_by_name("xyzfoo") is None


def test_openalex_timeout_returns_error_not_c():
    """Simulated OpenAlex timeout returns search failed message with no partial record."""
    with patch("services.feedstock_service.search_papers_multi_query") as mock_search:
        mock_search.return_value = {
            "material": "unseen_feedstock_timeout",
            "total_results": 0,
            "papers": [],
            "relevant_papers": [],
            "error": "The request to OpenAlex timed out.",
        }
        res = classify_feedstock("unseen_feedstock_timeout", search_api=True, generate_route=True)
        assert res["category"] == "ERROR"
        assert res["category"] != "C"
        assert "Search failed" in res["banner_text"]


def test_save_route_with_steps_and_never_overwrite_verified():
    """Verify route saving as ai_draft, and ensure human_verified routes are never downgraded."""
    import uuid
    test_mat = f"test_feedstock_{uuid.uuid4().hex[:6]}"
    route_data = {
        "product_name": "Test Starch Film",
        "route_summary": "Extrusion and casting of starch.",
        "route_type": "Extrusion",
        "evidence_level": "Laboratory Demonstration",
        "steps": [
            {
                "step_number": 1,
                "title": "Extraction",
                "description": "Aqueous extraction.",
                "required_inputs": "water",
                "conditions": "room temp",
                "supporting_paper_id": None,
            }
        ],
    }

    try:
        # 1. Save as ai_draft
        route_id = save_route_with_steps(test_mat, route_data, review_status="ai_draft")
        assert route_id is not None

        routes = get_routes_for_material(test_mat)
        assert len(routes) == 1
        assert routes[0]["review_status"] == "ai_draft"
        assert routes[0]["reviewed_by_human"] is False

        # 2. Promote to human_verified
        res_promote = promote_route_to_verified(route_id, "Dr. Scientist", config.ADMIN_PASSWORD)
        assert res_promote["success"] is True

        routes_verified = get_routes_for_material(test_mat)
        assert routes_verified[0]["review_status"] == "human_verified"
        assert routes_verified[0]["reviewed_by_human"] is True

        # 3. Attempt to save again as ai_draft (simulating repeat AI query): MUST NOT downgrade!
        save_route_with_steps(test_mat, route_data, review_status="ai_draft")
        routes_after = get_routes_for_material(test_mat)
        assert routes_after[0]["review_status"] == "human_verified"
        assert routes_after[0]["reviewed_by_human"] is True
    finally:
        from services.database_service import get_connection, release_connection
        _conn = get_connection()
        try:
            with _conn.cursor() as _cur:
                _cur.execute("DELETE FROM process_steps WHERE route_id IN (SELECT id FROM production_routes WHERE material_id IN (SELECT id FROM raw_materials WHERE name = %s));", (test_mat,))
                _cur.execute("DELETE FROM production_routes WHERE material_id IN (SELECT id FROM raw_materials WHERE name = %s);", (test_mat,))
                _cur.execute("DELETE FROM raw_materials WHERE name = %s;", (test_mat,))
            _conn.commit()
        finally:
            release_connection(_conn)


def test_human_review_authorization():
    """Verify unauthorized review attempts are rejected at the backend service layer."""
    # Wrong password
    bad_res = promote_route_to_verified(999999, "Reviewer", "wrong_password_123")
    assert bad_res["success"] is False
    assert "Unauthorized" in bad_res["error"]

    bad_reject = reject_route(999999, "wrong_password_123")
    assert bad_reject["success"] is False
    assert "Unauthorized" in bad_reject["error"]

    # Valid admin password check
    assert verify_admin_password(config.ADMIN_PASSWORD) is True
    assert verify_admin_password("bad_pass") is False
