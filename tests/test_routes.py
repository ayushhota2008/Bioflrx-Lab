"""
Unit and integration tests for Production Route Pages (Phase 5).
Verifies that routes, chemical steps, inputs, conditions, evidence levels,
and metadata are populated and never merged across feedstocks.
"""

import pytest
from services.database_service import get_routes_for_material, get_material_by_name

VALID_EVIDENCE_LEVELS = [
    "Commercial",
    "Pilot / Scale-Up",
    "Laboratory Demonstration",
    "Emerging / Exploratory",
]

def test_priority_materials_have_routes():
    """Verify that all 3 MVP priority feedstocks have verified production routes."""
    priority_feedstocks = ["sugarcane", "sugarcane bagasse", "banana peel"]
    for mat in priority_feedstocks:
        routes = get_routes_for_material(mat)
        assert len(routes) >= 1, f"Expected at least 1 route for {mat}"
        route = routes[0]
        assert route["reviewed_by_human"] is True
        assert route["evidence_level"] in VALID_EVIDENCE_LEVELS

def test_sugarcane_pla_route_details():
    """Verify sugarcane route specifically describes industrial PLA production."""
    routes = get_routes_for_material("sugarcane")
    route = routes[0]
    assert "PLA" in route["product_name"] or "Poly(lactic acid)" in route["product_name"]
    assert route["evidence_level"] == "Commercial"
    assert "fermentation" in route["route_type"].lower()
    assert len(route["applications"]) > 20
    assert len(route["advantages"]) > 20
    assert len(route["limitations"]) > 20
    assert len(route["environmental_notes"]) > 20

    # Verify steps
    steps = route["steps"]
    assert len(steps) == 3
    assert steps[0]["step_number"] == 1
    assert "Extraction" in steps[0]["title"] or "Juice" in steps[0]["title"]
    assert "Fermentation" in steps[1]["title"]
    assert "Polymerization" in steps[2]["title"] or "Lactide" in steps[2]["title"]
    assert steps[1]["conditions"] is not None

def test_bagasse_cellulose_route_details():
    """Verify bagasse route specifically describes cellulose nanocomposite films."""
    routes = get_routes_for_material("sugarcane bagasse")
    route = routes[0]
    assert "Cellulose" in route["product_name"]
    assert route["evidence_level"] == "Pilot / Scale-Up"
    assert "delignification" in route["route_summary"].lower()

    steps = route["steps"]
    assert len(steps) >= 3
    assert any("Delignification" in s["title"] for s in steps)
    assert any("Nanofibrillation" in s["title"] or "Bleaching" in s["title"] for s in steps)

def test_banana_peel_starch_route_details():
    """Verify banana peel route specifically describes starch extraction and plasticization."""
    routes = get_routes_for_material("banana peel")
    route = routes[0]
    assert "Starch" in route["product_name"]
    assert route["evidence_level"] == "Laboratory Demonstration"
    assert "glycerol" in route["route_summary"].lower() or "gelatinization" in route["route_summary"].lower()

    steps = route["steps"]
    assert len(steps) >= 3
    assert any("Starch" in s["title"] or "Milling" in s["title"] for s in steps)
    assert any("Gelatinization" in s["title"] or "Casting" in s["title"] for s in steps)

def test_feedstock_routes_remain_distinct():
    """Verify that distinct feedstocks do not share or merge route records."""
    sugarcane_routes = get_routes_for_material("sugarcane")
    bagasse_routes = get_routes_for_material("sugarcane bagasse")
    
    s_ids = {r["id"] for r in sugarcane_routes}
    b_ids = {r["id"] for r in bagasse_routes}
    assert s_ids.isdisjoint(b_ids), "Sugarcane and bagasse routes must be completely distinct records!"

