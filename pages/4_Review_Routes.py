"""
Review Routes - BioFlex Lab
Admin dashboard for human review, verification, editing, and promotion of AI-drafted production routes.
Protected by administrator credentials.
"""

import streamlit as st
import config
from services.review_service import (
    verify_admin_password,
    promote_route_to_verified,
    reject_route,
    get_pending_drafts,
)

st.set_page_config(
    page_title=f"Route Review - {config.APP_TITLE}",
    page_icon="📋",
    layout="wide",
)

st.title("📋 Production Route Human Review Dashboard")
st.caption("Promote AI-drafted pathways to human_verified, edit technical details, or reject inaccurate routes.")

# Sidebar authentication
st.sidebar.subheader("🔐 Admin Authentication")
admin_pass = st.sidebar.text_input(
    "Administrator Password:",
    type="password",
    help="Configured via ADMIN_PASSWORD in environment variables.",
)

if not verify_admin_password(admin_pass):
    st.warning(
        "🔒 **Administrator Access Restricted**\n\n"
        "Enter the administrator password in the sidebar to review, promote, or reject AI-drafted production routes.\n\n"
        "*Nothing may be promoted to human_verified without explicit administrative review.*"
    )
    st.stop()

st.sidebar.success("🔓 Authenticated as Administrator")

# Fetch pending drafts
drafts = get_pending_drafts(admin_pass)

st.metric("Pending AI Route Drafts", f"{len(drafts):,}")
st.divider()

if not drafts:
    st.success("✅ **All caught up!** There are currently no AI-drafted routes awaiting human review.")
else:
    st.markdown("### 📝 Draft Routes Awaiting Human Review")
    st.write("Carefully inspect the chemical steps, reaction conditions, and supporting literature citations before promoting.")

    for draft in drafts:
        route_id = draft["id"]
        mat_name = draft.get("material_name", "Unknown Feedstock").title()
        p_name = draft.get("product_name", "Bio-based Product")
        ev_level = draft.get("evidence_level", "Laboratory Demonstration")
        model = draft.get("model_name") or "Gemini"

        with st.container(border=True):
            r_col1, r_col2 = st.columns([3, 1])
            with r_col1:
                st.markdown(f"### 🌿 {mat_name} $\\rightarrow$ {p_name}")
                st.caption(f"**Route Type:** {draft.get('route_type', 'N/A')} | **Drafted By:** {model}")
            with r_col2:
                st.warning("🟠 **Review Status:** `ai_draft`")
                st.caption(f"Generated: {draft.get('generated_at') or 'Recently'}")

            st.write(f"**Route Summary:** {draft.get('route_summary', '')}")

            # Steps Expander
            with st.expander("⚙️ Inspect Chemical & Physical Process Steps", expanded=True):
                steps = draft.get("steps") or []
                if not steps:
                    st.caption("No steps documented.")
                else:
                    for s in steps:
                        st.markdown(f"**Step {s.get('step_number')}: {s.get('title')}**")
                        st.write(s.get("description", ""))
                        sc1, sc2 = st.columns(2)
                        with sc1:
                            st.caption(f"🧪 **Inputs:** `{s.get('required_inputs') or 'not reported'}`")
                        with sc2:
                            st.caption(f"🌡️ **Conditions:** `{s.get('conditions') or 'not reported'}`")
                        if s.get("paper_doi"):
                            st.caption(f"🔗 [Supporting Paper DOI]({s['paper_doi']}) — *{s.get('paper_title', '')}*")
                        elif s.get("paper_title"):
                            st.caption(f"📄 Supporting Paper: *{s.get('paper_title')}*")
                        st.markdown("---")

            # Technical Details
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                st.markdown(f"**📦 Applications:** {draft.get('applications') or 'not reported'}")
                st.markdown(f"**✨ Advantages:** {draft.get('advantages') or 'not reported'}")
            with d_col2:
                st.markdown(f"**⚠️ Limitations:** {draft.get('limitations') or 'not reported'}")
                st.markdown(f"**🌱 Environmental Notes:** {draft.get('environmental_notes') or 'not reported'}")

            st.divider()

            # Actions Area
            act_col1, act_col2, act_col3 = st.columns([2, 1, 1])
            with act_col1:
                reviewer_input = st.text_input(
                    "Reviewer Name / Title:",
                    value="BioFlex Lab Domain Expert",
                    key=f"reviewer_{route_id}",
                )

            with act_col2:
                st.write("")  # visual spacing
                if st.button("✅ Approve (Mark Verified)", key=f"app_{route_id}", type="primary", use_container_width=True):
                    res = promote_route_to_verified(
                        route_id=route_id,
                        reviewer_name=reviewer_input,
                        admin_password=admin_pass,
                    )
                    if res["success"]:
                        st.cache_data.clear()
                        st.success(res["message"])
                        st.rerun()
                    else:
                        st.error(res["error"])

            with act_col3:
                st.write("")  # visual spacing
                if st.button("❌ Reject Route", key=f"rej_{route_id}", use_container_width=True):
                    res = reject_route(
                        route_id=route_id,
                        admin_password=admin_pass,
                        reason="Marked as inaccurate during admin review",
                    )
                    if res["success"]:
                        st.cache_data.clear()
                        st.warning(res["message"])
                        st.rerun()
                    else:
                        st.error(res["error"])

