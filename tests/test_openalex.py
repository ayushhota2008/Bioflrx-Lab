"""
Unit and integration tests for OpenAlex service (Phase 2).
"""

import pytest
from services.openalex_service import (
    normalize_material_name,
    reconstruct_abstract,
    extract_authors,
    calculate_relevance_score,
    parse_openalex_work,
    search_papers,
)

def test_normalize_material_name():
    """Verify material synonyms resolve to canonical forms."""
    assert normalize_material_name("bagasse") == "sugarcane bagasse"
    assert normalize_material_name("  Banana  ") == "banana peel"
    assert normalize_material_name("cane bagasse") == "sugarcane bagasse"
    assert normalize_material_name("corn") == "corn starch"
    assert normalize_material_name("sugarcane") == "sugarcane"

def test_reconstruct_abstract_valid():
    """Verify inverted index reconstruction sorts words by position."""
    inverted_index = {
        "Bioplastic": [0],
        "films": [1],
        "from": [2],
        "banana": [3],
        "peel": [4],
        "exhibit": [5],
        "good": [6],
        "tensile": [7],
        "strength.": [8],
    }
    expected = "Bioplastic films from banana peel exhibit good tensile strength."
    assert reconstruct_abstract(inverted_index) == expected

def test_reconstruct_abstract_empty_or_none():
    """Verify missing or invalid inverted index returns None."""
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None
    assert reconstruct_abstract("not a dict") is None

def test_extract_authors():
    """Verify author display names extraction and truncation."""
    mock_work = {
        "authorships": [
            {"author": {"display_name": "Alice Smith"}},
            {"author": {"display_name": "Bob Jones"}},
            {"author": {"display_name": "Charlie Brown"}},
            {"author": {"display_name": "Diana Prince"}},
            {"author": {"display_name": "Evan Wright"}},
            {"author": {"display_name": "Frank White"}},
        ]
    }
    authors = extract_authors(mock_work, max_authors=3)
    assert len(authors) == 4
    assert authors[-1] == "et al."
    assert authors[0] == "Alice Smith"

def test_calculate_relevance_score():
    """Verify score is higher when material and bioplastic terms are present."""
    high_score, status_high = calculate_relevance_score(
        title="Fabrication of sugarcane bagasse bioplastic films",
        abstract="This work studies poly(lactic acid) reinforcement using cellulose fibers.",
        material="sugarcane bagasse",
    )
    assert high_score >= 70
    assert status_high == "Highly Relevant"

    low_score, status_low = calculate_relevance_score(
        title="Economic trends in agriculture",
        abstract="A survey of global crop yields.",
        material="banana peel",
    )
    assert low_score < 25
    assert status_low == "Potentially Relevant"

def test_parse_openalex_work():
    """Verify complete parsing of OpenAlex work item."""
    mock_work = {
        "id": "https://openalex.org/W123456789",
        "doi": "https://doi.org/10.1016/j.test.2024.001",
        "title": "Biodegradable sugarcane bioplastic composite",
        "publication_year": 2024,
        "authorships": [{"author": {"display_name": "Dr. Green"}}],
        "abstract_inverted_index": {"Study": [0], "of": [1], "PLA.": [2]},
        "open_access": {"is_oa": True, "oa_url": "https://example.com/paper.pdf"},
        "primary_location": {"landing_page_url": "https://doi.org/10.1016/j.test.2024.001"},
        "cited_by_count": 12,
    }
    parsed = parse_openalex_work(mock_work, "sugarcane")
    assert parsed is not None
    assert parsed["title"] == "Biodegradable sugarcane bioplastic composite"
    assert parsed["abstract"] == "Study of PLA."
    assert parsed["has_abstract"] is True
    assert parsed["is_open_access"] is True
    assert parsed["doi"] == "https://doi.org/10.1016/j.test.2024.001"
    assert parsed["relevance_score"] > 50

def test_search_papers_live():
    """Live integration test: search 'sugarcane' and verify real OpenAlex or fallback results."""
    results = search_papers("sugarcane", page=1, per_page=3)
    assert results["material"] == "sugarcane"
    if results["error"] is not None:
        assert "heavy load" in results["error"] or "rate limit" in results["error"]
    else:
        assert results["total_results"] > 0
        assert len(results["papers"]) > 0
        first_paper = results["papers"][0]
        assert first_paper["title"] is not None
        assert first_paper["openalex_id"].startswith("https://openalex.org/W")

def test_search_empty_material():
    """Verify empty query handling."""
    results = search_papers("")
    assert results["error"] is not None
    assert results["papers"] == []

