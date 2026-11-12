# BioFlex Lab: Project Brief for Antigravity

## 0. How to use this brief (read first)

You are my coding partner. I am a first-year B.Tech CSE (AI/ML) student with beginner-level Python. Save this file in the project root as `PROJECT_BRIEF.md` and re-read it at the start of every session.

**Working rules**
1. Build ONE phase at a time. Start with Phase 1 only. After each phase, stop, show results, and wait for my "approved" before continuing.
2. Before each phase, give me a 3-5 line plan in plain language (what, why, which files). Then implement.
3. Inspect the existing project first. Never overwrite a working file without reading it and telling me what changes.
4. Run the tests for the phase and show the real output. Never fabricate API responses, papers, DOIs, or test results.
5. Never hardcode secrets. Use `.env` locally (git-ignored) and `st.secrets` / platform secrets in deployment. Provide `.env.example` with placeholder names only.
6. Ask before: installing paid services, enabling paid API usage, running destructive commands (drop table, delete files, force push), or changing the architecture.
7. Pin dependency versions in `requirements.txt`. Keep code commented in a beginner-friendly way and prefer simple over clever.
8. Maintain `PROGRESS.md`: checklist of phases, what is done, test results, known issues, and decisions made (with reasons).
9. Verify against current official docs before using any API, model name, or package version. Do not rely on memory for these. If something is unavailable, propose a supported alternative and ask me before switching.
10. If you are unsure of a scientific fact, say so. Do not guess chemistry.

## 1. Project goal

**BioFlex Lab: An AI-Assisted Research Platform for Bioplastic Production from Renewable Raw Materials.**

A user searches a raw material (e.g., "sugarcane"). The app finds real research papers, shows what the literature says about converting that material into biodegradable plastics, displays source-backed production routes, and lets the user ask follow-up questions to an AI assistant powered by the Gemini API.

Audience: first-year students and non-specialists. Tone: clear, honest, professional. Context: college project combining Chemistry, IT, and Society.

**Core principle: honesty over fluency.** The AI must clearly separate what the papers show from general background knowledge, and must never invent sources.

## 2. Scope: MVP vs. stretch

**MVP (must work end to end)**
- Home page
- Material search with real OpenAlex results
- Papers saved in Neon
- AI assistant that answers questions with Gemini, with the papers found for the selected material passed in as context
- Production route pages for the 3 priority materials: sugarcane (sugar to PLA route), sugarcane bagasse (cellulose films/composites), banana peel (starch-based films)

**Stretch (only after MVP is approved)**
- Route comparison page
- Extra materials (corn starch, potato starch, cassava, rice husk)
- Keyword search over saved papers, answer-quality evaluation

**Explicitly NOT in this version:** embeddings, vector databases, pgvector, semantic/vector search, document chunking pipelines, and Supabase. Do not add them unless I ask.

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| UI | Streamlit, light custom CSS | Multipage app; `st.chat_message` + `st.session_state` for chat |
| Backend | Python 3.11+, `httpx` or `requests`, `pandas` | Keep services separate from UI |
| Paper discovery | OpenAlex API | Check current auth/rate-limit policy (API key or `mailto` identification) before coding |
| Database | Neon serverless Postgres | Plain tables only. Handle cold starts with retries/timeouts |
| LLM | Google Gemini API | Choose a currently supported model; keep the model name in config |
| Tooling | Git/GitHub, `venv`, `pytest` | |
| Deployment | Streamlit Community Cloud (or compatible) | Secrets via platform settings |

## 4. Features

1. **Home**: what BioFlex Lab is, the problem (plastic waste), how to use it.
2. **Material Explorer**: search a material, see papers and route information.
3. **Paper discovery**: normalize the material name and synonyms (e.g., "bagasse" = "sugarcane bagasse"), query OpenAlex with bioplastic-related keywords, reconstruct abstracts from OpenAlex's inverted-index format when present, deduplicate by DOI/OpenAlex ID, score and filter for relevance, save to Neon. Show title, authors, year, abstract (if any), DOI link, open-access link, and an "abstract available / metadata only" badge.
4. **Production routes**: per material, show composition, conversion pathway, ordered process steps, inputs and conditions (only when documented), resulting polymer, applications, advantages, limitations, environmental/social notes, and references. Each route carries an **evidence level**:
   - Commercial (established industrial process)
   - Pilot / scale-up
   - Laboratory demonstration
   - Emerging / exploratory

   Never merge different feedstock routes. Sugarcane sugars -> fermentation -> lactic acid -> PLA is a different route from bagasse -> cellulose films/composites.
5. **AI Assistant**: dedicated chat page. The scientist persona and rules live in backend config (a system prompt in code), so the user never writes a prompt.

## 5. How the AI assistant works (no embeddings)

Keep this simple: the assistant is a normal Gemini API call with a good built-in system prompt and some context from our own database.

1. The user picks a material (or it is detected from the question) and asks a question.
2. The backend loads the saved papers for that material from Neon (title, authors, year, DOI, abstract) and passes a small number of the most relevant ones (e.g., 5-10, with abstracts trimmed to fit) to Gemini as context. Select them by simple means: relevance score, publication year, or basic keyword matching on title/abstract. No embeddings.
3. The backend also passes the verified route and process-step rows for that material, if they exist.
4. The system prompt (set once in `config.py`) tells Gemini to:
   - Act as a careful, professional researcher who explains clearly for first-year students.
   - Use the provided papers and routes first, and cite them by paper number/title/DOI exactly as provided.
   - Clearly label anything that comes from general knowledge rather than the provided papers, for example "General background (not from the listed papers)".
   - Distinguish established/commercial processes from lab-scale or emerging research.
   - Say "I don't have enough information" instead of guessing, and suggest what to search next.
   - Never invent citations, DOIs, authors, yields, temperatures, or experimental conditions.
