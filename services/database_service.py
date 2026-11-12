"""
Database Service for BioFlex Lab.
Connects to Neon PostgreSQL, executes schema setup, seeds verified routes,
and handles paper persistence with duplicate prevention.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Global thread-safe connection pool (min 1, max 10 connections)
_connection_pool: Optional[pool.ThreadedConnectionPool] = None

# Max retries for handling Neon compute cold-starts
MAX_RETRIES = 3
RETRY_DELAY = 2.0


def get_connection_pool() -> pool.ThreadedConnectionPool:
    """Initialize or return the existing thread-safe connection pool."""
    global _connection_pool
    if _connection_pool is None or _connection_pool.closed:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is not configured.")
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=db_url,
        )
    return _connection_pool


def get_connection(retries: int = MAX_RETRIES):
    """
    Acquire a database connection from the pool, with retry logic
    to accommodate Neon serverless compute spin-up delays.
    """
    last_error = None
    for attempt in range(retries):
        try:
            cp = get_connection_pool()
            conn = cp.getconn()
            if conn:
                return conn
        except Exception as e:
            last_error = e
            time.sleep(RETRY_DELAY)
    raise ConnectionError(f"Failed to connect to Neon PostgreSQL after {retries} attempts: {last_error}")


def release_connection(conn):
    """Safely return connection to the pool."""
    if conn and _connection_pool and not _connection_pool.closed:
        try:
            _connection_pool.putconn(conn)
        except Exception:
            pass


def init_db(schema_file_path: Optional[str] = None):
    """
    Initialize database schema by running schema.sql and seeding initial materials.
    """
    if schema_file_path is None:
        schema_file_path = os.path.join(os.path.dirname(__file__), "..", "database", "schema.sql")

    with open(schema_file_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    finally:
        release_connection(conn)

    # Seed verified materials and routes
    seed_verified_data()


def seed_verified_data():
    """
    Seed raw materials and verified human-reviewed production routes
    for the 3 MVP priority feedstocks:
    1. Sugarcane (Sucrose -> Fermentation -> Lactic Acid -> PLA)
    2. Sugarcane Bagasse (Cellulose extraction -> Cellulose films/nanocomposites)
    3. Banana Peel (Starch extraction -> Plasticized films)
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Ensure schema migration columns exist
            cur.execute("ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS applications TEXT;")
            cur.execute("ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS advantages TEXT;")
            cur.execute("ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS environmental_notes TEXT;")

            # 1. Seed raw_materials
            materials = [
                (
                    "sugarcane",
                    "Agricultural Sugar Crop",
                    "C4 perennial grass rich in sucrose juice, widely cultivated for sugar and bioethanol.",
                    "Sucrose (12-16%), Fiber (10-15%), Water (70-75%)",
                    ["sugar cane", "sugarcane juice", "cane sugar"],
                ),
                (
                    "sugarcane bagasse",
                    "Agricultural Lignocellulosic Residue",
                    "Dry pulpy fibrous residue remaining after crushing sugarcane stalks to extract juice.",
                    "Cellulose (40-50%), Hemicellulose (25-35%), Lignin (20-25%)",
                    ["bagasse", "cane bagasse", "sugarcane fiber"],
                ),
                (
                    "banana peel",
                    "Fruit Processing Agro-Waste",
                    "Outer protective skin discarded during fresh consumption and fruit processing.",
                    "Starch (10-20%), Pectin (10-15%), Cellulose/Hemicellulose (15-25%), Moisture",
                    ["banana skins", "banana peels", "musa peel"],
                ),
            ]

            for name, category, desc, components, aliases in materials:
                cur.execute(
                    """
                    INSERT INTO raw_materials (name, category, description, key_components, aliases)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        key_components = EXCLUDED.key_components,
                        aliases = EXCLUDED.aliases
                    RETURNING id;
                    """,
                    (name, category, desc, components, aliases),
                )
            conn.commit()

            def get_mat_id(mat_name):
                cur.execute("SELECT id FROM raw_materials WHERE name = %s;", (mat_name,))
                row = cur.fetchone()
                return row["id"] if row else None

            # 2. Seed Sugarcane -> PLA Route (Commercial)
            sugarcane_id = get_mat_id("sugarcane")
            if sugarcane_id:
                cur.execute(
                    """
                    SELECT id FROM production_routes 
                    WHERE material_id = %s AND product_name = %s;
                    """,
                    (sugarcane_id, "Poly(lactic acid) [PLA]"),
                )
                route_row = cur.fetchone()

                pla_apps = "Thermoformed packaging, disposable food containers, cold-beverage cups, 3D printing filament, agricultural mulch films, bio-resorbable medical sutures."
                pla_advs = "High optical clarity, excellent tensile strength (~50-70 MPa), thermoplastic processability on standard industrial extruders, derived from 100% bio-based carbon."
                pla_env = "Reduces fossil carbon footprint by up to 68% compared to PET; bagasse byproduct from sugar extraction is burned on-site for carbon-neutral process energy."

                if not route_row:
                    cur.execute(
                        """
                        INSERT INTO production_routes 
                            (material_id, product_name, route_summary, route_type, evidence_level, limitations, applications, advantages, environmental_notes, reviewed_by_human)
                        VALUES 
                            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            sugarcane_id,
                            "Poly(lactic acid) [PLA]",
                            "Industrial conversion of fermentable sugarcane sucrose into L-lactic acid, followed by lactide dimerization and ring-opening polymerization to produce high molecular weight PLA thermoplastic.",
                            "Fermentation & Ring-Opening Polymerization",
                            "Commercial",
                            "Competes with food/sugar crops for arable land; industrial composting facilities (>58°C) required for biodegradation.",
                            pla_apps, pla_advs, pla_env, True,
                        ),
                    )
                    route_row = cur.fetchone()
                else:
                    cur.execute(
                        """
                        UPDATE production_routes SET
                            applications = %s, advantages = %s, environmental_notes = %s
                        WHERE id = %s;
                        """,
                        (pla_apps, pla_advs, pla_env, route_row["id"]),
                    )

                route_id = route_row["id"]
                steps = [
                    (1, "Juice Extraction & Clarification", "Sugarcane is milled to crush juice, which is filtered, limed, and concentrated into fermentable sucrose syrups.", "Milling water, lime (calcium hydroxide), flocculants", "Temperature 70-100°C, pH 7.0-7.5, mechanical multi-roller milling"),
                    (2, "Lactic Acid Fermentation", "Inoculation with homofermentative bacterial strains (e.g. Lactobacillus delbrueckii) converting sucrose/glucose to L-lactic acid at high selectivity.", "Nutrient broth, yeast extract, calcium carbonate neutralizer", "Temperature 37-45°C, pH 5.5-6.5, anaerobic/microaerophilic, 48-72 hours (yield >90%)"),
                    (3, "Lactide Formation & Ring-Opening Polymerization (ROP)", "Lactic acid undergoes polycondensation into oligomers, catalytic depolymerization into cyclic lactide dimer, and tin-catalyzed ROP into high molecular weight PLA.", "L-lactic acid, stannous octoate catalyst, solvent-free melt", "Vacuum depolymerization at 180-220°C, ring-opening polymerization at 160-190°C under <10 mbar vacuum"),
                ]
                for s_num, s_title, s_desc, s_inputs, s_cond in steps:
                    cur.execute(
                        """
                        INSERT INTO process_steps (route_id, step_number, title, description, required_inputs, conditions)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (route_id, step_number) DO UPDATE SET
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            required_inputs = EXCLUDED.required_inputs,
                            conditions = EXCLUDED.conditions;
                        """,
                        (route_id, s_num, s_title, s_desc, s_inputs, s_cond),
                    )

            # 3. Seed Bagasse -> Cellulose films (Pilot / Scale-Up)
            bagasse_id = get_mat_id("sugarcane bagasse")
            if bagasse_id:
                cur.execute(
                    """
                    SELECT id FROM production_routes 
                    WHERE material_id = %s AND product_name = %s;
                    """,
                    (bagasse_id, "Cellulose Nanocomposite Films"),
                )
                route_row = cur.fetchone()

                bag_apps = "Oxygen-barrier food wraps, grease-resistant paper coatings, biodegradable composite trays, organic electronics dielectric substrates, paper reinforcement."
                bag_advs = "Valorizes abundant post-harvest agricultural waste (non-food); exceptional Young's modulus (>8-12 GPa); rapid biodegradation in soil without industrial composting."
                bag_env = "Prevents open-field burning of bagasse; eliminates methane from landfilling; zero competition with human food supplies."

                if not route_row:
                    cur.execute(
                        """
                        INSERT INTO production_routes 
                            (material_id, product_name, route_summary, route_type, evidence_level, limitations, applications, advantages, environmental_notes, reviewed_by_human)
                        VALUES 
                            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            bagasse_id,
                            "Cellulose Nanocomposite Films",
                            "Alkaline delignification and bleaching of bagasse fiber to isolate high-purity cellulose, followed by homogenization and casting into biodegradable barrier films.",
                            "Delignification & Solution Casting",
                            "Pilot / Scale-Up",
                            "High chemical and energy demand for delignification and nanofibrillation; sensitivity to high humidity unless crosslinked.",
                            bag_apps, bag_advs, bag_env, True,
                        ),
                    )
                    route_row = cur.fetchone()
                else:
                    cur.execute(
                        """
                        UPDATE production_routes SET
                            applications = %s, advantages = %s, environmental_notes = %s
                        WHERE id = %s;
                        """,
                        (bag_apps, bag_advs, bag_env, route_row["id"]),
                    )

                route_id = route_row["id"]
                bagasse_steps = [
                    (1, "Alkaline Delignification & Soda Pulping", "Treatment of chopped bagasse with sodium hydroxide to solubilize lignin and hemicellulose, isolating insoluble cellulose fibers.", "NaOH (10-14% w/v), water, solid-to-liquid ratio 1:10", "Digestion temperature 100-120°C for 2-3 hours; removes up to 85% of acid-insoluble lignin"),
                    (2, "Bleaching & Alpha-Cellulose Purification", "Purification of washed brown pulp using hydrogen peroxide to remove chromophores and residual lignin.", "Hydrogen peroxide (H2O2 3-5%), sodium silicate stabilizer", "Temperature 70-80°C, pH 10.0-10.5, 90 minutes; yields bright white alpha-cellulose (>88% purity)"),
                    (3, "High-Pressure Nanofibrillation & Film Casting", "Alpha-cellulose slurry is passed through a high-pressure homogenizer, plasticized with glycerol, and solution-cast into clear barrier films.", "Alpha-cellulose slurry (1-2%), glycerol (20-30% w/w dry fiber), casting plates", "Homogenization at 600-1000 bar (10-15 passes); degassing; level casting and drying at 45-50°C for 24 hours"),
                ]
                for s_num, s_title, s_desc, s_inputs, s_cond in bagasse_steps:
                    cur.execute(
                        """
                        INSERT INTO process_steps (route_id, step_number, title, description, required_inputs, conditions)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (route_id, step_number) DO UPDATE SET
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            required_inputs = EXCLUDED.required_inputs,
                            conditions = EXCLUDED.conditions;
                        """,
                        (route_id, s_num, s_title, s_desc, s_inputs, s_cond),
                    )

            # 4. Seed Banana Peel -> Thermoplastic Starch (Laboratory Demonstration)
            banana_id = get_mat_id("banana peel")
            if banana_id:
                cur.execute(
                    """
                    SELECT id FROM production_routes 
                    WHERE material_id = %s AND product_name = %s;
                    """,
                    (banana_id, "Thermoplastic Starch Bio-Film"),
                )
                route_row = cur.fetchone()

                ban_apps = "Single-use grocery bags, seedling planting envelopes, dry-goods wrappers, disposable organic waste bin liners."
                ban_advs = "Utilizes high-volume municipal and agro-processing food waste; 100% home compostable within 30-60 days; non-toxic plasticization using food-grade glycerol."
                ban_env = "Diverts organic fruit waste from landfills, directly mitigating methane emissions while reducing dependence on synthetic single-use polyethylene."

                if not route_row:
                    cur.execute(
                        """
                        INSERT INTO production_routes 
                            (material_id, product_name, route_summary, route_type, evidence_level, limitations, applications, advantages, environmental_notes, reviewed_by_human)
                        VALUES 
                            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            banana_id,
                            "Thermoplastic Starch Bio-Film",
                            "Aqueous or alkaline extraction of starch and pectin from discarded banana peels, followed by thermal gelatinization with glycerol plasticizer and casting.",
                            "Starch Extraction & Solution Casting",
                            "Laboratory Demonstration",
                            "Low tensile strength and high moisture absorption compared to petroleum plastics; batch-to-batch variation based on fruit ripeness.",
                            ban_apps, ban_advs, ban_env, True,
                        ),
                    )
                    route_row = cur.fetchone()
                else:
                    cur.execute(
                        """
                        UPDATE production_routes SET
                            applications = %s, advantages = %s, environmental_notes = %s
                        WHERE id = %s;
                        """,
                        (ban_apps, ban_advs, ban_env, route_row["id"]),
                    )

                route_id = route_row["id"]
                banana_steps = [
                    (1, "Peel Washing, Anti-Browning Soak & Convective Drying", "Washing peels, immersion in sodium metabisulfite or citric acid to inhibit polyphenol oxidase browning, and convective air drying.", "Water, 0.5% sodium metabisulfite or 1% citric acid solution", "Peels sliced to 1 cm, soaked 20 min, oven dried at 55-60°C for 18-24 hours"),
                    (2, "Milling & Aqueous Starch Sedimentation", "Milling dried peel chips into powder, slurry agitation in water, filtration, and sedimentation/centrifugation to separate pure starch granules.", "Distilled water, 100-mesh sieve (150 µm), centrifuge", "Slurry agitated 30 min (1:5 w/v); centrifuged at 3000 rpm for 10 min, washed 3 times, dried at 40°C"),
                    (3, "Thermal Gelatinization & Solution Casting", "Starch suspension is blended with glycerol plasticizer and heated above gelatinization temperature with continuous stirring, then poured onto level molds.", "Banana peel starch (5-10% w/v), glycerol (25-35% w/w dry starch), dilute acetic acid (1%)", "Continuous stirring at 500 rpm while heating at 75-85°C for 20-30 min; ultrasonic degassing; dried at 45°C for 24 hours"),
                ]
                for s_num, s_title, s_desc, s_inputs, s_cond in banana_steps:
                    cur.execute(
                        """
                        INSERT INTO process_steps (route_id, step_number, title, description, required_inputs, conditions)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (route_id, step_number) DO UPDATE SET
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            required_inputs = EXCLUDED.required_inputs,
                            conditions = EXCLUDED.conditions;
                        """,
                        (route_id, s_num, s_title, s_desc, s_inputs, s_cond),
                    )

            conn.commit()
    finally:
        release_connection(conn)


def get_all_materials() -> List[Dict[str, Any]]:
    """Retrieve all registered raw materials."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM raw_materials ORDER BY name ASC;")
            return cur.fetchall()
    finally:
        release_connection(conn)


