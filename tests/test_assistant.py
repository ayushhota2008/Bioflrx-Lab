"""
Unit and integration tests for AI Assistant & Citation Validator (Phase 4).
"""

import pytest
from services.context_builder import build_material_context, format_paper_block, format_route_block
from services.citation_validator import extract_citations, validate_citations
from services.gemini_service import query_ai_assistant, identify_target_materials


def test_format_paper_block():
    """Verify paper block formatting contains essential fields."""
    mock_paper = {
        "title": "Synthesis of PLA from Sugar",
        "authors": ["Dr. Smith", "Dr. Patel"],
        "publication_year": 2023,
        "doi": "https://doi.org/10.1016/j.test.2023",
        "relevance_status": "Highly Relevant",
        "relevance_score": 90,
        "abstract": "We report ring-opening polymerization of lactide into high-molecular-weight PLA.",
    }
    block = format_paper_block(1, mock_paper)
    assert "[Paper 1]" in block
    assert "Synthesis of PLA from Sugar" in block
    assert "Dr. Smith, Dr. Patel" in block
    assert "https://doi.org/10.1016/j.test.2023" in block


def test_format_route_block():
    """Verify route block formatting renders steps and conditions."""
    mock_route = {
        "product_name": "PLA Thermoplastic",
        "evidence_level": "Commercial",
        "route_summary": "Fermentation followed by polymerization.",
        "limitations": "Composting required.",
        "steps": [
            {
                "step_number": 1,
                "title": "Fermentation",
                "description": "Lactobacillus fermentation of sucrose.",
                "required_inputs": "Sucrose, yeast extract",
                "conditions": "40°C, pH 6.0",
            }
        ],
    }
    block = format_route_block(mock_route)
    assert "[Verified Production Route: PLA Thermoplastic]" in block
    assert "Evidence Level: Commercial" in block
    assert "Step 1: Fermentation" in block
    assert "40°C, pH 6.0" in block


def test_build_material_context():
    """Verify context building retrieves seeded routes and papers for sugarcane."""
    ctx = build_material_context("sugarcane", max_papers=5)
    assert ctx["material"] == "sugarcane"
    assert ctx["has_content"] is True
    assert "=== VERIFIED HUMAN-REVIEWED PRODUCTION ROUTES ===" in ctx["context_text"]
    assert len(ctx["routes"]) >= 1


def test_extract_citations():
    """Verify regex extraction of bracketed paper indices and DOIs."""
    sample_text = (
        "According to [Paper 1] and [Paper 2], lactic acid is produced via fermentation. "
        "Further work at 10.1016/j.biomac.2021.05.012 confirms tensile strength."
    )
    indices, dois = extract_citations(sample_text)
    assert 1 in indices
    assert 2 in indices
    assert any("10.1016/j.biomac.2021.05.012" in d for d in dois)


def test_citation_validator_valid_and_invalid():
    """Verify that only context-provided papers are verified and fake ones are caught."""
    provided_papers = [
        {
            "id": 101,
            "title": "Real Sugarcane Research",
            "authors": ["Author A"],
            "publication_year": 2022,
            "doi": "https://doi.org/10.1016/j.real.2022",
        },
        {
            "id": 102,
            "title": "Bagasse Cellulose Film",
            "authors": ["Author B"],
            "publication_year": 2023,
            "doi": "https://doi.org/10.1016/j.real.2023",
        },
    ]

    response_with_hallucination = (
        "As established in [Paper 1], sucrose ferments readily into lactic acid. "
        "However, [Paper 99] claims banana peel produces superior yield without catalysts."
    )

    validation = validate_citations(response_with_hallucination, provided_papers)
    
    # Paper 1 is valid
    assert len(validation["verified_sources"]) == 1
    assert validation["verified_sources"][0]["title"] == "Real Sugarcane Research"

    # Paper 99 is caught and flagged as invalid
    assert any("[Paper 99]" in inv for inv in validation["invalid_citations"])
    assert "*(unverified citation)*" in validation["cleaned_text"]


def test_citation_validator_honest_lack_of_info():
    """Verify answers admitting lack of evidence are marked grounded."""
    honest_answer = (
        "I don't have enough information from the retrieved research to answer the specific "
        "thermal degradation kinetics of this composite."
    )
    validation = validate_citations(honest_answer, [])
    assert validation["is_grounded"] is True


def test_query_ai_assistant_graceful_fallback():
    """Verify AI assistant responds gracefully even when API key is unconfigured."""
    res = query_ai_assistant(
        question="What is the yield of PLA from sugarcane?",
        material_name="sugarcane",
    )
    assert res is not None
    assert "answer" in res
    assert res["context_used"]["has_content"] is True


def test_identify_target_materials_dynamic_db_lookup():
    """Verify that identify_target_materials dynamically detects feedstocks from Neon DB."""
    # Seeded material: sugarcane bagasse (precedence over sugarcane)
    mats_bagasse = identify_target_materials("What are the limitations of sugarcane bagasse?")
    assert mats_bagasse == ["sugarcane bagasse"]

    # Newly registered database material: potato starch
    mats_potato = identify_target_materials("How can potato starch be used to make bioplastics?")
    assert "potato starch" in mats_potato

    # Unregistered/inorganic query: returns empty list so general knowledge is used
    mats_sand = identify_target_materials("Can sand be used to make biopolymers?")
    assert mats_sand == []

    # Off-topic indicator: returns empty list
    mats_joke = identify_target_materials("Tell me a funny joke about football")
    assert mats_joke == []

    # Follow-up question with default material
    mats_followup = identify_target_materials("What is the tensile strength?", default_material="banana peel")
    assert mats_followup == ["banana peel"]


