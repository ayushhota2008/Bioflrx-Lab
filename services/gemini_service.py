"""
Gemini Service for BioFlex Lab AI Assistant.
Integrates with Google GenAI SDK (google-genai), formats context with system prompt,
enforces citation grounding, and validates citations with multi-model fallback.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
import config
from services.context_builder import build_material_context
from services.citation_validator import validate_citations
from services.openalex_service import normalize_material_name
from services.database_service import get_all_materials


_cached_gemini_client: Optional[genai.Client] = None


def get_gemini_client() -> Optional[genai.Client]:
    """Initialize and return a cached Google GenAI Client if API key is present."""
    global _cached_gemini_client
    if _cached_gemini_client is not None:
        return _cached_gemini_client

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            pass

    if not api_key or api_key.strip() == "your_gemini_api_key_here":
        return None
    _cached_gemini_client = genai.Client(api_key=api_key.strip())
    return _cached_gemini_client


def identify_target_materials(question: str, default_material: Optional[str] = None) -> List[str]:
    """
    Identify whether the question refers to database-seeded materials or another feedstock.
    If the question refers to database materials, returns their canonical names.
    If the question is about an unknown/non-database material, returns an empty list.
    If the question is a follow-up with no material name, returns [default_material] if valid in database.
    """
    q_lower = question.lower()

    # Immediately filter obvious off-topic queries so no database context is attached
    off_topic_indicators = ["poem", "joke", "story", "song", "football", "soccer", "cricket", "weather", "who won", "who is", "capital of", "president of", "movie", "game"]
    if any(term in q_lower for term in off_topic_indicators):
        return []

    # Dynamic lookup against all materials and aliases in Neon DB
    matched_db: List[str] = []
    masked_q = q_lower
    try:
        all_mats = get_all_materials()
        # Sort by length descending so multi-word (e.g. 'sugarcane bagasse') matches before 'sugarcane'
        sorted_mats = sorted(all_mats, key=lambda m: len(m.get("name", "")), reverse=True)
        for m in sorted_mats:
            c_name = m.get("name", "").strip().lower()
            if not c_name:
                continue
            if c_name in masked_q:
                matched_db.append(c_name)
                masked_q = masked_q.replace(c_name, " " * len(c_name))
                continue
            for al in (m.get("aliases") or []):
                al_clean = al.strip().lower() if al else ""
                if al_clean and al_clean in masked_q:
                    matched_db.append(c_name)
                    masked_q = masked_q.replace(al_clean, " " * len(al_clean))
                    break
    except Exception:
        # Fallback to priority materials if database is unreachable
        for pm in sorted(config.PRIORITY_MATERIALS, key=len, reverse=True):
            if pm in masked_q:
                matched_db.append(pm)
                masked_q = masked_q.replace(pm, " " * len(pm))

    if matched_db:
        return list(dict.fromkeys(matched_db))

    # If no specific material name was mentioned, use default_material if provided and registered
    if default_material:
        d_lower = default_material.strip().lower()
        if d_lower:
            return [d_lower]

    return []


def detect_material_override(question: str, current_material: str) -> str:
    """Backward-compatible helper for single material detection."""
    mats = identify_target_materials(question, current_material)
    if mats:
        return mats[0]
    return current_material


def build_grounded_user_prompt(
    question: str,
    context: Dict[str, Any],
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Build user prompt with conditional research context injection."""
    recent_history_text = ""
    if chat_history and len(chat_history) > 1:
        history_lines = []
        for msg in chat_history[-4:-1]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")
            if len(content) > 300:
                content = content[:300] + "..."
            history_lines.append(f"{role}: {content}")
        recent_history_text = "\nRecent Conversation History:\n" + "\n".join(history_lines) + "\n\n"

    has_research_context = context.get("has_content", False) and bool(context.get("papers") or context.get("routes"))

    if has_research_context:
        return (
            f"--- RELEVANT RESEARCH EVIDENCE FROM DATABASE ---\n"
            f"{context['context_text']}\n"
            f"--- END EVIDENCE CONTEXT ---\n\n"
            f"{recent_history_text}"
            f"User Question: {question}\n\n"
            f"Instructions for this response:\n"
            f"1. Rely primarily on the provided verified routes and research papers above.\n"
            f"2. Cite supporting sources using exact labels like [Paper 1], [Paper 2], or their DOI.\n"
            f"3. Explicitly label the maturity of each route mentioned (established industrial process, pilot/scale-up, laboratory experiment, proposed method, or theoretical possibility).\n"
            f"4. Clearly explain intermediate conversion steps (e.g. extraction, fermentation, chemical modification) and whether the material is only suitable as a composite filler.\n"
            f"5. Do NOT invent DOIs, authors, or experimental yields not documented above."
        )

    return (
        f"{recent_history_text}"
        f"User Question: {question}\n\n"
        f"Instructions for this response:\n"
        f"1. No specific research papers or database routes are available for this inquiry.\n"
        f"2. Answer thoroughly using your general scientific knowledge of bioplastics, polymer chemistry, and renewable materials.\n"
        f"3. You MUST include this exact short line in your response:\n"
        f"\"This explanation is based on general scientific knowledge and has not been checked against specific research papers.\"\n"
        f"4. Explicitly label the maturity of each production route discussed as one of:\n"
        f"   - established industrial process\n"
        f"   - pilot/scale-up\n"
        f"   - laboratory experiment\n"
        f"   - proposed method\n"
        f"   - theoretical possibility\n"
        f"5. Never claim every renewable material can directly yield a biodegradable plastic. Explain required intermediate steps (e.g. extraction of starch/cellulose, fermentation to lactic acid/PHA, chemical modification) or if it only functions as a filler/reinforcement.\n"
        f"6. If a material is a poor candidate or invalid (e.g. low polysaccharide content, contamination, or inorganic/non-renewable materials like sand), state that honestly.\n"
        f"7. Never invent papers, authors, DOIs, citations, or specific numerical yields/temperatures.\n"
        f"8. If the user question is completely off-topic (unrelated to bioplastics, polymers, or renewable materials), provide a brief, polite redirect back to bioplastics and renewable materials."
    )