def get_material_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Fetch raw material record by canonical name or alias."""
    if not name:
        return None
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            clean_name = name.strip()
            cur.execute(
                """
                SELECT * FROM raw_materials 
                WHERE LOWER(name) = LOWER(%s)
                   OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(aliases, ARRAY[]::text[]))))
                LIMIT 1;
                """,
                (clean_name, clean_name),
            )
            return cur.fetchone()
    finally:
        release_connection(conn)


def add_material_alias(canonical_name: str, alias: str) -> bool:
    """Add an alias/typo to raw_materials.aliases for the canonical material."""
    if not canonical_name or not alias:
        return False
    clean_canon = canonical_name.strip().lower()
    clean_alias = alias.strip().lower()
    if clean_canon == clean_alias:
        return False
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE raw_materials
                SET aliases = ARRAY(
                    SELECT DISTINCT unnest(array_append(COALESCE(aliases, ARRAY[]::text[]), %s))
                )
                WHERE LOWER(name) = LOWER(%s)
                   OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(aliases, ARRAY[]::text[]))));
                """,
                (clean_alias, clean_canon, clean_canon),
            )
            conn.commit()
            return True
    finally:
        release_connection(conn)


def save_paper(paper: Dict[str, Any], material_name: Optional[str] = None) -> int:
    """
    Save a single paper into research_papers with duplicate prevention.
    If the paper already exists (by openalex_id), update its fields.
    Optionally link to material in material_papers.
    Returns the integer primary key paper_id.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            openalex_id = paper.get("openalex_id")
            doi = paper.get("doi")
            title = paper.get("title") or "Untitled Paper"
            authors = paper.get("authors") or []
            pub_year = paper.get("publication_year")
            abstract = paper.get("abstract")
            landing_url = paper.get("landing_page_url")
            oa_url = paper.get("open_access_url")
            rel_status = paper.get("relevance_status", "Potentially Relevant")
            rel_score = paper.get("relevance_score", 0)
            citations = paper.get("citation_count", 0)
            metadata = json.dumps(paper.get("metadata_json") or {})

            cur.execute(
                """
                INSERT INTO research_papers (
                    openalex_id, doi, title, authors, publication_year,
                    abstract, landing_page_url, open_access_url,
                    relevance_status, relevance_score, citation_count,
                    metadata_json, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (openalex_id) DO UPDATE SET
                    doi = COALESCE(EXCLUDED.doi, research_papers.doi),
                    title = EXCLUDED.title,
                    authors = EXCLUDED.authors,
                    publication_year = EXCLUDED.publication_year,
                    abstract = COALESCE(EXCLUDED.abstract, research_papers.abstract),
                    landing_page_url = EXCLUDED.landing_page_url,
                    open_access_url = EXCLUDED.open_access_url,
                    relevance_status = EXCLUDED.relevance_status,
                    relevance_score = EXCLUDED.relevance_score,
                    citation_count = EXCLUDED.citation_count,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (
                    openalex_id, doi, title, authors, pub_year,
                    abstract, landing_url, oa_url, rel_status,
                    rel_score, citations, metadata
                ),
            )
            paper_id = cur.fetchone()["id"]

            if material_name:
                clean_mat = material_name.strip()
                cur.execute(
                    """
                    SELECT id FROM raw_materials 
                    WHERE LOWER(name) = LOWER(%s)
                       OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(aliases, ARRAY[]::text[]))))
                    LIMIT 1;
                    """,
                    (clean_mat, clean_mat),
                )
                mat_row = cur.fetchone()
                if not mat_row:
                    cur.execute(
                        "INSERT INTO raw_materials (name) VALUES (%s) RETURNING id;",
                        (clean_mat.lower(),)
                    )
                    mat_row = cur.fetchone()
                
                material_id = mat_row["id"]
                cur.execute(
                    """
                    INSERT INTO material_papers (material_id, paper_id, relevance_notes)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (material_id, paper_id) DO NOTHING;
                    """,
                    (material_id, paper_id, f"Relevance score: {rel_score}"),
                )

            conn.commit()
            return paper_id
    finally:
        release_connection(conn)


