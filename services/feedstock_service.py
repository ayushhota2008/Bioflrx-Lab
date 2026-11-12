"""
Feedstock Classification Service for BioFlex Lab.
Classifies any searched feedstock into evidence categories:
- Category A: Verified Production Routes (human_verified)
- Category AI_DRAFT: AI-Drafted Production Route (ai_draft, pending human review)
- Category B: Research-Supported Material (open literature threshold met, cautious summary)
- Category C: Insufficient Research Evidence (relevance gate failed, zero DB records created)
- Error State: External API search failure (distinguished from Category C)
"""

import difflib
from typing import Any, Dict, List, Optional
import config
from services.openalex_service import (
    normalize_material_name,
    search_papers_multi_query,
    is_paper_relevant,
    is_plausible_renewable_material,
)
from services.database_service import (
    get_routes_for_material,
    get_papers_for_material,
    save_papers_batch,
    get_material_by_name,
    get_all_materials,
    get_feedstock_summary,
    save_feedstock_summary,
    save_route_with_steps,
)
from services.gemini_service import (
    generate_category_b_summary,
    draft_structured_production_route,
    check_canonical_material_name,
)


def damerau_levenshtein(s1: str, s2: str) -> int:
    """Compute Damerau-Levenshtein edit distance (accounting for transpositions, insertions, deletions, substitutions)."""
    d = {}
    len1, len2 = len(s1), len(s2)
    for i in range(-1, len1 + 1):
        d[(i, -1)] = i + 1
    for j in range(-1, len2 + 1):
        d[(-1, j)] = j + 1

    for i in range(len1):
        for j in range(len2):
            cost = 0 if s1[i] == s2[j] else 1
            d[(i, j)] = min(
                d[(i - 1, j)] + 1,
                d[(i, j - 1)] + 1,
                d[(i - 1, j - 1)] + cost,
            )
            if i > 0 and j > 0 and s1[i] == s2[j - 1] and s1[i - 1] == s2[j]:
                d[(i, j)] = min(d[(i, j)], d[(i - 2, j - 2)] + cost)

    return d[(len1 - 1, len2 - 1)]


def is_likely_typo(query: str, target: str, min_ratio: float = 0.82) -> bool:
    """
    Verify if query is an actual typo of target, preventing false-positive matches
    between distinct feedstocks that share common suffixes (e.g. 'corn starch' vs 'cane starch').
    """
    q, t = query.strip().lower(), target.strip().lower()
    if q == t:
        return False

    # 1. Overall sequence similarity check
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    if ratio < min_ratio:
        return False

    # 2. Maximum absolute edit distance guard
    max_len = max(len(q), len(t))
    total_dist = damerau_levenshtein(q, t)
    allowed_edits = 1 if max_len <= 5 else (2 if max_len <= 14 else 3)
    if total_dist > allowed_edits:
        return False

    # 3. Word-level token guard for multi-word phrases
    q_words, t_words = q.split(), t.split()
    if len(q_words) == len(t_words) and len(q_words) > 1:
        for qw, tw in zip(q_words, t_words):
            if qw == tw:
                continue
            w_dist = damerau_levenshtein(qw, tw)
            w_ratio = difflib.SequenceMatcher(None, qw, tw).ratio()
            max_w_edits = 1 if max(len(qw), len(tw)) <= 4 else 2
            if w_dist > max_w_edits or w_ratio < 0.70:
                return False

    return True


_cached_feedstock_name_map: Dict[str, str] = {}
_last_feedstock_cache_time: float = 0.0


def _get_feedstock_name_map() -> Dict[str, str]:
    """Retrieve all feedstock names and aliases with a 60s in-memory cache to minimize DB roundtrips."""
    global _cached_feedstock_name_map, _last_feedstock_cache_time
    import time
    now = time.time()
    if not _cached_feedstock_name_map or (now - _last_feedstock_cache_time > 60.0):
        all_mats = get_all_materials()
        name_map: Dict[str, str] = {}
        for m in all_mats:
            c_name = m["name"].strip()
            name_map[c_name.lower()] = c_name
            for al in (m.get("aliases") or []):
                if al:
                    name_map[al.strip().lower()] = c_name
        _cached_feedstock_name_map = name_map
        _last_feedstock_cache_time = now
    return _cached_feedstock_name_map


