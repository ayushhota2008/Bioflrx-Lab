"""
Context Builder for BioFlex Lab AI Assistant.
Selects saved papers and verified production routes from Neon PostgreSQL
and formats them into structured, numbered evidence blocks for Gemini.
"""

from typing import Any, Dict, List, Optional, Union
from services.database_service import get_papers_for_material, get_routes_for_material


def format_paper_block(index: int, paper: Dict[str, Any], max_abstract_len: int = 700) -> str:
    """Format a single paper record into an evidence block with DOI and abstract."""
    title = paper.get("title", "Untitled")
    authors = paper.get("authors") or []
    author_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
    year = paper.get("publication_year") or "N/A"
    doi = paper.get("doi") or paper.get("landing_page_url") or "No DOI"
    abstract = (paper.get("abstract") or "No abstract available in open repository.").strip()

    if len(abstract) > max_abstract_len:
        abstract = abstract[:max_abstract_len] + "... [trimmed]"

    return (
        f"[Paper {index}]\n"
        f"Title: {title}\n"
        f"Authors: {author_str}\n"
        f"Year: {year}\n"
        f"DOI: {doi}\n"
        f"Relevance: {paper.get('relevance_status', 'Relevant')} (Score: {paper.get('relevance_score', 0)})\n"
        f"Abstract/Summary: {abstract}\n"
    )


def format_route_block(route: Dict[str, Any]) -> str:
    """Format a human-reviewed production route and its ordered process steps."""
    product = route.get("product_name", "Biopolymer")
    evidence = route.get("evidence_level", "Laboratory Demonstration")
    summary = route.get("route_summary", "")
    limitations = route.get("limitations", "None documented")
    steps = route.get("steps") or []

    steps_text = []
    for step in steps:
        s_num = step.get("step_number", 1)
        s_title = step.get("title", "")
        s_desc = step.get("description", "")
        s_inputs = step.get("required_inputs", "Standard laboratory inputs")
        s_cond = step.get("conditions", "Standard atmospheric conditions")
        steps_text.append(
            f"   Step {s_num}: {s_title}\n"
            f"   - Description: {s_desc}\n"
            f"   - Required Inputs: {s_inputs}\n"
            f"   - Process Conditions: {s_cond}"
        )

    joined_steps = "\n".join(steps_text) if steps_text else "   (No individual process steps documented yet)"

    return (
        f"[Verified Production Route: {product}]\n"
        f"Evidence Level: {evidence}\n"
        f"Route Summary: {summary}\n"
        f"Known Limitations: {limitations}\n"
        f"Chemical Process Steps:\n{joined_steps}\n"
    )


def build_material_context(
    material_name: Union[str, List[str]],
    max_papers: int = 8,
) -> Dict[str, Any]:
    """
    Fetch relevant saved papers and verified production routes for the feedstock(s) from Neon.
    Returns:
    {
        "material": str,
        "context_text": str,
        "papers": List[Dict],
        "routes": List[Dict],
        "has_content": bool,
    }
    """
    if isinstance(material_name, str):
        target_materials = [material_name.strip()] if material_name.strip() else []
    else:
        target_materials = [m.strip() for m in material_name if m and m.strip()]

    all_papers: List[Dict[str, Any]] = []
    all_routes: List[Dict[str, Any]] = []

    per_mat_papers = max(2, max_papers // len(target_materials)) if len(target_materials) > 1 else max_papers

    for mat in target_materials:
        raw_papers = get_papers_for_material(mat, limit=per_mat_papers)
        routes = get_routes_for_material(mat)
        all_papers.extend(raw_papers)
        all_routes.extend(routes)

    paper_blocks = []
    for idx, paper in enumerate(all_papers, start=1):
        paper["citation_id"] = f"[Paper {idx}]"
        paper_blocks.append(format_paper_block(idx, paper))

    route_blocks = [format_route_block(r) for r in all_routes]

    sections = []
    if route_blocks:
        sections.append("=== VERIFIED HUMAN-REVIEWED PRODUCTION ROUTES ===\n" + "\n".join(route_blocks))
    if paper_blocks:
        sections.append("=== RETRIEVED SCIENTIFIC LITERATURE ===\n" + "\n".join(paper_blocks))

    if not sections:
        context_text = ""
        has_content = False
    else:
        context_text = "\n\n".join(sections)
        has_content = True

    canonical_name = ", ".join(target_materials) if target_materials else "feedstock"

    return {
        "material": canonical_name,
        "context_text": context_text,
        "papers": all_papers,
        "routes": all_routes,
        "has_content": has_content,
    }