def save_papers_batch(papers: List[Dict[str, Any]], material_name: str) -> int:
    """Save a batch of papers for a material using a single connection and transaction."""
    if not papers:
        return 0
    clean_mat = material_name.strip()
    conn = get_connection()
    saved_count = 0
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id FROM raw_materials 
                WHERE LOWER(name) = LOWER(%s)
                   OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(aliases, ARRAY[]::text[]))))
                LIMIT 1;
                """,
                (clean_mat, clean_mat),
            )
            mat_row = cur.fetchone()
            if not mat_row:
                cur.execute(
                    "INSERT INTO raw_materials (name) VALUES (%s) RETURNING id;",
                    (clean_mat.lower(),),
                )
                mat_row = cur.fetchone()
            material_id = mat_row["id"]

            for p in papers:
                try:
                    openalex_id = p.get("openalex_id")
                    if not openalex_id:
                        continue
                    doi = p.get("doi")
                    title = p.get("title") or "Untitled Paper"
                    authors = p.get("authors") or []
                    pub_year = p.get("publication_year")
                    abstract = p.get("abstract")
                    landing_url = p.get("landing_page_url")
                    oa_url = p.get("open_access_url")
                    rel_status = p.get("relevance_status", "Potentially Relevant")
                    rel_score = p.get("relevance_score", 0)
                    citations = p.get("citation_count", 0)
                    metadata = json.dumps(p.get("metadata_json") or {})

                    cur.execute(
                        """
                        INSERT INTO research_papers (
                            openalex_id, doi, title, authors, publication_year,
                            abstract, landing_page_url, open_access_url, relevance_status,
                            relevance_score, citation_count, metadata_json
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (openalex_id) DO UPDATE SET
                            title = EXCLUDED.title,
                            authors = EXCLUDED.authors,
                            publication_year = EXCLUDED.publication_year,
                            abstract = COALESCE(EXCLUDED.abstract, research_papers.abstract),
                            landing_page_url = EXCLUDED.landing_page_url,
                            open_access_url = EXCLUDED.open_access_url,
                            relevance_status = EXCLUDED.relevance_status,
                            relevance_score = EXCLUDED.relevance_score,
                            citation_count = EXCLUDED.citation_count,
                            metadata_json = EXCLUDED.metadata_json,
                            updated_at = CURRENT_TIMESTAMP
                        RETURNING id;
                        """,
                        (openalex_id, doi, title, authors, pub_year, abstract, landing_url, oa_url, rel_status, rel_score, citations, metadata),
                    )
                    paper_id = cur.fetchone()["id"]
                    cur.execute(
                        """
                        INSERT INTO material_papers (material_id, paper_id, relevance_notes)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (material_id, paper_id) DO NOTHING;
                        """,
                        (material_id, paper_id, f"Relevance score: {rel_score}"),
                    )
                    saved_count += 1
                except Exception as p_err:
                    print(f"Error saving paper {p.get('title')}: {p_err}")

            conn.commit()
            return saved_count
    finally:
        release_connection(conn)


def get_papers_for_material(material_name: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve stored papers for a given material, ordered by relevance_score DESC."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            clean_name = material_name.strip()
            cur.execute(
                """
                SELECT p.*
                FROM research_papers p
                JOIN material_papers mp ON p.id = mp.paper_id
                JOIN raw_materials m ON m.id = mp.material_id
                WHERE LOWER(m.name) = LOWER(%s)
                   OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(m.aliases, ARRAY[]::text[]))))
                ORDER BY p.relevance_score DESC, p.publication_year DESC NULLS LAST
                LIMIT %s;
                """,
                (clean_name, clean_name, limit),
            )
            return cur.fetchall()
    finally:
        release_connection(conn)


def get_saved_paper_count() -> int:
    """Return total number of saved research papers in Neon."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM research_papers;")
            return cur.fetchone()[0]
    finally:
        release_connection(conn)


