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
                   COUNT(r.id) as route_count,
                   COUNT(p.id) as paper_count
            FROM raw_materials m
            LEFT JOIN production_routes r ON r.material_id = m.id
            LEFT JOIN material_papers mp ON mp.material_id = m.id
            LEFT JOIN research_papers p ON p.id = mp.paper_id
            GROUP BY m.id, m.name, m.category
            ORDER BY m.id ASC;
        """)
        materials = cur.fetchall()
        print(f"Total raw_materials: {len(materials)}")
        for m in materials:
            print(f"ID {m['id']}: '{m['name']}' (Cat: {m['category']}) -> {m['route_count']} routes, {m['paper_count']} papers")

        cur.execute("""
            SELECT * FROM production_routes WHERE review_status != 'human_verified' OR reviewed_by_human IS NOT TRUE;
        """)
        non_verified_routes = cur.fetchall()
        print(f"\nNon-verified routes: {len(non_verified_routes)}")
        for r in non_verified_routes:
            print(dict(r))

finally:
    release_connection(conn)