def generate_stream_chunks(
    question: str,
    context: Dict[str, Any],
    chat_history: Optional[List[Dict[str, str]]] = None,
):
    """
    Yields text tokens in real time from Gemini for Streamlit's st.write_stream.
    Handles fallback models and unconfigured keys seamlessly.
    """
    client = get_gemini_client()
    resolved_material = context.get("material", "renewable material")
    if not client:
        fallback_msg = (
            f"*(Demo / Educational Mode)* You asked about **{resolved_material.title()}**: \"{question}\".\n\n"
            "To connect live to Google Gemini, please configure your `GEMINI_API_KEY` in your `.env` file.\n\n"
            f"**Context Retrieved from Database:**\n"
            f"- Found **{len(context['papers'])}** saved research papers.\n"
            f"- Found **{len(context['routes'])}** verified production routes.\n\n"
            "Once `GEMINI_API_KEY` is provided, live generative responses with grounded citations will activate."
        )
        yield fallback_msg
        return

    user_prompt = build_grounded_user_prompt(question, context, chat_history)

    candidate_models = [
        config.GEMINI_MODEL_NAME,
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
        "gemini-3.8-flash",
    ]
    models_to_try = list(dict.fromkeys(candidate_models))

    streamed_any = False
    last_err = None

    for model_name in models_to_try:
        try:
            stream = client.models.generate_content_stream(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=config.AI_ASSISTANT_SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=1000,
                ),
            )
            for chunk in stream:
                if chunk.text:
                    streamed_any = True
                    yield chunk.text
            if streamed_any:
                return
        except Exception as e:
            last_err = e
            if streamed_any:
                break
            continue

    if not streamed_any:
        yield f"Failed to generate response from Gemini API: {str(last_err)}"


