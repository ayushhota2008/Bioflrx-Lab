"""
AI Assistant - BioFlex Lab
Chat with an AI research assistant powered by Google Gemini, grounded in retrieved scientific literature.
"""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
import config
from services.gemini_service import (
    query_ai_assistant,
    generate_stream_chunks,
    identify_target_materials,
)
from services.context_builder import build_material_context
from services.citation_validator import validate_citations
from services.database_service import get_all_materials, get_papers_for_material, get_routes_for_material
from services.openalex_service import search_papers
from services.database_service import save_papers_batch

st.set_page_config(
    page_title=f"AI Assistant - {config.APP_TITLE}",
    page_icon="🤖",
    layout="wide",
)

# Cache material context queries for 5 minutes to avoid redundant database roundtrips
@st.cache_data(ttl=300, show_spinner=False)
def get_cached_context(materials_tuple: tuple, max_papers: int):
    return build_material_context(list(materials_tuple), max_papers=max_papers)


# Cache feedstocks list for 60 seconds
@st.cache_data(ttl=60, show_spinner=False)
def get_cached_materials():
    return [m["name"] for m in get_all_materials()]

st.title("🤖 AI Research Assistant")
st.caption("Ask technical questions on bioplastic synthesis, processes, and yields from any renewable raw material.")

# Sidebar: Controls & Database Context Overview
with st.sidebar:
    st.subheader("⚙️ Context Settings")
    st.caption("💡 The chatbot answers questions about ANY renewable raw material. The selector below sets which database seed literature to display.")

    # Available materials
    try:
        db_mats = get_cached_materials()
    except Exception:
        db_mats = config.PRIORITY_MATERIALS

    selected_material = st.selectbox(
        "Active Feedstock Context:",
        options=db_mats,
        index=0 if "sugarcane" in db_mats else 0,
        format_func=lambda x: x.title(),
        key="selected_feedstock",
    )

    # Show count of papers and routes in DB for this material
    saved_papers = get_papers_for_material(selected_material)
    routes = get_routes_for_material(selected_material)

    st.write(f"**Saved Research Papers:** {len(saved_papers)}")
    st.write(f"**Verified Production Routes:** {len(routes)}")

    # Convenience button if papers are low
    if len(saved_papers) < 3:
        if st.button(f"📥 Fetch & Save {selected_material.title()} Papers"):
            with st.spinner(f"Fetching papers from OpenAlex for {selected_material}..."):
                res = search_papers(selected_material, per_page=10)
                if res.get("papers"):
                    save_papers_batch(res["papers"], selected_material)
                    st.success(f"Saved {len(res['papers'])} papers to Neon!")
                    st.rerun()
                elif res.get("error"):
                    st.warning(res["error"])

    st.divider()
    if st.button("🗑️ Reset Chat History", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

st.warning(config.AI_DISCLAIMER)

# Initialize conversation memory in session state
if "messages" not in st.session_state or not st.session_state.messages:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Hello! I am your bioplastics research assistant. "
                "I can analyze and answer technical questions about **any renewable raw material** "
                "(sugarcane, bagasse, banana peel, rice husk, potato starch, seaweed, algae, bamboo, and more).\n\n"
                "What would you like to explore? (e.g. *How can potato starch be used to make bioplastic?* or *What are the limitations of rice husk?*)"
            ),
            "sources": [],
        }
    ]

# Display conversation messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        
        # Display sources if present on assistant messages
        sources = msg.get("sources") or []
        if sources:
            with st.expander(f"📚 Verified Sources Used ({len(sources)})"):
                for src in sources:
                    label = src.get("citation_label", "")
                    title = src.get("title", "Untitled")
                    authors = src.get("authors", "")
                    year = src.get("year", "N/A")
                    url = src.get("url")
                    
                    st.markdown(f"**{label}: {title}** ({year})")
                    st.caption(f"Authors: {authors}")
                    if url:
                        st.markdown(f"🔗 [View Source / DOI]({url})")
                    st.divider()

# User prompt input
if prompt := st.chat_input("Ask a question about any renewable raw material or bioplastic conversion..."):
    # Append user question
    st.session_state.messages.append({"role": "user", "content": prompt, "sources": []})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate assistant response with real-time streaming
    with st.chat_message("assistant"):
        target_mats = identify_target_materials(prompt, selected_material)
        context = get_cached_context(tuple(target_mats), config.MAX_CONTEXT_PAPERS)

        if target_mats:
            st.caption(f"📚 *Referencing database evidence for: **{', '.join(m.title() for m in target_mats)}***")

        # Stream tokens live to screen
        raw_stream = generate_stream_chunks(
            question=prompt,
            context=context,
            chat_history=st.session_state.messages,
        )
        answer_text = st.write_stream(raw_stream)

        # Validate citations after stream completes
        validation = validate_citations(answer_text, context["papers"])
        verified_sources = validation["verified_sources"]
        invalid_citations = validation["invalid_citations"]

        # Flag invalid citations if any were caught
        if invalid_citations:
            st.caption(f"🛡️ *Citation Validator caught unverified references: {', '.join(invalid_citations)}*")

        # Render verified sources
        if verified_sources:
            with st.expander(f"📚 Verified Sources Used ({len(verified_sources)})"):
                for src in verified_sources:
                    label = src.get("citation_label", "")
                    title = src.get("title", "Untitled")
                    authors = src.get("authors", "")
                    year = src.get("year", "N/A")
                    url = src.get("url")
                    
                    st.markdown(f"**{label}: {title}** ({year})")
                    st.caption(f"Authors: {authors}")
                    if url:
                        st.markdown(f"🔗 [View Source / DOI]({url})")
                    st.divider()

    # Append assistant response to chat history
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer_text,
        "sources": verified_sources,
    })
