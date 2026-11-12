import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.database_service import get_connection, release_connection
from psycopg2.extras import RealDictCursor

conn = get_connection()
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, aliases, category
            FROM raw_materials
            WHERE id IN (53, 78);
        """)
        rows = cur.fetchall()
        for r in rows:
            print(dict(r))
finally:
    release_connection(conn)