def query_ai_assistant(
    question: str,
    material_name: Optional[str] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
    max_context_papers: int = 5,
) -> Dict[str, Any]:
    """
    Query the AI research assistant on any renewable raw material question.
    Loads papers and routes from Neon if relevant, constructs grounded prompt, calls Gemini,
    and runs programmatic citation validation with automatic model fallbacks.
    """
    target_mats = identify_target_materials(question, material_name)
    context = build_material_context(
        material_name=target_mats,
        max_papers=max_context_papers,
    )

    client = get_gemini_client()

    # If API key is not configured, return educational fallback
    if not client:
        fallback_msg = (
            f"*(Demo / Educational Mode)* You asked: \"{question}\".\n\n"
            "To connect live to Google Gemini, please configure your `GEMINI_API_KEY` in your `.env` file.\n\n"
            f"**Context Retrieved from Database:**\n"
            f"- Found **{len(context['papers'])}** saved research papers.\n"
            f"- Found **{len(context['routes'])}** verified production routes.\n\n"
            "Once `GEMINI_API_KEY` is provided, live generative responses will activate."
        )
        validation = validate_citations(fallback_msg, context["papers"])
        return {
            "answer": fallback_msg,
            "sources_used": validation["verified_sources"],
            "invalid_citations": validation["invalid_citations"],
            "context_used": context,
            "error": "GEMINI_API_KEY_NOT_CONFIGURED",
        }

    user_prompt = build_grounded_user_prompt(question, context, chat_history)

    # Candidate models in order of resilience
    candidate_models = [
        config.GEMINI_MODEL_NAME,
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
        "gemini-3.8-flash",
    ]
    # Deduplicate while preserving priority order
    models_to_try = list(dict.fromkeys(candidate_models))

    last_error = None
    raw_answer = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=config.AI_ASSISTANT_SYSTEM_PROMPT,
                    temperature=0.2,  # Low temperature for factual grounding
                    max_output_tokens=1000,
                ),
            )

            # Safely extract text
            if response and hasattr(response, "text") and response.text:
                raw_answer = response.text
                break
            elif response and response.candidates and response.candidates[0].content:
                parts = response.candidates[0].content.parts
                raw_answer = "".join(p.text for p in parts if hasattr(p, "text") and p.text)
                if raw_answer:
                    break
        except Exception as e:
            last_error = e
            continue

    if not raw_answer:
        error_msg = f"Failed to generate response from Gemini API: {str(last_error)}"
        return {
            "answer": error_msg,
            "sources_used": [],
            "invalid_citations": [],
            "context_used": context,
            "error": str(last_error),
        }

    # Post-generation programmatic citation validation
    validation = validate_citations(raw_answer, context["papers"])

    return {
        "answer": validation["cleaned_text"],
        "sources_used": validation["verified_sources"],
        "invalid_citations": validation["invalid_citations"],
        "context_used": context,
        "error": None,
    }


