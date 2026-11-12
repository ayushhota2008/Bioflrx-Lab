"""
Unit and integration tests for Feedstock Classification and 3-Tier Evidence categories.
Verifies Category A, B, and C classification, error handling, and deduplication.
"""

from unittest.mock import patch
import pytest
import requests

import config
from services.openalex_service import is_paper_relevant, normalize_material_name
from services.feedstock_service import classify_feedstock
from services.database_service import get_saved_paper_count, save_papers_batch


def test_classify_category_a_sugarcane():
    """Verify sugarcane classifies as Category A with human-reviewed routes."""
    res = classify_feedstock("sugarcane", search_api=False, generate_summary=False)
    assert res["category"] == "A"
    assert "Verified route" in res["banner_text"]
    assert len(res["routes"]) >= 1
    assert any(r.get("reviewed_by_human") for r in res["routes"])


def test_classify_category_a_banana_peel_synonym():
    """Verify banana peels synonym resolves and classifies as Category A."""
    assert normalize_material_name("banana peels") == "banana peel"
    res = classify_feedstock("banana peels", search_api=False, generate_summary=False)
    assert res["category"] == "A"
    assert res["material"] == "banana peel"
    assert len(res["routes"]) >= 1


def test_classify_category_b_research_supported():
    """Verify materials with >= MIN_RELEVANT_PAPERS and no human routes classify as Category B when route drafting is skipped/fails."""
    mock_papers = [
        {
            "openalex_id": f"W100{i}",
            "title": f"Biodegradable cassava starch bioplastic film study {i}",
            "abstract": "Thermoplastic cassava starch films plasticized with glycerol.",
            "relevance_score": 85,
            "publication_year": 2023,
            "authors": ["Test Author"],
        }
        for i in range(5)
    ]
    with patch("services.feedstock_service.search_papers_multi_query") as mock_search:
        mock_search.return_value = {
            "material": "cassava starch",
            "total_results": 5,
            "papers": mock_papers,
            "relevant_papers": mock_papers,
            "error": None,
        }
        with patch("services.feedstock_service.get_routes_for_material", return_value=[]):
            res = classify_feedstock("cassava starch", search_api=True, generate_summary=False, generate_route=False)
            assert res["category"] == "B"
            assert "research-supported feedstock" in res["banner_text"]
            assert res["relevant_count"] >= config.MIN_RELEVANT_PAPERS


def test_classify_category_c_insufficient_evidence():
    """Verify materials with no routes and 0 relevant papers classify as Category C (not ERROR)."""
    with patch("services.feedstock_service.search_papers_multi_query") as mock_search:
        mock_search.return_value = {
            "material": "xyzfoo",
            "total_results": 0,
            "papers": [],
            "relevant_papers": [],
            "error": None,
        }
        res = classify_feedstock("xyzfoo", search_api=True, generate_summary=False)
        assert res["category"] == "C"
        assert "did not find sufficiently relevant research" in res["banner_text"]
        assert len(res["routes"]) == 0
        assert len(res["papers"]) == 0


def test_classify_error_distinct_from_category_c():
    """Verify API failures (timeout/load) return ERROR, distinct from Category C."""
    with patch("services.feedstock_service.search_papers_multi_query") as mock_search:
        mock_search.return_value = {
            "material": "obscure_plant",
            "total_results": 0,
            "papers": [],
            "relevant_papers": [],
            "error": "The request to OpenAlex timed out.",
        }
        with patch("services.feedstock_service.get_papers_for_material", return_value=[]):
            res = classify_feedstock("obscure_plant", search_api=True, generate_summary=False)
            assert res["category"] == "ERROR"
            assert res["category"] != "C"
            assert "Search failed" in res["banner_text"]


def test_paper_relevance_checker():
    """Verify is_paper_relevant checks for material and bioplastic terms."""
    relevant_paper = {
        "title": "Properties of potato starch bioplastic films",
        "abstract": "Biodegradable thermoplastic film prepared with glycerol.",
    }
    assert is_paper_relevant(relevant_paper, "potato starch") is True

    off_topic_paper = {
        "title": "Agronomic yields of Solanum tuberosum in sandy soil",
        "abstract": "We measured agricultural potato output across several fertilizer treatments.",
    }
    assert is_paper_relevant(off_topic_paper, "potato starch") is False

    nonsense_paper = {
        "title": "Quantum chromodynamics at high temperature",
        "abstract": "Lattice gauge simulations.",
    }
    assert is_paper_relevant(nonsense_paper, "xyzfoo") is False


def test_no_old_misleading_message_in_code():
    """Verify the old misleading seeded-route message was completely eradicated from application files."""
    import pathlib
    project_root = pathlib.Path(__file__).parent.parent
    banned_string = "No verified human-reviewed " + "production routes are currently seeded"
    
    for py_file in project_root.rglob("*.py"):
        if ".venv" in py_file.parts or "tests" in py_file.parts:
            continue
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        assert banned_string not in content, f"Found banned string in {py_file}"