def check_feedstock_canonical(search_input: str) -> Dict[str, Any]:
    """
    Check a search input against canonical feedstock names and aliases before any search or DB insert.
    1. Normalize (trim, lowercase, collapse spaces, plural handling).
    2. Exact match on normalized name or aliases in Neon DB -> reuse that feedstock.
    3. Fuzzy-match against existing feedstock names and aliases (difflib with SIMILARITY_THRESHOLD and token guard).
    4. Gemini fallback: check if it's a known renewable raw material or a misspelling.
    5. If unrecognized and not a typo -> return action='proceed'.
    """
    clean_raw = (search_input or "").strip()
    if not clean_raw:
        return {"action": "none", "canonical_name": "", "raw_input": ""}

    normalized = normalize_material_name(clean_raw)
    if not normalized:
        return {"action": "none", "canonical_name": "", "raw_input": clean_raw}

    # Step 2: Exact match on normalized name or aliases in DB
    existing_mat = get_material_by_name(normalized)
    if existing_mat:
        canonical_name = existing_mat["name"].strip()
        is_alias_match = (canonical_name.lower() != clean_raw.lower())
        return {
            "action": "exact_match",
            "canonical_name": canonical_name,
            "material_id": existing_mat["id"],
            "is_alias": is_alias_match,
            "raw_input": clean_raw,
            "normalized": normalized,
        }

    # Step 3: Fuzzy-match against existing feedstock names and aliases in DB with typo token guard
    try:
        name_map = _get_feedstock_name_map()
        candidates = list(name_map.keys())
        matches = difflib.get_close_matches(
            normalized,
            candidates,
            n=3,
            cutoff=config.SIMILARITY_THRESHOLD,
        )
        for matched_term in matches:
            canonical = name_map[matched_term]
            if canonical.lower() != normalized and is_likely_typo(normalized, matched_term, min_ratio=config.SIMILARITY_THRESHOLD):
                return {
                    "action": "suggest",
                    "source": "fuzzy_db",
                    "suggested_name": canonical,
                    "raw_input": clean_raw,
                    "normalized": normalized,
                }
    except Exception as db_err:
        print(f"Fuzzy match note: {db_err}")

    # Fast-path: If clearly non-renewable or invalid, skip Gemini spell-check and proceed to relevance gate
    if not is_plausible_renewable_material(normalized):
        return {
            "action": "proceed",
            "canonical_name": normalized,
            "raw_input": clean_raw,
            "normalized": normalized,
        }

    # Step 4: Gemini spell check fallback
    try:
        gemini_res = check_canonical_material_name(normalized)
        if gemini_res.get("corrected") and gemini_res.get("canonical_name"):
            c_name = gemini_res["canonical_name"].strip().lower()
            if c_name != normalized:
                return {
                    "action": "suggest",
                    "source": "gemini",
                    "suggested_name": c_name,
                    "raw_input": clean_raw,
                    "normalized": normalized,
                    "is_renewable": gemini_res.get("is_renewable", True),
                }
    except Exception as gem_err:
        print(f"Gemini canonical check note: {gem_err}")

    # Step 5: Unrecognized / correctly spelled term -> proceed to relevance gate
    return {
        "action": "proceed",
        "canonical_name": normalized,
        "raw_input": clean_raw,
        "normalized": normalized,
    }


