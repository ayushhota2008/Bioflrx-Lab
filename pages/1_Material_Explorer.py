"""
Material Explorer - BioFlex Lab
Search any renewable feedstock across 3 evidence categories:
- Category A: Verified Human-Reviewed Production Routes
- Category B: Research-Supported Material (AI synthesized from peer-reviewed literature)
- Category C: Insufficient Research Evidence (transparent guidance, no invented pathways)
"""

import streamlit as st
import config
from services.openalex_service import normalize_material_name
from services.database_service import (
    get_saved_paper_count,
    get_all_materials,
    get_material_by_name,
    add_material_alias,
)
from services.feedstock_service import (
    classify_feedstock,
    check_feedstock_canonical,
)

st.set_page_config(
    page_title=f"Material Explorer - {config.APP_TITLE}",
    page_icon="🔍",
    layout="wide",
)

# Cache feedstock classification for 10 minutes (invalidated when reviews are approved/rejected)
@st.cache_data(ttl=600, show_spinner=False)
def cached_classify_feedstock(material: str):
    return classify_feedstock(material)


# Cache sidebar overview statistics for 60 seconds
@st.cache_data(ttl=60, show_spinner=False)
def cached_sidebar_stats():
    return get_saved_paper_count(), get_all_materials()


st.title("🔍 Material Explorer & Production Routes")
st.caption("Investigate renewable feedstocks, validated chemical conversion routes, and peer-reviewed literature.")

# Sidebar status
with st.sidebar:
    st.subheader("🐘 Neon Database Overview")
    try:
        total_saved, mats = cached_sidebar_stats()
        st.metric("Total Saved Papers", f"{total_saved:,}")
        st.write(f"**Registered Feedstocks ({len(mats)}):**")
        for m in mats:
            st.markdown(f"- {m['name'].title()}")
    except Exception as e:
        st.caption(f"DB Status: Connecting... ({e})")

st.divider()

# Maintain search state in st.session_state
if "search_query" not in st.session_state:
    st.session_state.search_query = "sugarcane"
if "current_page" not in st.session_state:
    st.session_state.current_page = 1

# Search Bar layout
search_col, button_col = st.columns([4, 1])
with search_col:
    user_input = st.text_input(
        "Search raw material / feedstock:",
        value=st.session_state.search_query,
        placeholder="e.g. sugarcane, banana peel, potato starch, corn starch, rice husk, seaweed, orange peel...",
    )
with button_col:
    st.write("")  # visual spacing alignment
    if st.button("Search Feedstock", type="primary", use_container_width=True):
        st.session_state.search_query = user_input
        st.session_state.search_as_typed_query = None
        st.session_state.current_page = 1

# Quick selector for MVP priority materials
st.write("**Priority Feedstocks (Verified Routes):**")
btn_cols = st.columns(len(config.PRIORITY_MATERIALS))
for idx, mat in enumerate(config.PRIORITY_MATERIALS):
    if btn_cols[idx].button(mat.title(), key=f"quick_{mat}", use_container_width=True):
        st.session_state.search_query = mat
        st.session_state.search_as_typed_query = None
        st.session_state.current_page = 1
        st.rerun()

st.divider()

# Execute search if query is non-empty
active_query = st.session_state.search_query.strip()
if not active_query:
    st.info("💡 Enter a raw material name above or click one of the priority feedstocks to explore research.")