def generate_category_b_summary(material: str, papers: List[Dict[str, Any]]) -> str:
    """
    Generate an evidence synthesis summary for Category B (Research-Supported) feedstocks.
    Strictly constrained to the provided paper titles and reconstructed abstracts.
    Cites only provided papers, separates lab vs commercial, highlights limitations,
    and never invents numbers or citations.
    """
    if not papers:
        return (
            f"No research papers were provided to generate a synthesis for **{material.title()}**.\n\n"
            f"> ⚠️ **Note:** {config.AI_SUMMARY_DISCLAIMER_NOTE}"
        )

    # Format paper excerpts for Gemini prompt
    paper_excerpts = []
    for idx, p in enumerate(papers[:5], start=1):
        title = p.get("title") or "Untitled"
        authors = ", ".join(p.get("authors", [])) if isinstance(p.get("authors"), list) else str(p.get("authors", "Unknown"))
        year = p.get("publication_year") or "N/A"
        abstract = p.get("abstract") or "Abstract not available; metadata only."
        doi = p.get("doi") or p.get("landing_page_url") or "No DOI"
        paper_excerpts.append(
            f"[Paper {idx}]: \"{title}\" ({year})\n"
            f"Authors: {authors}\n"
            f"DOI: {doi}\n"
            f"Abstract excerpt: {abstract}\n"
        )

    papers_text = "\n".join(paper_excerpts)

    prompt = f"""You are a scientific research assistant synthesizing peer-reviewed literature for a first-year university engineering student.
Synthesize the research approaches reported in the papers below for converting {material.title()} into biodegradable materials or bioplastics.

PAPERS PROVIDED:
{papers_text}

STRICT REQUIREMENTS:
1. Grounding: Use ONLY the provided paper titles and reconstructed abstracts above.
2. Citations: Cite ONLY the papers provided using their exact labels: [Paper 1], [Paper 2], etc.
3. Abstract Transparency: Explicitly state when claims or parameters come from abstracts only.
4. Scale & Maturity: Clearly separate laboratory/bench-scale research demonstrations from pilot or established industrial processes.
5. Conversion Approaches: Describe the documented processing steps (e.g. starch/cellulose extraction, plasticization, solvent casting, blending).
6. Limitations: Mention key technical limitations (e.g., moisture sensitivity, retrogradation, mechanical weakness, plasticizer migration, processing energy).
7. Honesty: NEVER invent numbers, experimental yields, temperatures, or unprovided citations. If a number or specific procedure is not mentioned in the text, do not invent it.
8. Structure:
   - ### 🔬 Research Overview & Conversion Pathways
   - ### ⚙️ Experimental & Laboratory Approaches Reported
   - ### ⚠️ Technical Limitations & Challenges
   - ### 📚 Cited Sources

At the very end of your response, you MUST include this exact disclaimer on its own line:
> ⚠️ **Note:** {config.AI_SUMMARY_DISCLAIMER_NOTE}
"""

    client = get_gemini_client()
    if not client:
        # Fallback if no API key is available
        lines = [
            f"### 🔬 Research Overview for {material.title()}",
            f"Academic literature indicates that **{material.title()}** is being actively investigated for bioplastic and biopolymer applications across {len(papers)} retrieved papers.",
            "",
            "### ⚙️ Reported Approaches (From Indexed Metadata):",
        ]
        for idx, p in enumerate(papers[:5], start=1):
            lines.append(f"- **[Paper {idx}]**: *{p.get('title')}* ({p.get('publication_year') or 'N/A'})")
        lines.extend([
            "",
            "### ⚠️ Technical Limitations & Challenges:",
            "- Processing challenges commonly include moisture sensitivity and mechanical durability compared to petrochemical plastics.",
            "",
            f"> ⚠️ **Note:** {config.AI_SUMMARY_DISCLAIMER_NOTE}",
        ])
        return "\n".join(lines)

    candidate_models = [
        config.GEMINI_MODEL_NAME,
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
        "gemini-3.8-flash",
    ]
    models_to_try = list(dict.fromkeys(candidate_models))

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=config.AI_ASSISTANT_SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=1000,
                ),
            )
            if response and hasattr(response, "text") and response.text:
                summary_text = response.text
                if config.AI_SUMMARY_DISCLAIMER_NOTE not in summary_text:
                    summary_text += f"\n\n> ⚠️ **Note:** {config.AI_SUMMARY_DISCLAIMER_NOTE}"
                return summary_text
        except Exception:
            continue

    # Fallback if all Gemini attempts fail
    return (
        f"### 🔬 Research Overview for {material.title()}\n\n"
        f"Retrieved {len(papers)} peer-reviewed papers investigating bioplastic applications for **{material.title()}**.\n\n"
        + "\n".join(f"- **[Paper {i}]**: *{p.get('title')}* ({p.get('publication_year') or 'N/A'})" for i, p in enumerate(papers[:5], start=1))
        + f"\n\n> ⚠️ **Note:** {config.AI_SUMMARY_DISCLAIMER_NOTE}"
    )


