"""
OpenAlex Service for BioFlex Lab.
Handles querying the OpenAlex API, material normalization, abstract reconstruction,
deduplication, relevance scoring, and structured error handling.
"""

import os
import re
import time
import concurrent.futures
from typing import Any, Dict, List, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
import config

# Persistent HTTP session with connection pooling for low latency
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=1)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

# Base OpenAlex API URL
OPENALEX_WORKS_URL = "https://api.openalex.org/works"

# Default request timeout in seconds
REQUEST_TIMEOUT = 12

# Material synonyms dictionary for normalization
MATERIAL_SYNONYMS = {
    "bagasse": "sugarcane bagasse",
    "cane bagasse": "sugarcane bagasse",
    "sugar cane": "sugarcane",
    "sugarcane juice": "sugarcane",
    "banana": "banana peel",
    "banana skin": "banana peel",
    "banana peels": "banana peel",
    "corn": "corn starch",
    "maize": "corn starch",
    "potato": "potato starch",
    "cassava": "cassava starch",
    "manioc": "cassava starch",
    "rice": "rice husk",
    "rice hulls": "rice husk",
}

# Bioplastic keywords for search and relevance scoring
BIOPLASTIC_KEYWORDS = [
    "bioplastic",
    "biodegradable plastic",
    "poly(lactic acid)",
    "polylactic acid",
    "pla",
    "polyhydroxyalkanoate",
    "pha",
    "biopolymer film",
    "bio-composite",
    "biocomposite",
    "thermoplastic starch",
    "cellulose film",
]

# Obvious non-renewable or inorganic keywords that should fail the relevance gate upfront
INORGANIC_OR_OFF_TOPIC_TERMS = {
    "sand", "silicon", "glass", "gravel", "rock", "stone", "metal", "steel",
    "iron", "copper", "aluminum", "concrete", "cement", "petroleum",
    "gasoline", "diesel", "laptop", "computer", "phone", "tv", "car", "keyboard",
}


def is_plausible_renewable_material(material: str) -> bool:
    """
    Preliminary screening to filter out non-renewable, inorganic, or nonsensical query inputs.
    Returns False if name is too short, too long, contains invalid characters, or is an inorganic term.
    """
    cleaned = re.sub(r"[^\w\s\-_]", "", material).strip().lower()
    if len(cleaned) < 2 or len(cleaned) > 60:
        return False
    if cleaned.isdigit():
        return False
    tokens = [t for t in re.split(r"[\s\-_]+", cleaned) if t]
    if any(t in INORGANIC_OR_OFF_TOPIC_TERMS for t in tokens):
        return False
    return True


def normalize_material_name(material: str) -> str:
    """Normalize user input material names, collapse extra spaces, handle plurals and synonyms."""
    cleaned = re.sub(r"\s+", " ", material).strip().lower()
    if cleaned.endswith("starches"):
        cleaned = cleaned[:-2]  # starch
    elif cleaned.endswith("peels"):
        cleaned = cleaned[:-1]  # peel
    elif cleaned.endswith("husks"):
        cleaned = cleaned[:-1]  # husk
    elif cleaned.endswith("straws"):
        cleaned = cleaned[:-1]  # straw
    return MATERIAL_SYNONYMS.get(cleaned, cleaned)


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:
    """
    Reconstruct a plain text abstract from OpenAlex's abstract_inverted_index.
    Returns None if the inverted index is missing or empty.
    """
    if not inverted_index or not isinstance(inverted_index, dict):
        return None

    # Flatten the inverted index into a list of (position, word) tuples
    word_positions: List[Tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if isinstance(positions, list):
            for pos in positions:
                word_positions.append((pos, word))

    if not word_positions:
        return None

    # Sort tokens in reading order by word index
    word_positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in word_positions)


def extract_authors(work: Dict[str, Any], max_authors: int = 5) -> List[str]:
    """Extract human-readable author names from OpenAlex authorships."""
    authorships = work.get("authorships") or []
    names = []
    for authorship in authorships:
        author_info = authorship.get("author") or {}
        display_name = author_info.get("display_name")
        if display_name:
            names.append(display_name)
    
    if not names:
        return ["Unknown Authors"]
    
    if len(names) > max_authors:
        return names[:max_authors] + ["et al."]
    return names


def calculate_relevance_score(title: str, abstract: Optional[str], material: str) -> Tuple[int, str]:
    """
    Score relevance (0-100) based on presence of material name and bioplastic terminology
    in the title and reconstructed abstract.
    """
    score = 0
    title_lower = (title or "").lower()
    abstract_lower = (abstract or "").lower()
    material_terms = [t for t in re.split(r"\s+", material.lower()) if len(t) > 2]

    # Check for feedstock terms
    material_in_title = any(term in title_lower for term in material_terms)
    material_in_abstract = any(term in abstract_lower for term in material_terms)
    
    if material_in_title:
        score += 35
    elif material_in_abstract:
        score += 20

    # Check for bioplastic terms
    bioplastic_in_title = any(kw in title_lower for kw in BIOPLASTIC_KEYWORDS)
    bioplastic_in_abstract = any(kw in abstract_lower for kw in BIOPLASTIC_KEYWORDS)

    if bioplastic_in_title:
        score += 35
    elif bioplastic_in_abstract:
        score += 25

    # Bonus if both material and bioplastic are present in title
    if material_in_title and bioplastic_in_title:
        score += 15

    score = min(score, 100)

    # Classify status
    if score >= 50:
        status = "Highly Relevant"
    elif score >= 25:
        status = "Relevant"
    else:
        status = "Potentially Relevant"

    return score, status


