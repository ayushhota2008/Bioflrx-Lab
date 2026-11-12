"""
Unit tests for feedstock canonicalization, typo handling, fuzzy matching, and alias resolution.
"""

import pytest
from unittest.mock import patch

import config
from services.feedstock_service import (
    check_feedstock_canonical,
    classify_feedstock,
    is_likely_typo,
)
from services.database_service import (
    get_material_by_name,
    add_material_alias,
    get_connection,
    release_connection,
)
from services.gemini_service import check_canonical_material_name


def test_potato_strach_resolves_to_potato_starch_via_alias():
    """Verify that 'Potato Strach' exact-matches to 'potato starch' via database aliases."""
    res = check_feedstock_canonical("Potato Strach")
    assert res["action"] == "exact_match"
    assert res["canonical_name"].lower() == "potato starch"
    assert res["is_alias"] is True


def test_potato_starch_exact_match():
    """Verify that 'potato starch' finds the existing record directly as exact match."""
    res = check_feedstock_canonical("potato starch")
    assert res["action"] == "exact_match"
    assert res["canonical_name"].lower() == "potato starch"
    assert res["is_alias"] is False


def test_fuzzy_match_rice_hsuk_suggests_rice_husk():
    """Verify that 'Rice Hsuk' fuzzy matches against existing feedstock 'rice husk'."""
    res = check_feedstock_canonical("Rice Hsuk")
    assert res["action"] == "suggest"
    assert res["suggested_name"].lower() == "rice husk"


def test_relevance_gate_rejects_sand_zero_db_creation():
    """Verify that searching 'sand' is rejected by relevance gate with zero records created."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'sand';")
            assert cur.fetchone() is None
    finally:
        release_connection(conn)

    res = classify_feedstock("sand", search_api=True, generate_summary=False, generate_route=False)
    assert res["category"] == "C"
    assert "not find sufficiently relevant research" in res["banner_text"]
    assert res["newly_created"] is False

    # Verify still zero records
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'sand';")
            assert cur.fetchone() is None
    finally:
        release_connection(conn)


def test_relevance_gate_rejects_xyzfoo_nonsense():
    """Verify that nonsense query 'xyzfoo' fails relevance gate with zero records created."""
    res = classify_feedstock("xyzfoo", search_api=True, generate_summary=False, generate_route=False)
    assert res["category"] == "C"
    assert res["newly_created"] is False

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'xyzfoo';")
            assert cur.fetchone() is None
    finally:
        release_connection(conn)


def test_verified_sugarcane_untouched():
    """Verify that priority verified feedstock 'sugarcane' remains Category A and human-verified."""
    canon = check_feedstock_canonical("sugarcane")
    assert canon["action"] == "exact_match"
    assert canon["canonical_name"].lower() == "sugarcane"

    res = classify_feedstock("sugarcane", search_api=False, generate_summary=False, generate_route=False)
    assert res["category"] == "A"
    assert res["route_status"] == "human_verified"
    assert len(res["routes"]) >= 1
    assert res["routes"][0]["reviewed_by_human"] is True


def test_verified_banana_peel_untouched():
    """Verify that priority verified feedstock 'banana peel' remains Category A and human-verified."""
    canon = check_feedstock_canonical("banana peel")
    assert canon["action"] == "exact_match"
    assert canon["canonical_name"].lower() == "banana peel"

    res = classify_feedstock("banana peel", search_api=False, generate_summary=False, generate_route=False)
    assert res["category"] == "A"
    assert res["route_status"] == "human_verified"
    assert len(res["routes"]) >= 1
    assert res["routes"][0]["reviewed_by_human"] is True


def test_alias_persistence_lifecycle():
    """Verify adding an alias dynamically allows immediate subsequent resolution without prompting."""
    test_alias = "potat_o_strrarch_test"
    canonical = "potato starch"

    # Before alias: does not exact match this alias
    pre = check_feedstock_canonical(test_alias)
    assert pre["action"] != "exact_match"

    # Add alias
    added = add_material_alias(canonical, test_alias)
    assert added is True

    try:
        # After alias: exact match immediately
        post = check_feedstock_canonical(test_alias)
        assert post["action"] == "exact_match"
        assert post["canonical_name"].lower() == canonical
        assert post["is_alias"] is True
    finally:
        # Clean up test alias
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE raw_materials SET aliases = array_remove(aliases, %s) WHERE LOWER(name) = %s;",
                    (test_alias, canonical),
                )
                conn.commit()
        finally:
            release_connection(conn)


def test_distinct_materials_with_shared_suffixes_not_confused():
    """Verify that distinct feedstocks sharing a component word (e.g. 'starch', 'straw') are not falsely marked as typos."""
    # Direct typo detector function checks
    assert is_likely_typo("cane starch", "corn starch") is False
    assert is_likely_typo("pea starch", "potato starch") is False
    assert is_likely_typo("wheat straw", "oat straw") is False
    assert is_likely_typo("rice straw", "rice husk") is False

    # Pipeline integration: searching 'cane starch' must not suggest 'corn starch'
    res_cane = check_feedstock_canonical("cane starch")
    assert res_cane.get("suggested_name") != "corn starch"
    assert res_cane["action"] == "proceed"

    # Searching 'pea starch' must not suggest 'potato starch'
    res_pea = check_feedstock_canonical("pea starch")
    assert res_pea.get("suggested_name") != "potato starch"
    assert res_pea["action"] == "proceed"


def test_actual_typos_detected_by_token_guard():
    """Verify that true typos (transposition, deletion, insertion) are reliably detected."""
    assert is_likely_typo("corn stach", "corn starch") is True
    assert is_likely_typo("rice hsuk", "rice husk") is True
    assert is_likely_typo("potato strach", "potato starch") is True
    assert is_likely_typo("banana pel", "banana peel") is True
    assert is_likely_typo("sugarcne", "sugarcane") is True
    assert is_likely_typo("baggasse", "bagasse") is True