def draft_structured_production_route(
    material: str,
    papers: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Draft a structured production route from retrieved research paper titles and abstracts.
    Outputs strict JSON matching the production route schema.
    Validates JSON and ensures every cited supporting_paper_id is actually in the provided set.
    """
    if not papers:
        return None

    client = get_gemini_client()
    if not client:
        return None

    # Format papers list for prompt
    paper_entries = []
    valid_paper_ids = set()
    for idx, p in enumerate(papers[:5], start=1):
        p_id = p.get("id") or idx
        if p.get("id"):
            valid_paper_ids.add(p["id"])
        title = p.get("title") or "Untitled"
        year = p.get("publication_year") or "N/A"
        abstract = p.get("abstract") or "Abstract not available; metadata only."
        paper_entries.append(
            f"Paper ID: {p_id}\n"
            f"Title: \"{title}\" ({year})\n"
            f"Abstract: {abstract}\n"
        )

    papers_text = "\n".join(paper_entries)

    system_instruction = (
        "You are an expert chemical engineer and scientific research assistant specializing in bioplastics. "
        "Your task is to draft a structured chemical/physical production route from renewable feedstocks "
        "strictly based on provided peer-reviewed literature. You must respond ONLY with valid JSON."
    )

    prompt = f"""Draft a structured production route for converting {material.title()} into a biodegradable plastic or biopolymer material, strictly grounded in the research papers below.

RESEARCH PAPERS:
{papers_text}

INSTRUCTIONS:
1. Grounding: Rely ONLY on the titles and abstracts provided above.
2. If details (such as exact temperatures, pressures, or reagents) are not mentioned in the abstracts, write "not reported". DO NOT invent numbers or parameters.
3. Every step in "steps" must reference a valid "supporting_paper_id" integer chosen from the Paper IDs provided above. If no specific paper describes that step, set "supporting_paper_id" to null.
4. "evidence_level" must be one of:
   - "Commercial" (if established industrial process)
   - "Pilot / Scale-Up" (if pilot plant / semi-industrial)
   - "Laboratory Demonstration" (if bench scale / lab experiment)
   - "Emerging / Exploratory" (if preliminary / theoretical)

OUTPUT JSON FORMAT:
{{
  "product_name": "string (e.g. Thermoplastic Starch Bio-Film)",
  "route_summary": "concise summary of the conversion pathway",
  "route_type": "string (e.g. Thermoplastic Processing & Film Casting)",
  "evidence_level": "Laboratory Demonstration",
  "applications": "documented applications or 'not reported'",
  "advantages": "documented advantages or 'not reported'",
  "limitations": "documented technical limitations or 'not reported'",
  "environmental_notes": "biodegradation/environmental notes or 'not reported'",
  "steps": [
    {{
      "step_number": 1,
      "title": "step title",
      "description": "chemical and physical description of what happens",
      "required_inputs": "required reagents or 'not reported'",
      "conditions": "reaction/processing conditions or 'not reported'",
      "supporting_paper_id": <integer Paper ID or null>
    }}
  ]
}}
"""

    candidate_models = [
        config.GEMINI_MODEL_NAME,
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
    ]
    models_to_try = list(dict.fromkeys(candidate_models))

    for attempt in range(2):
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.1,
                        response_mime_type="application/json",
                        max_output_tokens=1500,
                    ),
                )
                text = response.text if response and hasattr(response, "text") else ""
                if not text and response and response.candidates:
                    text = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, "text"))

                if not text:
                    continue

                # Clean potential markdown fences
                cleaned_text = re.sub(r"^```(?:json)?\s*", "", text.strip())
                cleaned_text = re.sub(r"\s*```$", "", cleaned_text).strip()

                data = json.loads(cleaned_text)

                # Schema verification
                required_fields = ["product_name", "route_summary", "route_type", "evidence_level", "steps"]
                if not all(k in data for k in required_fields):
                    continue

                if not isinstance(data.get("steps"), list) or not data["steps"]:
                    continue

                # Evidence level normalization
                valid_levels = ["Commercial", "Pilot / Scale-Up", "Laboratory Demonstration", "Emerging / Exploratory"]
                if data["evidence_level"] not in valid_levels:
                    data["evidence_level"] = "Laboratory Demonstration"

                # Step cleaning and supporting_paper_id validation
                cleaned_steps = []
                for s in data["steps"]:
                    if not isinstance(s, dict):
                        continue
                    s_num = int(s.get("step_number") or len(cleaned_steps) + 1)
                    s_title = str(s.get("title") or f"Step {s_num}")
                    s_desc = str(s.get("description") or "")
                    if not s_desc:
                        continue

                    # Validate supporting_paper_id: must exist in provided valid IDs
                    paper_id = s.get("supporting_paper_id")
                    if paper_id and paper_id not in valid_paper_ids:
                        paper_id = None

                    cleaned_steps.append({
                        "step_number": s_num,
                        "title": s_title,
                        "description": s_desc,
                        "required_inputs": s.get("required_inputs") or "not reported",
                        "conditions": s.get("conditions") or "not reported",
                        "supporting_paper_id": paper_id,
                    })

                if not cleaned_steps:
                    continue

                data["steps"] = cleaned_steps
                return data

            except Exception:
                continue

    return None


_canonical_check_cache: Dict[str, Dict[str, Any]] = {}


def check_canonical_material_name(raw_name: str) -> Dict[str, Any]:
    """
    Check if a raw search query is a known renewable raw material or a misspelling/typo of one.
    Returns:
    {
        "raw_name": str,
        "canonical_name": str,
        "is_renewable": bool,
        "corrected": bool,
        "confidence": str
    }
    """
    clean_input = raw_name.strip()
    if not clean_input:
        return {
            "raw_name": "",
            "canonical_name": "",
            "is_renewable": False,
            "corrected": False,
            "confidence": "high",
        }

    cache_key = clean_input.lower()
    if cache_key in _canonical_check_cache:
        cached = _canonical_check_cache[cache_key]
        return {
            "raw_name": clean_input,
            "canonical_name": cached["canonical_name"],
            "is_renewable": cached["is_renewable"],
            "corrected": cached["corrected"],
            "confidence": cached["confidence"],
        }

    client = get_gemini_client()
    if not client:
        res = {
            "raw_name": clean_input,
            "canonical_name": clean_input.lower(),
            "is_renewable": True,
            "corrected": False,
            "confidence": "low",
        }
        _canonical_check_cache[cache_key] = res
        return res

    prompt = f"""Analyze this feedstock/material search query: "{clean_input}".
Determine:
1. Is it a recognizable renewable raw material (or agricultural biomass/residue/waste) that could potentially be researched for bioplastics or biopolymers?
2. Is the query a typo/misspelling or slight grammatical error of a standard renewable raw material?
If it is a typo or misspelling, provide the corrected standard English lowercase canonical name.
If it is NOT a typo (spelled correctly or completely unrecognizable/nonsense), keep canonical_name as the normalized input.

Respond ONLY with valid JSON in this exact structure:
{{
  "canonical_name": "standard lowercase canonical name",
  "is_renewable": true,
  "corrected": false,
  "confidence": "high"
}}
"""

    candidate_models = [
        config.GEMINI_MODEL_NAME,
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
    ]
    models_to_try = list(dict.fromkeys(candidate_models))

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            raw_text = (response.text or "").strip()
            data = json.loads(raw_text)
            c_name = str(data.get("canonical_name") or clean_input.lower()).strip().lower()
            is_renew = bool(data.get("is_renewable", True))
            corrected = bool(data.get("corrected", False))

            if c_name == clean_input.lower():
                corrected = False

            result = {
                "raw_name": clean_input,
                "canonical_name": c_name,
                "is_renewable": is_renew,
                "corrected": corrected,
                "confidence": str(data.get("confidence") or "high"),
            }
            _canonical_check_cache[cache_key] = result
            return result
        except Exception:
            continue

    fallback = {
        "raw_name": clean_input,
        "canonical_name": clean_input.lower(),
        "is_renewable": True,
        "corrected": False,
        "confidence": "low",
    }
    _canonical_check_cache[cache_key] = fallback
    return fallback