def classify_feedstock(
    material: str,
    search_api: bool = True,
    generate_summary: bool = True,
    generate_route: bool = True,
) -> Dict[str, Any]:
    """
    Classify a searched feedstock, enforce relevance gating, auto-draft routes when relevant,
    and assemble all data needed for UI rendering.
    """
    normalized = normalize_material_name(material)
    if not normalized:
        return {
            "material": "",
            "category": "C",
            "route_status": "none",
            "banner_text": "Please enter a valid renewable raw material name to search.",
            "banner_style": "warning",
            "routes": [],
            "papers": [],
            "relevant_papers": [],
            "relevant_count": 0,
            "ai_summary": None,
            "newly_created": False,
            "error": "Empty material name",
        }

    # Canonical alias resolution: if material matches an alias in Neon DB, use canonical name
    existing_mat = get_material_by_name(normalized)
    if existing_mat:
        normalized = existing_mat["name"].lower()

    # Relevance gate pre-check: filter out inorganic, non-renewable, or invalid terms
    if not is_plausible_renewable_material(normalized):
        return {
            "material": normalized,
            "category": "C",
            "route_status": "none",
            "banner_text": (
                f"We did not find sufficiently relevant research for {normalized.title()} in this search. "
                "This does not mean a production method is impossible. "
                "Try a more specific name or a related keyword."
            ),
            "banner_style": "warning",
            "routes": [],
            "papers": [],
            "relevant_papers": [],
            "relevant_count": 0,
            "ai_summary": None,
            "newly_created": False,
            "error": None,
        }

    # 1. Check for existing routes in Neon (Idempotent: reuse existing verified or draft routes)
    routes = get_routes_for_material(normalized)
    verified_routes = [
        r for r in routes
        if r.get("review_status") == "human_verified" or r.get("reviewed_by_human") is True
    ]
    draft_routes = [
        r for r in routes
        if r.get("review_status") == "ai_draft" and not r.get("reviewed_by_human")
    ]

    papers = get_papers_for_material(normalized, limit=20)

    # 1A. Verified Route Exists (Category A)
    if verified_routes:
        if not papers and search_api:
            search_res = search_papers_multi_query(normalized, per_query=10)
            if search_res.get("papers"):
                papers = search_res["papers"]
                try:
                    save_papers_batch(papers, material_name=normalized)
                except Exception:
                    pass

        relevant_papers = [p for p in papers if is_paper_relevant(p, normalized)]
        return {
            "material": normalized,
            "category": "A",
            "route_status": "human_verified",
            "banner_text": "Verified route: reviewed by a human and linked to sources.",
            "banner_style": "success",
            "routes": verified_routes,
            "papers": papers,
            "relevant_papers": relevant_papers,
            "relevant_count": len(relevant_papers),
            "ai_summary": None,
            "newly_created": False,
            "error": None,
        }

    # 1B. AI Draft Route Already Exists in Neon (Idempotent reuse: zero extra Gemini calls)
    if draft_routes:
        relevant_papers = [p for p in papers if is_paper_relevant(p, normalized)]
        return {
            "material": normalized,
            "category": "AI_DRAFT",
            "route_status": "ai_draft",
            "banner_text": (
                f"This route was drafted by AI from the research papers listed below for {normalized.title()}. "
                "It has not been reviewed by a human yet. Check the original sources before relying on it."
            ),
            "banner_style": "warning",
            "routes": draft_routes,
            "papers": papers,
            "relevant_papers": relevant_papers,
            "relevant_count": len(relevant_papers),
            "ai_summary": None,
            "newly_created": False,
            "error": None,
        }

    # 2. No route exists yet -> Query research literature via OpenAlex (or Neon fallback)
    search_error: Optional[str] = None
    if search_api:
        search_res = search_papers_multi_query(normalized, per_query=10)
        search_error = search_res.get("error")
        if search_res.get("papers"):
            papers = search_res["papers"]

    # If OpenAlex returned no papers or failed, check Neon DB
    if not papers:
        db_papers = get_papers_for_material(normalized, limit=20)
        if db_papers:
            papers = db_papers
            search_error = None

    # Handle Search Error (distinguished from Category C)
    if not papers and search_error:
        return {
            "material": normalized,
            "category": "ERROR",
            "route_status": "none",
            "banner_text": f"Search failed: {search_error}",
            "banner_style": "error",
            "routes": [],
            "papers": [],
            "relevant_papers": [],
            "relevant_count": 0,
            "ai_summary": None,
            "newly_created": False,
            "error": search_error,
        }

    # Evaluate relevance gate against bioplastic terms
    relevant_papers = [p for p in papers if is_paper_relevant(p, normalized)]
    relevant_count = len(relevant_papers)

    # 3. Relevance Gate Check: must have >= MIN_RELEVANT_PAPERS
    if relevant_count < config.MIN_RELEVANT_PAPERS:
        # Gate fails: do NOT create feedstock in database
        return {
            "material": normalized,
            "category": "C",
            "route_status": "none",
            "banner_text": (
                f"We did not find sufficiently relevant research for {normalized.title()} in this search. "
                "This does not mean a production method is impossible. "
                "Try a more specific name or a related keyword."
            ),
            "banner_style": "warning",
            "routes": [],
            "papers": papers,
            "relevant_papers": relevant_papers,
            "relevant_count": relevant_count,
            "ai_summary": None,
            "newly_created": False,
            "error": None,
        }

    # 4. Gate passed! Auto-create feedstock record and save papers in Neon
    try:
        save_papers_batch(papers, material_name=normalized)
    except Exception as save_err:
        print(f"Paper persistence note: {save_err}")

    # Reload saved papers to have their integer primary keys
    db_papers = get_papers_for_material(normalized, limit=20)
    if db_papers:
        papers = db_papers
        relevant_papers = [p for p in papers if is_paper_relevant(p, normalized)]

    # 5. Auto-draft production route via Gemini
    if generate_route:
        try:
            draft_data = draft_structured_production_route(normalized, relevant_papers[:5])
            if draft_data:
                save_route_with_steps(
                    material_name=normalized,
                    route_data=draft_data,
                    review_status="ai_draft",
                    generated_by="gemini",
                    model_name=config.GEMINI_MODEL_NAME,
                )
                new_routes = get_routes_for_material(normalized)
                return {
                    "material": normalized,
                    "category": "AI_DRAFT",
                    "route_status": "ai_draft",
                    "banner_text": (
                        f"This route was drafted by AI from the research papers listed below for {normalized.title()}. "
                        "It has not been reviewed by a human yet. Check the original sources before relying on it."
                    ),
                    "banner_style": "warning",
                    "routes": new_routes,
                    "papers": papers,
                    "relevant_papers": relevant_papers,
                    "relevant_count": relevant_count,
                    "ai_summary": None,
                    "newly_created": True,
                    "error": None,
                }
        except Exception as draft_err:
            print(f"Route drafting note: {draft_err}")

    # 6. Fallback: Category B (Literature Synthesis Summary) if route could not be drafted
    ai_summary = None
    if generate_summary:
        cached_synth = get_feedstock_summary(normalized)
        if cached_synth and cached_synth.get("summary_text"):
            ai_summary = cached_synth["summary_text"]
        else:
            ai_summary = generate_category_b_summary(normalized, relevant_papers[:5])
            try:
                paper_ids = [p["id"] for p in relevant_papers[:5] if p.get("id")]
                save_feedstock_summary(
                    material_name=normalized,
                    summary_text=ai_summary,
                    paper_ids=paper_ids,
                    model_name=config.GEMINI_MODEL_NAME,
                )
            except Exception as synth_save_err:
                print(f"Synthesis persistence note: {synth_save_err}")

    return {
        "material": normalized,
        "category": "B",
        "route_status": "none",
        "banner_text": (
            f"{normalized.title()} is a research-supported feedstock. "
            "No human-reviewed production route has been added to our verified pathways database yet. "
            "Explore the available academic research below."
        ),
        "banner_style": "info",
        "routes": [],
        "papers": papers,
        "relevant_papers": relevant_papers,
        "relevant_count": relevant_count,
        "ai_summary": ai_summary,
        "newly_created": True,
        "error": None,
    }