def is_paper_relevant(paper: Dict[str, Any], material: str) -> bool:
    """
    Check if a paper is relevant to bioplastics from the specified feedstock.
    Rule: Title or abstract must mention both:
    1. The material name or its primary distinguishing token (e.g. 'potato' in 'potato starch')
    2. A bioplastic-related keyword from config.RELEVANCE_BIOPLASTIC_KEYWORDS
    """
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstract") or "").lower()
    combined = f"{title} {abstract}"
    if not combined.strip():
        return False

    normalized_mat = normalize_material_name(material).lower()
    
    # Check if full material name is in text
    has_mat = normalized_mat in combined
    if not has_mat:
        # Check distinguishing tokens (e.g., 'potato' for 'potato starch', 'bagasse', 'orange')
        tokens = [tok for tok in re.split(r"[\s\-_]+", normalized_mat) if len(tok) >= 3]
        if tokens:
            primary_token = tokens[0]
            if re.search(rf"\b{re.escape(primary_token)}", combined):
                has_mat = True

    if not has_mat:
        return False

    has_bioplastic = any(
        re.search(rf"\b{re.escape(kw)}", combined)
        for kw in config.RELEVANCE_BIOPLASTIC_KEYWORDS
    )
    return bool(has_bioplastic)


def parse_openalex_work(work: Dict[str, Any], material: str) -> Optional[Dict[str, Any]]:
    """Transform raw OpenAlex JSON item into a structured paper dictionary."""
    openalex_id = work.get("id")
    title = work.get("title") or work.get("display_name")
    if not title or not openalex_id:
        return None

    # DOI extraction and cleaning
    doi = work.get("doi")
    
    # Abstract
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    
    # Authors
    authors = extract_authors(work)
    
    # Publication Year
    pub_year = work.get("publication_year")
    
    # URLs
    primary_loc = work.get("primary_location") or {}
    landing_page_url = doi or primary_loc.get("landing_page_url") or openalex_id
    
    open_access_info = work.get("open_access") or {}
    is_oa = open_access_info.get("is_oa", False)
    oa_url = open_access_info.get("oa_url") or primary_loc.get("pdf_url")

    # Relevance
    relevance_score, relevance_status = calculate_relevance_score(title, abstract, material)

    return {
        "openalex_id": openalex_id,
        "doi": doi,
        "title": title,
        "authors": authors,
        "publication_year": pub_year,
        "abstract": abstract,
        "has_abstract": bool(abstract and len(abstract.strip()) > 10),
        "landing_page_url": landing_page_url,
        "is_open_access": is_oa,
        "open_access_url": oa_url,
        "relevance_score": relevance_score,
        "relevance_status": relevance_status,
        "citation_count": work.get("cited_by_count", 0),
    }


