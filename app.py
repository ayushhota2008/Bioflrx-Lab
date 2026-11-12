"""
BioFlex Lab - Main Streamlit Application
Home page introducing the platform, the global plastic challenge, and guide for students.
"""

import streamlit as st
import config

# Configure the Streamlit page layout and metadata
st.set_page_config(
    page_title=f"{config.APP_TITLE} - Home",
    page_icon=config.APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

def main():
    # Header section
    st.title(f"{config.APP_ICON} {config.APP_TITLE}")
    st.subheader(config.APP_TAGLINE)
    st.caption("A research-backed educational platform bridging Chemistry, Computer Science, and Society.")

    st.divider()

    # Introduction & The Problem
    col1, col2 = st.columns([3, 2], gap="large")

    with col1:
        st.markdown("### 🌍 The Challenge: Petroleum Plastic Waste")
        st.write(
            """
            Conventional synthetic plastics derived from petroleum persist in ecosystems for centuries.
            Over 400 million tonnes of plastic are produced annually worldwide, with less than 10% effectively recycled.
            The resulting microplastic contamination, ocean pollution, and greenhouse emissions demand renewable, 
            rapidly biodegradable alternatives derived from biomass.
            """
        )

        st.markdown("### 🔬 What BioFlex Lab Does")
        st.write(
            """
            **BioFlex Lab** connects first-year students and researchers to peer-reviewed scientific literature 
            on turning renewable agricultural residues and crops into bioplastics:
            
            - **Literature Discovery:** Retrieves real scientific research from OpenAlex on renewable raw materials.
            - **Production Pathways:** Maps validated chemical, enzymatic, and mechanical conversion routes.
            - **Grounded AI Assistance:** Queries Gemini with research papers passed as context, enforcing honesty and traceable citations.
            """
        )

    with col2:
        st.info(
            """
            **🎯 Priority Feedstocks (MVP)**
            
            1. **Sugarcane (Juice/Sugar)**: Sucrose fermentation to lactic acid, polymerized to Poly(lactic acid) [PLA].
            2. **Sugarcane Bagasse**: Cellulose and lignin extraction for biodegradable composite films.
            3. **Banana Peel**: Starch extraction and plasticization into flexible bio-films.
            """
        )

        st.warning(
            f"**Platform Principle**\n\n{config.AI_DISCLAIMER}"
        )

    st.divider()

    # Quick Navigation Guide
    st.markdown("### 🚀 Getting Started")
    nav1, nav2, nav3 = st.columns(3)

    with nav1:
        st.markdown("#### 1. Material Explorer")
        st.write("Search feedstocks, discover indexed papers from OpenAlex, and inspect verified chemical pathways.")
        st.page_link("pages/1_Material_Explorer.py", label="Open Material Explorer →", icon="🔍")

    with nav2:
        st.markdown("#### 2. AI Assistant")
        st.write("Ask technical questions to a research assistant grounded in retrieved literature.")
        st.page_link("pages/2_AI_Assistant.py", label="Chat with AI Assistant →", icon="🤖")

    with nav3:
        st.markdown("#### 3. About & Context")
        st.write("Learn about the project's background, evidence rating scale, and academic sources.")
        st.page_link("pages/3_About.py", label="Read Project Context →", icon="📖")

if __name__ == "__main__":
    main()