def get_routes_for_material(material_name: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve production routes and their ordered process steps for a material."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            clean_name = material_name.strip()
            if status_filter:
                cur.execute(
                    """
                    SELECT r.* 
                    FROM production_routes r
                    JOIN raw_materials m ON m.id = r.material_id
                    WHERE (LOWER(m.name) = LOWER(%s) OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(m.aliases, ARRAY[]::text[])))))
                      AND r.review_status = %s
                    ORDER BY r.id ASC;
                    """,
                    (clean_name, clean_name, status_filter),
                )
            else:
                cur.execute(
                    """
                    SELECT r.* 
                    FROM production_routes r
                    JOIN raw_materials m ON m.id = r.material_id
                    WHERE (LOWER(m.name) = LOWER(%s) OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(m.aliases, ARRAY[]::text[])))))
                      AND (r.review_status != 'rejected' OR r.review_status IS NULL)
                    ORDER BY 
                        CASE WHEN r.review_status = 'human_verified' THEN 0 ELSE 1 END,
                        r.id ASC;
                    """,
                    (clean_name, clean_name),
                )
            routes = cur.fetchall()
            if not routes:
                return []

            route_ids = [r["id"] for r in routes]
            cur.execute(
                """
                SELECT s.*, p.title as paper_title, p.doi as paper_doi, p.openalex_id
                FROM process_steps s
                LEFT JOIN research_papers p ON s.supporting_paper_id = p.id
                WHERE s.route_id = ANY(%s)
                ORDER BY s.route_id ASC, s.step_number ASC;
                """,
                (route_ids,),
            )
            all_steps = cur.fetchall()
            steps_by_route = {}
            for step in all_steps:
                steps_by_route.setdefault(step["route_id"], []).append(step)

            for r in routes:
                r["steps"] = steps_by_route.get(r["id"], [])

            return routes
    finally:
        release_connection(conn)


def save_route_with_steps(
    material_name: str,
    route_data: Dict[str, Any],
    review_status: str = "ai_draft",
    generated_by: str = "gemini",
    model_name: Optional[str] = None,
) -> int:
    """
    Save or update a production route and its process steps in Neon.
    If the route was already human-verified, its review_status is NEVER downgraded to ai_draft.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            clean_name = material_name.strip()
            cur.execute(
                """
                SELECT id FROM raw_materials 
                WHERE LOWER(name) = LOWER(%s)
                   OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(aliases, ARRAY[]::text[]))))
                LIMIT 1;
                """,
                (clean_name, clean_name),
            )
            mat_row = cur.fetchone()
            if not mat_row:
                cur.execute(
                    "INSERT INTO raw_materials (name, category, description) VALUES (%s, %s, %s) RETURNING id;",
                    (clean_name.lower(), "Agricultural Feedstock", f"Renewable raw material: {clean_name}"),
                )
                mat_row = cur.fetchone()

            mat_id = mat_row["id"]
            p_name = route_data.get("product_name") or "Bio-based Material"
            r_summary = route_data.get("route_summary") or "Conversion pathway documented in literature."
            r_type = route_data.get("route_type") or "Chemical Conversion"
            ev_level = route_data.get("evidence_level") or "Laboratory Demonstration"
            limitations = route_data.get("limitations")
            apps = route_data.get("applications")
            advs = route_data.get("advantages")
            env_notes = route_data.get("environmental_notes")

            is_human = (review_status == "human_verified")

            cur.execute(
                """
                INSERT INTO production_routes (
                    material_id, product_name, route_summary, route_type, evidence_level,
                    limitations, applications, advantages, environmental_notes,
                    reviewed_by_human, review_status, generated_by, model_name, generated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (material_id, product_name) DO UPDATE SET
                    route_summary = EXCLUDED.route_summary,
                    route_type = EXCLUDED.route_type,
                    evidence_level = EXCLUDED.evidence_level,
                    limitations = EXCLUDED.limitations,
                    applications = EXCLUDED.applications,
                    advantages = EXCLUDED.advantages,
                    environmental_notes = EXCLUDED.environmental_notes,
                    review_status = CASE 
                        WHEN production_routes.review_status = 'human_verified' THEN 'human_verified'
                        ELSE EXCLUDED.review_status
                    END,
                    reviewed_by_human = CASE
                        WHEN production_routes.review_status = 'human_verified' THEN TRUE
                        ELSE EXCLUDED.reviewed_by_human
                    END,
                    model_name = EXCLUDED.model_name
                RETURNING id;
                """,
                (
                    mat_id, p_name, r_summary, r_type, ev_level,
                    limitations, apps, advs, env_notes,
                    is_human, review_status, generated_by, model_name
                ),
            )
            route_id = cur.fetchone()["id"]

            # Save steps
            steps = route_data.get("steps") or []
            for s in steps:
                s_num = s.get("step_number", 1)
                s_title = s.get("title") or f"Step {s_num}"
                s_desc = s.get("description") or ""
                s_inputs = s.get("required_inputs") or "not reported"
                s_cond = s.get("conditions") or "not reported"
                s_paper_id = s.get("supporting_paper_id")

                # Validate supporting_paper_id actually exists in research_papers
                if s_paper_id:
                    cur.execute("SELECT id FROM research_papers WHERE id = %s;", (s_paper_id,))
                    if not cur.fetchone():
                        s_paper_id = None

                cur.execute(
                    """
                    INSERT INTO process_steps (
                        route_id, step_number, title, description, required_inputs, conditions, supporting_paper_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (route_id, step_number) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        required_inputs = EXCLUDED.required_inputs,
                        conditions = EXCLUDED.conditions,
                        supporting_paper_id = EXCLUDED.supporting_paper_id;
                    """,
                    (route_id, s_num, s_title, s_desc, s_inputs, s_cond, s_paper_id),
                )

            conn.commit()
            return route_id
    finally:
        release_connection(conn)


def update_route_review_status(
    route_id: int,
    new_status: str,
    reviewer_name: Optional[str] = None,
    edited_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Update review status of a route (e.g. 'human_verified' or 'rejected')."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            is_verified = (new_status == "human_verified")
            if edited_data:
                cur.execute(
                    """
                    UPDATE production_routes SET
                        review_status = %s,
                        reviewed_by_human = %s,
                        reviewed_by = %s,
                        reviewed_at = CURRENT_TIMESTAMP,
                        route_summary = COALESCE(%s, route_summary),
                        applications = COALESCE(%s, applications),
                        advantages = COALESCE(%s, advantages),
                        limitations = COALESCE(%s, limitations)
                    WHERE id = %s;
                    """,
                    (
                        new_status, is_verified, reviewer_name,
                        edited_data.get("route_summary"),
                        edited_data.get("applications"),
                        edited_data.get("advantages"),
                        edited_data.get("limitations"),
                        route_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE production_routes SET
                        review_status = %s,
                        reviewed_by_human = %s,
                        reviewed_by = %s,
                        reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                    """,
                    (new_status, is_verified, reviewer_name, route_id),
                )
            conn.commit()
            return True
    finally:
        release_connection(conn)


def get_routes_by_review_status(status: str = "ai_draft") -> List[Dict[str, Any]]:
    """Retrieve all routes with a specific review status along with their steps and feedstock name."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT r.*, m.name as material_name
                FROM production_routes r
                JOIN raw_materials m ON m.id = r.material_id
                WHERE r.review_status = %s
                ORDER BY r.generated_at DESC NULLS LAST, r.id DESC;
                """,
                (status,),
            )
            routes = cur.fetchall()
            for r in routes:
                cur.execute(
                    """
                    SELECT s.*, p.title as paper_title, p.doi as paper_doi, p.openalex_id
                    FROM process_steps s
                    LEFT JOIN research_papers p ON s.supporting_paper_id = p.id
                    WHERE s.route_id = %s
                    ORDER BY s.step_number ASC;
                    """,
                    (r["id"],),
                )
                r["steps"] = cur.fetchall()
            return routes
    finally:
        release_connection(conn)


