-- Backup and migration script for cleaning up orange peels and test feedstocks
-- Can be rolled back if needed

-- 1. Merge orange peels (ID 53) into orange peel (ID 78)
-- Move papers
INSERT INTO material_papers (material_id, paper_id)
SELECT 78, paper_id
FROM material_papers
WHERE material_id = 53
ON CONFLICT DO NOTHING;

DELETE FROM material_papers WHERE material_id = 53;

-- Add 'orange peels' as alias to ID 78
UPDATE raw_materials
SET aliases = array_append(COALESCE(aliases, ARRAY[]::text[]), 'orange peels')
WHERE id = 78 AND NOT ('orange peels' = ANY(COALESCE(aliases, ARRAY[]::text[])));

-- Delete orphaned orange peels row
DELETE FROM raw_materials WHERE id = 53;

-- 2. Clean up or reject non-relevant test feedstocks
UPDATE production_routes
SET review_status = 'rejected', reviewed_by_human = false
WHERE material_id IN (
    SELECT id FROM raw_materials WHERE name LIKE 'test_feedstock_%'
);

