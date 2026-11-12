import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.openalex_service import search_papers_multi_query
from services.feedstock_service import check_feedstock_canonical
from services.database_service import get_routes_for_material
from services.gemini_service import check_canonical_material_name

print("--- 1. Testing Non-Renewable Fast Path ---")
t0 = time.time()
res_sand = check_feedstock_canonical("sand")
t1 = time.time()
print(f"check_feedstock_canonical('sand'): {res_sand['action']} in {(t1 - t0)*1000:.2f}ms")

print("\n--- 2. Testing Route Step Batch Fetching ---")
t0 = time.time()
routes = get_routes_for_material("sugarcane")
t1 = time.time()
print(f"get_routes_for_material('sugarcane'): {len(routes)} routes with {sum(len(r.get('steps', [])) for r in routes)} steps in {(t1 - t0)*1000:.2f}ms")

print("\n--- 3. Testing Parallel OpenAlex Search ---")
t0 = time.time()
oa_res = search_papers_multi_query("hemp fiber", per_query=5)
t1 = time.time()
print(f"search_papers_multi_query('hemp fiber'): {len(oa_res.get('papers', []))} papers in {(t1 - t0):.2f}s")

print("\n--- 4. Testing Canonical Check Cache ---")
t0 = time.time()
c1 = check_canonical_material_name("corn strach")
t1 = time.time()
print(f"First check_canonical_material_name('corn strach'): {c1.get('canonical_name')} in {(t1 - t0):.2f}s")

t0 = time.time()
c2 = check_canonical_material_name("corn strach")
t1 = time.time()
print(f"Repeated check_canonical_material_name('corn strach') (cached): {c2.get('canonical_name')} in {(t1 - t0)*1000:.2f}ms")
