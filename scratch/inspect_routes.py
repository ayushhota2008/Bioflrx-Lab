import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.database_service import get_connection, release_connection

from psycopg2.extras import RealDictCursor

conn = get_connection()
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check columns of production_routes
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'production_routes';
        """)
        cols = cur.fetchall()
        print("Columns in production_routes:")
        for c in cols:
            print(f"  {c['column_name']} ({c['data_type']})")

        print("\nAll production_routes:")
        cur.execute("""
            SELECT r.*, m.name as material_name
            FROM production_routes r
            JOIN raw_materials m ON m.id = r.material_id
            ORDER BY r.id ASC;
        """)
        routes = cur.fetchall()
        print(f"Total routes found: {len(routes)}")
        for r in routes:
            print(f"ID {r['id']}: Material: '{r['material_name']}' | Name: '{r.get('route_name')}' | Status: '{r.get('review_status')}' | ReviewedByHuman: {r.get('reviewed_by_human')} | GeneratedBy: {r.get('generated_by')}")
finally:
    release_connection(conn)
