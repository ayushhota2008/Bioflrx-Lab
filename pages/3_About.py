"""
About BioFlex Lab
Background, evidence ranking criteria, data sources, and educational disclaimers.
"""

import streamlit as st
import config

st.set_page_config(
    page_title=f"About - {config.APP_TITLE}",
    page_icon="📖",
    layout="wide",
)

st.title("📖 About BioFlex Lab")
st.caption("College project combining Chemistry, Information Technology, and Environmental Society.")

st.divider()

st.markdown("### 🎓 Academic Context & Mission")
st.write(
    """
    BioFlex Lab is developed by a first-year B.Tech CSE (AI/ML) student as a pragmatic, transparent tool
    for evaluating renewable feedstocks for bioplastic production.
    
    Rather than generating ungrounded speculative AI text, BioFlex Lab couples open academic literature (OpenAlex)
    with structured chemical pathways and Google's Gemini API to provide **honest, cited, and verifiable scientific insights**.
    """
)

st.markdown("### 📊 Evidence Level Classification")
st.write("Every production route displayed on BioFlex Lab is classified under one of four evidence tiers:")

e1, e2, e3, e4 = st.columns(4)
with e1:
    st.success("**Commercial**\n\nEstablished industrial manufacturing processes deployed at commercial scale (e.g. PLA from sugarcane sucrose).")
with e2:
    st.info("**Pilot / Scale-Up**\n\nValidated beyond bench scale in pilot plants or continuous reactor environments.")
with e3:
    st.warning("**Laboratory Demonstration**\n\nPeer-reviewed bench-scale experiments with repeatable synthesis protocols.")
with e4:
    st.error("**Emerging / Exploratory**\n\nEarly-stage proofs of concept, novel pre-treatments, or computational simulations.")

st.divider()

st.markdown("### 🛡️ Safety & Ethics Disclaimer")
st.write(
    """
    - **Educational Scope:** Descriptions of chemical processes, reactions, temperatures, and pressures reflect findings published in academic literature.
    - **No DIY Instructions:** Chemical reactions involving concentrated acids, organic solvents, high autoclave pressures, or thermal pyrolysis should **never** be attempted outside certified laboratory facilities with proper personal protective equipment (PPE).
    - **Source Grounding:** AI assistance explicitly separates paper findings from general knowledge and does not fabricate citations.
    """
)