def get_feedstock_summary(material_name: str) -> Optional[Dict[str, Any]]:
    """Retrieve cached Category B synthesis summary from Neon if available."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            clean_name = material_name.strip()
            cur.execute(
                """
                SELECT s.*, m.name as material_name
                FROM feedstock_summaries s
                JOIN raw_materials m ON m.id = s.material_id
                WHERE LOWER(m.name) = LOWER(%s)
                   OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(m.aliases, ARRAY[]::text[]))))
                ORDER BY s.updated_at DESC
                LIMIT 1;
                """,
                (clean_name, clean_name),
            )
            return cur.fetchone()
    finally:
        release_connection(conn)


def save_feedstock_summary(
    material_name: str,
    summary_text: str,
    paper_ids: Optional[List[int]] = None,
    model_name: Optional[str] = None,
) -> int:
    """
    Save or update a Category B synthesis summary in Neon.
    Returns the integer primary key summary_id.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            clean_name = material_name.strip()
            cur.execute(
                """
                SELECT id FROM raw_materials 
                WHERE LOWER(name) = LOWER(%s)
                   OR LOWER(%s) = ANY(SELECT LOWER(unnest(COALESCE(aliases, ARRAY[]::text[]))))
                LIMIT 1;
                """,
                (clean_name, clean_name),
            )
            mat_row = cur.fetchone()
            if not mat_row:
                cur.execute(
                    "INSERT INTO raw_materials (name) VALUES (%s) RETURNING id;",
                    (clean_name.lower(),),
                )
                mat_row = cur.fetchone()

            mat_id = mat_row["id"]
            cur.execute(
                """
                INSERT INTO feedstock_summaries (material_id, summary_text, paper_ids, model_name, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (material_id) DO UPDATE SET
                    summary_text = EXCLUDED.summary_text,
                    paper_ids = EXCLUDED.paper_ids,
                    model_name = EXCLUDED.model_name,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (mat_id, summary_text, paper_ids or [], model_name),
            )
            summary_id = cur.fetchone()["id"]
            conn.commit()
            return summary_id
    finally:
        release_connection(conn)