def search_papers(
    material: str,
    page: int = 1,
    per_page: int = 15,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search OpenAlex for bioplastic research related to the given raw material.
    
    Returns a dictionary:
    {
        "material": str,
        "total_results": int,
        "papers": List[Dict],
        "page": int,
        "error": Optional[str]
    }
    """
    normalized_mat = normalize_material_name(material)
    if not normalized_mat:
        return {
            "material": "",
            "total_results": 0,
            "papers": [],
            "page": page,
            "error": "Please provide a valid material name.",
        }

    # Use OpenAlex polite pool if email is provided or in environment
    contact_email = email or os.getenv("OPENALEX_EMAIL", "student@example.com")
    headers = {
        "User-Agent": f"BioFlexLab/1.0 (mailto:{contact_email})"
    }

    # Construct search query combining material and bioplastics domain
    query_str = f'"{normalized_mat}" (bioplastic OR "biodegradable plastic" OR "poly(lactic acid)" OR PLA OR "biopolymer film" OR "bio-composite")'

    params: Dict[str, Any] = {
        "search": query_str,
        "per_page": per_page,
        "page": page,
        "sort": "relevance_score:desc",
    }

    api_key = os.getenv("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key

    try:
        response = _session.get(
            OPENALEX_WORKS_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        
        if response.status_code == 429:
            return {
                "material": normalized_mat,
                "total_results": 0,
                "papers": [],
                "page": page,
                "error": "OpenAlex rate limit reached. Please wait a few seconds before searching again.",
            }

        if response.status_code == 503:
            return {
                "material": normalized_mat,
                "total_results": 0,
                "papers": [],
                "page": page,
                "error": "OpenAlex public cluster is temporarily under heavy load. The system is using papers stored in your local Neon database.",
            }

        response.raise_for_status()
        data = response.json()
        
        meta = data.get("meta") or {}
        total_count = meta.get("count", 0)
        raw_results = data.get("results") or []

        # Deduplicate and parse
        seen_identifiers = set()
        parsed_papers = []

        for item in raw_results:
            doi = (item.get("doi") or "").strip().lower()
            openalex_id = (item.get("id") or "").strip()

            # Deduplication key
            dedup_key = doi if doi else openalex_id
            if dedup_key in seen_identifiers:
                continue
            seen_identifiers.add(dedup_key)

            parsed = parse_openalex_work(item, normalized_mat)
            if parsed:
                parsed_papers.append(parsed)

        return {
            "material": normalized_mat,
            "total_results": total_count,
            "papers": parsed_papers,
            "page": page,
            "error": None,
        }

    except requests.exceptions.Timeout:
        return {
            "material": normalized_mat,
            "total_results": 0,
            "papers": [],
            "page": page,
            "error": "The request to OpenAlex timed out. Please check your internet connection and try again.",
        }
    except requests.exceptions.RequestException as e:
        return {
            "material": normalized_mat,
            "total_results": 0,
            "papers": [],
            "page": page,
            "error": f"Failed to retrieve papers from OpenAlex: {str(e)}",
        }


def search_papers_multi_query(
    material: str,
    per_query: int = 10,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search OpenAlex using multiple focused query templates for the feedstock,
    merging and deduplicating by DOI / OpenAlex ID, ranking by relevance.
    """
    normalized_mat = normalize_material_name(material)
    if not normalized_mat:
        return {
            "material": "",
            "total_results": 0,
            "papers": [],
            "relevant_papers": [],
            "error": "Please provide a valid material name.",
        }

    contact_email = email or os.getenv("OPENALEX_EMAIL", "student@example.com")
    headers = {"User-Agent": f"BioFlexLab/1.0 (mailto:{contact_email})"}
    api_key = os.getenv("OPENALEX_API_KEY")

    seen_identifiers = set()
    all_parsed_papers = []
    total_count = 0
    errors = []

    def _fetch_template(tmpl: str) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
        query_str = tmpl.format(material=normalized_mat)
        p: Dict[str, Any] = {
            "search": query_str,
            "per_page": per_query,
            "page": 1,
            "sort": "relevance_score:desc",
        }
        if contact_email:
            p["mailto"] = contact_email
        if api_key:
            p["api_key"] = api_key

        try:
            resp = _session.get(
                OPENALEX_WORKS_URL,
                params=p,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 429:
                time.sleep(1.0)
                resp = _session.get(
                    OPENALEX_WORKS_URL,
                    params=p,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
            if resp.status_code == 429:
                return (tmpl, None, "OpenAlex rate limit reached. Please wait a few seconds before searching again.")
            if resp.status_code == 503:
                return (tmpl, None, "OpenAlex public cluster is temporarily under heavy load.")
            resp.raise_for_status()
            return (tmpl, resp.json(), None)
        except requests.exceptions.Timeout:
            return (tmpl, None, "The request to OpenAlex timed out. Please check your internet connection.")
        except requests.exceptions.RequestException as e:
            return (tmpl, None, f"Network error querying OpenAlex: {str(e)}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(config.FEEDSTOCK_QUERY_TEMPLATES))) as executor:
        fetch_results = list(executor.map(_fetch_template, config.FEEDSTOCK_QUERY_TEMPLATES))

    for template, data, err in fetch_results:
        if err:
            errors.append(err)
            continue
        if not data:
            continue
        meta = data.get("meta") or {}
        total_count += meta.get("count", 0)
        raw_results = data.get("results") or []

        for item in raw_results:
            doi = (item.get("doi") or "").strip().lower()
            openalex_id = (item.get("id") or "").strip()
            dedup_key = doi if doi else openalex_id
            if not dedup_key or dedup_key in seen_identifiers:
                continue
            seen_identifiers.add(dedup_key)

            parsed = parse_openalex_work(item, normalized_mat)
            if parsed:
                all_parsed_papers.append(parsed)

    # Sort merged papers: relevance_score DESC, citation_count DESC, publication_year DESC
    all_parsed_papers.sort(
        key=lambda p: (p.get("relevance_score", 0), p.get("citation_count", 0), p.get("publication_year") or 0),
        reverse=True,
    )

    relevant_papers = [p for p in all_parsed_papers if is_paper_relevant(p, normalized_mat)]

    overall_error = None
    if not all_parsed_papers and errors:
        overall_error = errors[0]

    return {
        "material": normalized_mat,
        "total_results": max(total_count, len(all_parsed_papers)),
        "papers": all_parsed_papers,
        "relevant_papers": relevant_papers,
        "error": overall_error,
    }


