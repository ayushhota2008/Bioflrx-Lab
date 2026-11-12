"""
Unit and integration tests for Neon Database Service (Phase 3).
Verifies schema, connections, paper persistence, duplicate prevention, and route queries.
"""

import pytest
from services.database_service import (
    get_connection,
    release_connection,
    init_db,
    get_all_materials,
    get_material_by_name,
    save_paper,
    save_papers_batch,
    get_papers_for_material,
    get_saved_paper_count,
    get_routes_for_material,
    get_feedstock_summary,
    save_feedstock_summary,
)

@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Ensure database schema and seeds are applied once before running tests."""
    init_db()

def test_neon_connection():
    """Verify active connection to Neon PostgreSQL."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            result = cur.fetchone()
            assert result[0] == 1
    finally:
        release_connection(conn)

def test_materials_seeded():
    """Verify that all 3 MVP priority feedstocks are seeded."""
    materials = get_all_materials()
    mat_names = [m["name"].lower() for m in materials]
    assert "sugarcane" in mat_names
    assert "sugarcane bagasse" in mat_names
    assert "banana peel" in mat_names

def test_routes_and_steps_seeded():
    """Verify verified human-reviewed production routes are present."""
    routes = get_routes_for_material("sugarcane")
    assert len(routes) >= 1
    pla_route = routes[0]
    assert "PLA" in pla_route["product_name"] or "Poly(lactic acid)" in pla_route["product_name"]
    assert pla_route["evidence_level"] == "Commercial"
    assert len(pla_route["steps"]) == 3
    assert pla_route["reviewed_by_human"] is True

def test_paper_persistence_and_deduplication():
    """
    Test that saving a paper stores it in Neon, and saving the same
    openalex_id again updates the existing record without creating a duplicate.
    """
    initial_count = get_saved_paper_count()
    test_paper = {
        "openalex_id": "https://openalex.org/W9999999999",
        "doi": "https://doi.org/10.1016/j.test.persist.2024",
        "title": "Innovative Poly(lactic acid) Synthesis from Sugarcane",
        "authors": ["Test Researcher A", "Test Researcher B"],
        "publication_year": 2024,
        "abstract": "A comprehensive study on catalytic PLA polymerization from cane sugar.",
        "landing_page_url": "https://doi.org/10.1016/j.test.persist.2024",
        "open_access_url": "https://example.com/test.pdf",
        "relevance_status": "Highly Relevant",
        "relevance_score": 85,
        "citation_count": 5,
        "metadata_json": {"source": "pytest_test_suite"},
    }

    # First save
    paper_id_1 = save_paper(test_paper, material_name="sugarcane")
    assert paper_id_1 is not None

    count_after_first = get_saved_paper_count()
    # It should have incremented or stayed equal if already existed
    assert count_after_first >= initial_count

    # Second save with exact same openalex_id (simulating re-saving)
    test_paper["title"] = "Innovative Poly(lactic acid) Synthesis from Sugarcane (Updated)"
    paper_id_2 = save_paper(test_paper, material_name="sugarcane")

    count_after_second = get_saved_paper_count()

    # Crucial assertion: no duplicate row was created
    assert paper_id_1 == paper_id_2
    assert count_after_second == count_after_first

    # Verify retrieval
    stored_papers = get_papers_for_material("sugarcane")
    matching = [p for p in stored_papers if p["openalex_id"] == test_paper["openalex_id"]]
    assert len(matching) == 1
    assert matching[0]["title"] == "Innovative Poly(lactic acid) Synthesis from Sugarcane (Updated)"


def test_feedstock_summary_persistence_and_update():
    """Verify Category B literature synthesis persistence, retrieval, and upsert in Neon."""
    test_mat = "potato starch"
    test_summary_1 = "### Initial synthesis for potato starch bioplastics."
    
    # 1. Save synthesis
    sum_id_1 = save_feedstock_summary(
        material_name=test_mat,
        summary_text=test_summary_1,
        paper_ids=[1, 2, 3],
        model_name="gemini-3.1-flash-lite",
    )
    assert sum_id_1 is not None

    # 2. Retrieve synthesis
    fetched = get_feedstock_summary(test_mat)
    assert fetched is not None
    assert fetched["summary_text"] == test_summary_1
    assert fetched["paper_ids"] == [1, 2, 3]
    assert fetched["model_name"] == "gemini-3.1-flash-lite"

    # 3. Update existing synthesis (upsert test - should NOT create duplicate row)
    test_summary_2 = "### Updated synthesis for potato starch bioplastics with new insights."
    sum_id_2 = save_feedstock_summary(
        material_name=test_mat,
        summary_text=test_summary_2,
        paper_ids=[1, 2, 3, 4],
        model_name="gemini-3.1-flash-lite",
    )
    assert sum_id_1 == sum_id_2

    # 4. Re-fetch and verify updated content
    fetched_updated = get_feedstock_summary(test_mat)
    assert fetched_updated["summary_text"] == test_summary_2
    assert fetched_updated["paper_ids"] == [1, 2, 3, 4]