else:
    # Check if user explicitly clicked "No, search as typed" for this exact search query
    search_as_typed = (st.session_state.get("search_as_typed_query") == active_query.lower())

    # Check canonical name / typos before querying external APIs or inserting database records
    canonical_check = (
        {"action": "proceed", "canonical_name": active_query}
        if search_as_typed
        else check_feedstock_canonical(active_query)
    )

    if canonical_check.get("action") == "suggest":
        suggested = canonical_check["suggested_name"]
        suggested_title = suggested.title()

        st.warning(f"🤔 Did you mean **{suggested_title}**?")
        st.write(
            f"We found existing research and records for **{suggested_title}**, which closely matches *\"{active_query}\"*."
        )

        col_yes, col_no = st.columns([1, 1])
        with col_yes:
            if st.button(f"👉 Yes, use {suggested_title}", type="primary", use_container_width=True):
                add_material_alias(suggested, active_query)
                st.session_state.search_query = suggested
                st.session_state.search_as_typed_query = None
                st.session_state.current_page = 1
                st.rerun()
        with col_no:
            if st.button(f"🔍 No, search for '{active_query}' as typed", use_container_width=True):
                st.session_state.search_as_typed_query = active_query.lower()
                st.session_state.current_page = 1
                st.rerun()

        st.stop()

    # Determine canonical material name to display and analyze
    target_material = canonical_check.get("canonical_name") or active_query
    normalized = normalize_material_name(target_material)

    if canonical_check.get("is_alias") or (normalized != active_query.lower() and not search_as_typed):
        st.caption(f"ℹ️ Alias/Synonym resolved: Inspecting **{normalized.title()}**")

    # Fetch feedstock metadata from database
    mat_meta = get_material_by_name(normalized)

    # Feedstock Summary Card
    with st.container(border=True):
        f_col1, f_col2 = st.columns([3, 2])
        with f_col1:
            st.markdown(f"## 🌿 {normalized.title()}")
            if mat_meta and mat_meta.get("description"):
                st.write(mat_meta["description"])
            else:
                st.write("Renewable bio-based raw material under scientific investigation.")
        with f_col2:
            if mat_meta and mat_meta.get("key_components"):
                st.info(f"**🧪 Typical Composition:**\n\n{mat_meta['key_components']}")

    # Classify feedstock across the 3 evidence categories
    with st.spinner(f"Analyzing feedstock evidence and literature for '{normalized.title()}'..."):
        classification = cached_classify_feedstock(normalized)

    cat = classification["category"]
    banner_text = classification["banner_text"]
    routes = classification.get("routes", [])
    papers = classification.get("papers", [])
    relevant_papers = classification.get("relevant_papers", [])
    ai_summary = classification.get("ai_summary")
    error = classification.get("error")
    newly_created = classification.get("newly_created", False)

    # Note for dynamically created feedstocks
    if newly_created:
        st.info(f"🌿 **{normalized.title()}** was automatically added to BioFlex Lab from this search.")

    # Evidence Status Banner (Accessible, distinctive styles per category)
    if cat == "A":
        st.success(f"✅ **Category A: Verified Route Available**\n\n{banner_text}")
    elif cat == "AI_DRAFT":
        st.warning(f"🤖 **AI-Drafted Route (Pending Human Review)**\n\n{banner_text}")
    elif cat == "B":
        st.info(f"🔬 **Category B: Research-Supported Feedstock**\n\n{banner_text}")
    elif cat == "C":
        st.warning(f"ℹ️ **Category C: Insufficient Research Evidence**\n\n{banner_text}")
    elif cat == "ERROR":
        st.error(f"⚠️ **Search Service Unavailable (Not Category C)**\n\n{banner_text}")

    # Tabs: Production Routes/Synthesis vs Research Papers
    tab_routes_label = (
        f"🏭 Production Pathways ({len(routes)})"
        if routes
        else ("🔬 Research Pathways & Synthesis" if cat == "B" else "🏭 Production Pathways")
    )
    tab_papers_label = f"📄 Published Research Papers ({len(papers)})"

    tab_routes, tab_papers = st.tabs([tab_routes_label, tab_papers_label])

    # ---------------- TAB 1: PRODUCTION ROUTES / RESEARCH SYNTHESIS ----------------
    with tab_routes:
        if routes:
            for route in routes:
                with st.container(border=True):
                    is_draft = (route.get("review_status") == "ai_draft" or not route.get("reviewed_by_human"))

                    # Route Header
                    p_name = route.get("product_name", "Biopolymer")
                    ev_level = route.get("evidence_level", "Laboratory Demonstration")
                    r_type = route.get("route_type", "Chemical Conversion")

                    h_col1, h_col2 = st.columns([3, 1])
                    with h_col1:
                        st.markdown(f"### 🔬 Pathway to {p_name}")
                        st.caption(f"**Route Type:** {r_type}")
                    with h_col2:
                        # Review status & Evidence level badge
                        if not is_draft:
                            st.success("🟢 **Verified Route** (Human Reviewed)")
                        else:
                            st.warning("🟠 **AI Draft** (Pending Human Review)")
                            st.caption("Not reviewed by a human")

                        if ev_level == "Commercial":
                            st.caption("🟢 **Scale:** Commercial")
                        elif ev_level == "Pilot / Scale-Up":
                            st.caption("🔵 **Scale:** Pilot / Scale-Up")
                        elif ev_level == "Laboratory Demonstration":
                            st.caption("🟠 **Scale:** Laboratory Demonstration")
                        else:
                            st.caption("🟣 **Scale:** Emerging / Exploratory")

                    # Route Summary
                    st.write(f"**Summary:** {route.get('route_summary', '')}")

                    # Step-by-Step Chemical Pathway
                    st.markdown("#### ⚙️ Step-by-Step Chemical & Physical Conversion:")
                    steps = route.get("steps") or []
                    if not steps:
                        st.caption("No individual steps documented for this route.")
                    else:
                        for s in steps:
                            step_num = s.get("step_number", 1)
                            step_title = s.get("title", f"Step {step_num}")
                            with st.expander(f"**Step {step_num}: {step_title}**", expanded=(step_num == 1)):
                                st.write(s.get("description", ""))
                                
                                sc1, sc2 = st.columns(2)
                                with sc1:
                                    st.markdown(f"**🧪 Required Inputs & Reagents:**\n\n`{s.get('required_inputs') or 'not reported'}`")
                                with sc2:
                                    st.markdown(f"**🌡️ Reaction Conditions:**\n\n`{s.get('conditions') or 'not reported'}`")
                                
                                if s.get("paper_doi"):
                                    st.markdown(f"🔗 [Supporting Literature DOI]({s['paper_doi']}) — *{s.get('paper_title', '')}*")
                                elif s.get("paper_title"):
                                    st.markdown(f"📄 Supporting Literature: *{s.get('paper_title')}*")

                    # Applications & Advantages
                    st.divider()
                    a_col1, a_col2 = st.columns(2)
                    with a_col1:
                        st.markdown("##### 📦 Commercial Applications")
                        st.write(route.get("applications") or "not reported")
                    with a_col2:
                        st.markdown("##### ✨ Key Technical Advantages")
                        st.write(route.get("advantages") or "not reported")

                    # Limitations & Environmental Notes
                    l_col1, l_col2 = st.columns(2)
                    with l_col1:
                        st.markdown("##### ⚠️ Technical Limitations & Challenges")
                        st.write(route.get("limitations") or "not reported")
                    with l_col2:
                        st.markdown("##### 🌿 Environmental & Societal Impact")
                        st.write(route.get("environmental_notes") or "not reported")

                    # Quick link to AI Assistant
                    st.page_link(
                        "pages/2_AI_Assistant.py",
                        label=f"💬 Ask AI Assistant about this {p_name} pathway →",
                        icon="🤖",
                    )

        elif cat == "B":
            st.markdown(f"### 🔬 Research-Supported Synthesis for {normalized.title()}")
            st.caption(
                f"Synthesized from {len(relevant_papers)} peer-reviewed open literature works. "
                "No human-reviewed route has been entered into the database yet."
            )
            if ai_summary:
                st.markdown(ai_summary)
            else:
                st.info("No synthesis summary available.")

            st.divider()
            st.page_link(
                "pages/2_AI_Assistant.py",
                label=f"💬 Ask AI Assistant about {normalized.title()} research →",
                icon="🤖",
            )

        elif cat == "C":
            st.warning(
                f"**No verified pathways or established research routes found for {normalized.title()}.**\n\n"
                "This search did not return sufficiently relevant academic papers linking this feedstock directly to bioplastic production.\n\n"
                "**What this means:**\n"
                "- This does NOT prove that a production method is impossible.\n"
                "- Research into this material may be nascent, published under different terminology, or the material may only serve as a low-concentration filler.\n\n"
                "**Suggestions:**\n"
                "- Try searching for broader chemical classes (e.g., *starch*, *cellulose*, *lignin*, *biomass*).\n"
                "- Check spelling or search for alternative plant parts.\n"
                "- Consult the AI Assistant for general theoretical possibilities regarding this material."
            )
            st.page_link(
                "pages/2_AI_Assistant.py",
                label=f"💬 Ask AI Assistant about {normalized.title()} →",
                icon="🤖",
            )

        elif cat == "ERROR":
            st.error(
                f"**Search service unavailable.**\n\n"
                f"An error occurred while contacting the literature search service: `{error}`.\n\n"
                "This is a service disruption, not proof that the material has insufficient research. Please retry in a few moments."
            )

    # ---------------- TAB 2: RESEARCH PAPERS (OPENALEX) ----------------
    with tab_papers:
        if not papers:
            if cat == "ERROR":
                st.error(f"Search failed: {error}")
            else:
                st.warning(
                    f"No research papers found for '{normalized}'.\n\n"
                    "Try searching for broader terms or select one of the priority feedstocks."
                )
        else:
            header_text = f"Found **{len(papers):,}** research works on **{normalized.title()}** "
            header_text += f"(Page {st.session_state.current_page})"
            st.caption(header_text)

            # Render paper cards
            for idx, paper in enumerate(papers, start=1):
                with st.container(border=True):
                    st.markdown(f"#### {idx}. {paper['title']}")

                    authors = paper.get("authors") or []
                    author_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
                    meta_line = f"**Authors:** {author_str} | **Year:** {paper.get('publication_year') or 'N/A'}"
                    if paper.get("citation_count"):
                        meta_line += f" | **Citations:** {paper['citation_count']}"
                    st.markdown(meta_line)

                    # Badges row
                    b_col1, b_col2, b_col3, b_col4 = st.columns([2, 2, 2, 4])
                    with b_col1:
                        rel_status = paper.get("relevance_status", "Relevant")
                        rel_score = paper.get("relevance_score", 0)
                        if rel_status == "Highly Relevant":
                            st.success(f"Score: {rel_score} • {rel_status}")
                        elif rel_status == "Relevant":
                            st.info(f"Score: {rel_score} • {rel_status}")
                        else:
                            st.caption(f"Score: {rel_score} • {rel_status}")

                    with b_col2:
                        has_abs = bool(paper.get("abstract"))
                        if has_abs:
                            st.markdown("📄 **Abstract Available**")
                        else:
                            st.markdown("📑 *Metadata Only*")

                    with b_col3:
                        is_oa = paper.get("is_open_access") or bool(paper.get("open_access_url"))
                        oa_url = paper.get("open_access_url")
                        if is_oa:
                            if oa_url:
                                st.markdown(f"🔓 [Open Access Link]({oa_url})")
                            else:
                                st.markdown("🔓 **Open Access**")
                        else:
                            st.markdown("🔒 *Closed / Paywalled*")

                    with b_col4:
                        doi = paper.get("doi")
                        landing_url = paper.get("landing_page_url")
                        if doi:
                            st.markdown(f"🔗 [DOI: {doi}]({doi})")
                        elif landing_url:
                            st.markdown(f"🔗 [Publication Link]({landing_url})")
                        else:
                            st.markdown(f"🔗 [OpenAlex ID]({paper.get('openalex_id')})")

                    if paper.get("abstract"):
                        with st.expander("📖 Read Reconstructed Abstract"):
                            st.write(paper["abstract"])

            # Pagination Controls
            st.divider()
            p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
            with p_col1:
                if st.session_state.current_page > 1:
                    if st.button("← Previous Page"):
                        st.session_state.current_page -= 1
                        st.rerun()
            with p_col2:
                st.write(f"Page **{st.session_state.current_page}** of ~{(len(papers) // 10) + 1:,}")
            with p_col3:
                if len(papers) > st.session_state.current_page * 10:
                    if st.button("Next Page →"):
                        st.session_state.current_page += 1
                        st.rerun()
