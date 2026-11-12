"""
Citation Validator for BioFlex Lab.
Parses LLM responses for cited paper IDs and DOIs, cross-checks them against
the provided context set, and filters/flags any hallucinated citations.
"""

import re
from typing import Any, Dict, List, Set, Tuple


def extract_citations(text: str) -> Tuple[Set[int], Set[str]]:
    """
    Extract cited paper numbers (e.g. [Paper 1], [1]) and DOIs from text.
    Returns:
        (set_of_paper_indices, set_of_dois)
    """
    # Match patterns like [Paper 1], [Paper 2], (Paper 1), etc.
    paper_pattern = re.compile(r"\[Paper\s+(\d+)\]|\(Paper\s+(\d+)\)", re.IGNORECASE)
    paper_matches = paper_pattern.findall(text)
    cited_indices = set()
    for m in paper_matches:
        idx_str = m[0] or m[1]
        if idx_str:
            cited_indices.add(int(idx_str))

    # Match numeric bracketed citations like [1], [2] when labeled
    num_pattern = re.compile(r"\[(\d+)\]")
    num_matches = num_pattern.findall(text)
    for num_str in num_matches:
        cited_indices.add(int(num_str))

    # Match DOI patterns (e.g. 10.1016/j.indcrop.2020.112345 or https://doi.org/10.xxxx/yyyy)
    doi_pattern = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
    doi_matches = set(doi_pattern.findall(text))

    return cited_indices, doi_matches


def validate_citations(
    response_text: str,
    provided_papers: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Validate all citations in the response text against provided context papers.
    Ensures that only papers actually passed to the model appear in the verified sources list.
    """
    cited_indices, cited_dois = extract_citations(response_text)
    
    # Map provided papers by 1-based index and normalized DOI
    provided_by_index: Dict[int, Dict[str, Any]] = {}
    provided_by_doi: Dict[str, Dict[str, Any]] = {}

    for idx, p in enumerate(provided_papers, start=1):
        provided_by_index[idx] = p
        p_doi = p.get("doi") or ""
        # Clean doi to 10.xxxx/... format for matching
        clean_doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", p_doi)
        if clean_doi_match:
            provided_by_doi[clean_doi_match.group(0).lower()] = p

    verified_sources: List[Dict[str, Any]] = []
    seen_paper_ids: Set[Any] = set()
    invalid_citations: List[str] = []

    # 1. Check cited indices ([Paper 1], [1], etc.)
    for idx in sorted(cited_indices):
        if idx in provided_by_index:
            p = provided_by_index[idx]
            if p.get("id") not in seen_paper_ids:
                seen_paper_ids.add(p.get("id"))
                authors = p.get("authors") or []
                author_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
                verified_sources.append({
                    "citation_label": f"[Paper {idx}]",
                    "title": p.get("title", "Untitled"),
                    "authors": author_str,
                    "year": p.get("publication_year") or "N/A",
                    "doi": p.get("doi"),
                    "url": p.get("doi") or p.get("landing_page_url") or p.get("openalex_id"),
                })
        else:
            # Out of bounds index
            invalid_citations.append(f"[Paper {idx}] (not in retrieved set)")

    # 2. Check explicitly cited DOIs
    for raw_doi in cited_dois:
        clean_doi = raw_doi.lower().rstrip(".,;)")
        if clean_doi in provided_by_doi:
            p = provided_by_doi[clean_doi]
            if p.get("id") not in seen_paper_ids:
                seen_paper_ids.add(p.get("id"))
                authors = p.get("authors") or []
                author_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
                verified_sources.append({
                    "citation_label": f"DOI: {clean_doi}",
                    "title": p.get("title", "Untitled"),
                    "authors": author_str,
                    "year": p.get("publication_year") or "N/A",
                    "doi": p.get("doi"),
                    "url": p.get("doi") or p.get("landing_page_url") or p.get("openalex_id"),
                })
        else:
            invalid_citations.append(f"DOI: {raw_doi} (unverified)")

    # 3. Clean or flag invalid citations in text
    cleaned_text = response_text
    for inv in invalid_citations:
        # If model hallucinated a citation out of thin air, flag it
        label = inv.split()[0]
        cleaned_text = cleaned_text.replace(label, f"{label} *(unverified citation)*")

    # If the response explicitly notes that information is not available, or notes general scientific knowledge
    admits_lack_of_info = any(phrase in response_text.lower() for phrase in [
        "not enough information",
        "don't have enough information",
        "no research papers",
        "insufficient evidence",
        "not found in the retrieved",
        "general scientific knowledge",
    ])

    return {
        "cleaned_text": cleaned_text,
        "verified_sources": verified_sources,
        "invalid_citations": invalid_citations,
        "is_grounded": bool(verified_sources) or admits_lack_of_info,
    }

