import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.database_service import get_connection, release_connection
from psycopg2.extras import RealDictCursor

conn = get_connection()
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                m.id as material_id,
                m.name as material_name,
                m.category,
                r.id as route_id,
                r.product_name,
                r.review_status,
                r.reviewed_by_human,
                r.generated_by,
                COUNT(DISTINCT s.id) as step_count,
                COUNT(DISTINCT mp.paper_id) as paper_count
            FROM raw_materials m
            LEFT JOIN production_routes r ON r.material_id = m.id
            LEFT JOIN process_steps s ON s.route_id = r.id
            LEFT JOIN material_papers mp ON mp.material_id = m.id
            GROUP BY m.id, m.name, m.category, r.id, r.product_name, r.review_status, r.reviewed_by_human, r.generated_by
            ORDER BY m.id ASC;
        """)
        rows = cur.fetchall()
        for row in rows:
            is_test = row['material_name'].startswith('test_')
            print(f"[{'TEST' if is_test else 'REAL'}] Mat #{row['material_id']}: '{row['material_name']}' | Route #{row['route_id']}: '{row['product_name']}' | Status: '{row['review_status']}' | Human: {row['reviewed_by_human']} | Steps: {row['step_count']} | Papers: {row['paper_count']}")
finally:
    release_connection(conn)

