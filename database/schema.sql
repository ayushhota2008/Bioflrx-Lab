-- BioFlex Lab Database Schema
-- Compatible with Neon PostgreSQL (Standard relational tables)

-- 1. Raw Materials Table
CREATE TABLE IF NOT EXISTS raw_materials (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    category VARCHAR(100) DEFAULT 'Agricultural Feedstock',
    description TEXT,
    key_components TEXT,
    aliases TEXT[] DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Research Papers Table
CREATE TABLE IF NOT EXISTS research_papers (
    id SERIAL PRIMARY KEY,
    openalex_id VARCHAR(255) UNIQUE NOT NULL,
    doi VARCHAR(255) UNIQUE,
    title TEXT NOT NULL,
    authors TEXT[] DEFAULT '{}',
    publication_year INTEGER,
    abstract TEXT,
    landing_page_url TEXT,
    open_access_url TEXT,
    relevance_status VARCHAR(50) DEFAULT 'Potentially Relevant',
    relevance_score INTEGER DEFAULT 0,
    citation_count INTEGER DEFAULT 0,
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Junction Table: Material to Papers
CREATE TABLE IF NOT EXISTS material_papers (
    material_id INTEGER REFERENCES raw_materials(id) ON DELETE CASCADE,
    paper_id INTEGER REFERENCES research_papers(id) ON DELETE CASCADE,
    relevance_notes TEXT,
    PRIMARY KEY (material_id, paper_id)
);

-- 4. Production Routes Table
CREATE TABLE IF NOT EXISTS production_routes (
    id SERIAL PRIMARY KEY,
    material_id INTEGER REFERENCES raw_materials(id) ON DELETE CASCADE,
    product_name VARCHAR(255) NOT NULL,
    route_summary TEXT NOT NULL,
    route_type VARCHAR(100) NOT NULL,
    evidence_level VARCHAR(50) NOT NULL,
    limitations TEXT,
    applications TEXT,
    advantages TEXT,
    environmental_notes TEXT,
    reviewed_by_human BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_material_product UNIQUE (material_id, product_name)
);

-- Migration for existing tables if columns missing
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS applications TEXT;
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS advantages TEXT;
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS environmental_notes TEXT;
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS review_status VARCHAR(50) DEFAULT 'human_verified';
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS generated_by VARCHAR(50) DEFAULT 'human';
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS model_name VARCHAR(100);
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS generated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(255);
ALTER TABLE production_routes ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE;

-- 5. Process Steps Table
CREATE TABLE IF NOT EXISTS process_steps (
    id SERIAL PRIMARY KEY,
    route_id INTEGER REFERENCES production_routes(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    required_inputs TEXT,
    conditions TEXT,
    supporting_paper_id INTEGER REFERENCES research_papers(id) ON DELETE SET NULL,
    CONSTRAINT unique_step_per_route UNIQUE (route_id, step_number)
);

-- 6. Feedstock Summaries Table (Persistent Category B Literature Synthesis Cache)
CREATE TABLE IF NOT EXISTS feedstock_summaries (
    id SERIAL PRIMARY KEY,
    material_id INTEGER REFERENCES raw_materials(id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL,
    paper_ids INTEGER[] DEFAULT '{}',
    model_name VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_material_summary UNIQUE (material_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_papers_openalex ON research_papers(openalex_id);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON research_papers(doi);
CREATE INDEX IF NOT EXISTS idx_material_papers_mat ON material_papers(material_id);
CREATE INDEX IF NOT EXISTS idx_production_routes_mat ON production_routes(material_id);
CREATE INDEX IF NOT EXISTS idx_production_routes_review_status ON production_routes(review_status);
CREATE INDEX IF NOT EXISTS idx_process_steps_route ON process_steps(route_id);
CREATE INDEX IF NOT EXISTS idx_feedstock_summaries_mat ON feedstock_summaries(material_id);
