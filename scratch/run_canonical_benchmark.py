"""
Evaluation script testing all 10 benchmark scenarios for feedstock canonicalization,
typo prevention, alias resolution, relevance gating, and verified route immutability.
"""

import sys
sys.path.insert(0, r"c:\Users\AYUSH\OneDrive\Desktop\CC project BIOFLEX LAB")

import json
from services.feedstock_service import check_feedstock_canonical, classify_feedstock
from services.database_service import (
    get_connection,
    release_connection,
    get_material_by_name,
    add_material_alias,
)


def run_benchmark():
    results = {}

    # Scenario 1: "Potato Strach" after cleanup -> resolves to Potato Starch via alias
    s1 = check_feedstock_canonical("Potato Strach")
    results["1_potato_strach_initial"] = {
        "action": s1["action"],
        "canonical_name": s1.get("canonical_name"),
        "is_alias": s1.get("is_alias"),
        "pass": (s1["action"] == "exact_match" and s1["canonical_name"].lower() == "potato starch" and s1.get("is_alias") is True)
    }

    # Scenario 2: "potato starch" -> exact match immediately
    s2 = check_feedstock_canonical("potato starch")
    results["2_potato_starch_exact"] = {
        "action": s2["action"],
        "canonical_name": s2.get("canonical_name"),
        "is_alias": s2.get("is_alias"),
        "pass": (s2["action"] == "exact_match" and s2["canonical_name"].lower() == "potato starch" and s2.get("is_alias") is False)
    }

    # Scenario 3: "Potato Strach" again -> resolves directly via alias without prompt
    s3 = check_feedstock_canonical("Potato Strach")
    results["3_potato_strach_subsequent"] = {
        "action": s3["action"],
        "canonical_name": s3.get("canonical_name"),
        "is_alias": s3.get("is_alias"),
        "pass": (s3["action"] == "exact_match" and s3["canonical_name"].lower() == "potato starch")
    }

    # Scenario 4: "Rice Hsuk" -> suggests "Rice Husk" (fuzzy match / Gemini)
    s4 = check_feedstock_canonical("Rice Hsuk")
    results["4_rice_hsuk_suggests"] = {
        "action": s4["action"],
        "source": s4.get("source"),
        "suggested_name": s4.get("suggested_name"),
        "pass": (s4["action"] == "suggest" and s4.get("suggested_name", "").lower() == "rice husk")
    }

    # Scenario 5: "sand" -> rejected by relevance gate, zero feedstock rows created
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'sand';")
            had_sand_before = cur.fetchone() is not None
    finally:
        release_connection(conn)

    s5 = classify_feedstock("sand", search_api=True, generate_summary=False, generate_route=False)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'sand';")
            has_sand_after = cur.fetchone() is not None
    finally:
        release_connection(conn)

    results["5_sand_rejected"] = {
        "category": s5["category"],
        "had_before": had_sand_before,
        "has_after": has_sand_after,
        "pass": (s5["category"] == "C" and not has_sand_after)
    }

    # Scenario 6: "xyzfoo" -> nonsense rejected, zero feedstock rows created
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'xyzfoo';")
            had_xyzfoo_before = cur.fetchone() is not None
    finally:
        release_connection(conn)

    s6 = classify_feedstock("xyzfoo", search_api=True, generate_summary=False, generate_route=False)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'xyzfoo';")
            has_xyzfoo_after = cur.fetchone() is not None
    finally:
        release_connection(conn)

    results["6_xyzfoo_rejected"] = {
        "category": s6["category"],
        "had_before": had_xyzfoo_before,
        "has_after": has_xyzfoo_after,
        "pass": (s6["category"] == "C" and not has_xyzfoo_after)
    }

    # Scenario 7: "Wheat Straw" (new, not in DB) -> not suggested as typo, proceeds to route drafting
    s7_check = check_feedstock_canonical("Wheat Straw")
    # Wheat Straw is spelled correctly, so action should be 'proceed'
    results["7_wheat_straw_canonical_check"] = {
        "action": s7_check["action"],
        "normalized": s7_check.get("normalized"),
        "pass": (s7_check["action"] == "proceed")
    }

    # Scenario 8: "sugarcane" -> still shows verified route, untouched
    s8 = classify_feedstock("sugarcane", search_api=False, generate_summary=False, generate_route=False)
    results["8_sugarcane_verified_untouched"] = {
        "category": s8["category"],
        "route_status": s8["route_status"],
        "reviewed_by_human": s8["routes"][0]["reviewed_by_human"] if s8.get("routes") else False,
        "pass": (s8["category"] == "A" and s8["route_status"] == "human_verified" and s8["routes"][0]["reviewed_by_human"] is True)
    }

    # Scenario 9: "banana peel" -> still shows verified route, untouched
    s9 = classify_feedstock("banana peel", search_api=False, generate_summary=False, generate_route=False)
    results["9_banana_peel_verified_untouched"] = {
        "category": s9["category"],
        "route_status": s9["route_status"],
        "reviewed_by_human": s9["routes"][0]["reviewed_by_human"] if s9.get("routes") else False,
        "pass": (s9["category"] == "A" and s9["route_status"] == "human_verified" and s9["routes"][0]["reviewed_by_human"] is True)
    }

    # Scenario 10: "No, search as typed" on a typo or nonsense -> proceeds through relevance gate without creating junk
    # Simulate user clicking "No, search as typed" on a typo like "corn stach"
    # When user overrides suggestion and searches as typed:
    # If it's nonsense, relevance gate rejects it with zero rows created:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'fakejunktypomaterial';")
            before_fake = cur.fetchone() is not None
    finally:
        release_connection(conn)

    s10 = classify_feedstock("fakejunktypomaterial", search_api=True, generate_summary=False, generate_route=False)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM raw_materials WHERE LOWER(name) = 'fakejunktypomaterial';")
            after_fake = cur.fetchone() is not None
    finally:
        release_connection(conn)

    results["10_search_as_typed_nonsense_zero_junk"] = {
        "category": s10["category"],
        "created_row": after_fake,
        "pass": (s10["category"] == "C" and not after_fake)
    }

    print(json.dumps(results, indent=2))
    all_passed = all(v["pass"] for v in results.values())
    print(f"\nALL 10 BENCHMARK TESTS PASSED: {all_passed}")

if __name__ == "__main__":
    run_benchmark()

