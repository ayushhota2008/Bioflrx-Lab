import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.database_service import get_connection, release_connection
from psycopg2.extras import RealDictCursor

conn = get_connection()
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check counts before
        cur.execute("SELECT COUNT(*) as count FROM raw_materials;")
        mat_before = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM production_routes;")
        route_before = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM process_steps;")
        step_before = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM material_papers;")
        mp_before = cur.fetchone()["count"]

        print(f"BEFORE: {mat_before} materials, {route_before} routes, {step_before} steps, {mp_before} paper links")

        # 1. Merge 'orange peels' (ID 53) into canonical 'orange peel' (ID 78)
        cur.execute("""
            INSERT INTO material_papers (material_id, paper_id)
            SELECT 78, paper_id
            FROM material_papers
            WHERE material_id = 53
            ON CONFLICT DO NOTHING;
        """)
        cur.execute("DELETE FROM material_papers WHERE material_id = 53;")
        cur.execute("""
            UPDATE raw_materials
            SET aliases = array_append(COALESCE(aliases, ARRAY[]::text[]), 'orange peels')
            WHERE id = 78 AND NOT ('orange peels' = ANY(COALESCE(aliases, ARRAY[]::text[])));
        """)
        cur.execute("DELETE FROM raw_materials WHERE id = 53;")

        # 2. Remove non-relevant synthetic test feedstocks left by integration tests
        cur.execute("""
            DELETE FROM process_steps
            WHERE route_id IN (
                SELECT r.id FROM production_routes r
                JOIN raw_materials m ON m.id = r.material_id
                WHERE m.name LIKE 'test_feedstock_%'
            );
        """)
        cur.execute("""
            DELETE FROM production_routes
            WHERE material_id IN (
                SELECT id FROM raw_materials WHERE name LIKE 'test_feedstock_%'
            );
        """)
        cur.execute("""
            DELETE FROM raw_materials
            WHERE name LIKE 'test_feedstock_%';
        """)

        conn.commit()
        print("Transaction COMMITTED successfully.")

        # Check counts after
        cur.execute("SELECT COUNT(*) as count FROM raw_materials;")
        mat_after = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM production_routes;")
        route_after = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM process_steps;")
        step_after = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM material_papers;")
        mp_after = cur.fetchone()["count"]

        print(f"AFTER: {mat_after} materials, {route_after} routes, {step_after} steps, {mp_after} paper links")

        # Check remaining materials
        cur.execute("SELECT id, name, category, aliases FROM raw_materials ORDER BY id ASC;")
        remaining = cur.fetchall()
        print(f"\nRemaining {len(remaining)} materials:")
        for r in remaining:
            print(f"  ID {r['id']}: '{r['name']}' (Aliases: {r['aliases']})")

except Exception as e:
    conn.rollback()
    print(f"Error executing transaction: {e}")
    raise
finally:
    release_connection(conn)