5. After the response, **validate in code**: any DOI or paper cited in the answer must match a paper that was actually provided. Flag or remove citations that do not match.
6. Keep recent chat turns in `st.session_state` only, so follow-up questions work. Do not store personal data. Chat history is not treated as verified knowledge.
7. Display the answer with a "Sources used" list (title, authors, year, DOI link) and a short disclaimer: "AI summaries can contain errors. Check the original sources."

Do not claim the AI has read a full paper when only the abstract was provided.

## 6. Database schema (starting point)

Create in `database/schema.sql` with simple migration scripts. Use parameterized queries and a connection helper. Plain Postgres tables only.

- `raw_materials(id, name, category, description, key_components, aliases, created_at)`
- `research_papers(id, openalex_id UNIQUE, doi UNIQUE NULLABLE, title, authors, publication_year, abstract, landing_page_url, open_access_url, relevance_status, relevance_score, metadata_json, created_at, updated_at)`
- `material_papers(material_id, paper_id, relevance_notes, PRIMARY KEY (material_id, paper_id))`
- `production_routes(id, material_id, product_name, route_summary, route_type, evidence_level, limitations, reviewed_by_human BOOLEAN)`
- `process_steps(id, route_id, step_number, title, description, required_inputs, conditions, supporting_paper_id)`

Notes:
- Route and process-step content must come from sources. Seed it from papers I have reviewed; do not auto-generate routes with the LLM into the database. Use `reviewed_by_human` to mark verified rows.
- No extra tables or infrastructure until the core flow works.

## 7. Phases (build in order, one at a time)

Each phase ends with: tests run, results shown, `PROGRESS.md` updated, and my approval requested.

1. **Environment & skeleton**: inspect folder, create venv, minimal dependencies, Streamlit multipage skeleton, `.gitignore`, `.env.example`, `requirements.txt`. *Done when:* `streamlit run app.py` loads the home page with no errors and navigation works.
2. **OpenAlex integration**: search, abstract reconstruction, pagination, dedup, relevance scoring, error handling, caching. *Done when:* searching "sugarcane" shows real, clickable records; empty and failed searches show friendly messages.
3. **Neon database**: schema, secure connection, save/retrieve papers, duplicate prevention. *Done when:* papers persist across app restarts and re-saving causes no duplicates.
4. **Gemini AI assistant**: Gemini integration, backend system prompt, context built from saved papers (and routes when available), source list display, citation validation, "not enough information" replies, follow-up questions. *Done when:* the assistant answers questions about a material using the saved papers, shows its sources with working links, and honestly says when it lacks information.
5. **Production route pages**: routes, expandable steps, evidence levels, linked papers. *Done when:* a user can go from a material to its routes to the supporting sources.
6. **Comparison & UX (stretch)**: route comparison, better loading/error states, styling.
7. **Testing & evaluation**: see section 9.
8. **Deployment**: GitHub (no secrets), deploy, secrets configured, Neon access restrictions, test from another device.

## 8. UI requirements

Clean white/neutral background, readable typography, consistent spacing, simple navigation, search bar, paper cards with badges, expandable process steps, visible source links and evidence labels, loading indicators, useful error messages, responsive where practical. Avoid fake data, decorative "AI" effects, vanity metrics, and unsupported scientific claims.

## 9. Testing and evaluation

- Unit tests (`pytest`) for the OpenAlex parser, dedup, citation validator, and DB functions.
- Integration tests with real API responses where credentials allow. Mock data only for isolated UI work, clearly labeled.
- Edge cases: unknown material, irrelevant papers, missing abstracts, API timeout, invalid keys, no saved papers for a material, conflicting papers.
- Evaluation set in `tests/eval_questions.md`: 15-20 questions (including 3-5 that SHOULD get "not enough information") with the expected source papers. I will manually check answers; record results in `PROGRESS.md`.
- Security check: no secrets in git history, parameterized queries only, keys never reach the browser.

## 10. Safety and ethics

- The app is educational. Describe processes at the level documented in the literature. For steps involving hazardous chemicals, heat, or pressure, show the paper's conditions and add a note that these are research findings, not instructions to replicate at home without supervision.
- Respect publisher terms and OpenAlex usage policy. Use metadata, abstracts, and legally accessible content only.
- Show a short disclaimer: "Summaries are generated by AI and may contain errors. Check the original sources."

## 11. Suggested structure (adapt if simpler)

```
BioFlex-Lab/
  app.py
  PROJECT_BRIEF.md
  PROGRESS.md
  requirements.txt
  .gitignore
  .env.example
  config.py                 # model name, system prompt, number of papers sent
  pages/
    1_Material_Explorer.py
    2_AI_Assistant.py
    3_Compare_Routes.py     # stretch
    4_About.py
  services/
    openalex_service.py
    database_service.py
    context_builder.py      # picks papers/routes to send to Gemini
    gemini_service.py
    citation_validator.py
  database/
    schema.sql
    migrations/
  research/research_notes.md
  tests/
  assets/
```

Keep API calls, database logic, AI logic, and UI in separate modules.

## 12. Final objective

A deployed Streamlit app where a user searches a renewable raw material, sees real papers and source-backed production routes, and asks questions to a Gemini-powered assistant that explains clearly, shows its sources, separates paper-based facts from general background, and openly says when it does not know.
