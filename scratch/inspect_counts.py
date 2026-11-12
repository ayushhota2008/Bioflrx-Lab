import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.database_service import get_connection, release_connection
from psycopg2.extras import RealDictCursor

conn = get_connection()
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT m.id, m.name, m.category,
                   COUNT(DISTINCT r.id) as route_count,
                   COUNT(DISTINCT mp.paper_id) as paper_count
            FROM raw_materials m
            LEFT JOIN production_routes r ON r.material_id = m.id
            LEFT JOIN material_papers mp ON mp.material_id = m.id
            GROUP BY m.id, m.name, m.category
            ORDER BY m.id ASC;
        """)
        materials = cur.fetchall()
        print(f"Total raw_materials: {len(materials)}")
        for m in materials:
            print(f"ID {m['id']}: '{m['name']}' -> {m['route_count']} routes, {m['paper_count']} papers")

        print("\nAll routes detail:")
        cur.execute("""
            SELECT r.id, r.material_id, m.name as mat_name, r.product_name, r.review_status, r.reviewed_by_human, r.generated_by
            FROM production_routes r
            JOIN raw_materials m ON m.id = r.material_id
            ORDER BY r.id ASC;
        """)
        routes = cur.fetchall()
        for r in routes:
            print(dict(r))

finally:
    release_connection(conn)

