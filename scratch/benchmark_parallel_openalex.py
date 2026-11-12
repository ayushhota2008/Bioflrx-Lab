import time
import requests
from concurrent.futures import ThreadPoolExecutor

url = 'https://api.openalex.org/works'
headers = {'User-Agent': 'BioFlexLab/1.0 (mailto:student@example.com)'}
t1 = '"wheat straw" (bioplastic OR "biodegradable plastic" OR biopolymer)'
t2 = '"wheat straw" (thermoplastic OR "starch film" OR "bio-film" OR "biocomposite" OR plasticizer)'

s = requests.Session()

# 1. Sequential fetch
t0 = time.time()
r1 = s.get(url, params={'search': t1, 'per_page': 10}, headers=headers, timeout=12)
r2 = s.get(url, params={'search': t2, 'per_page': 10}, headers=headers, timeout=12)
t_seq = time.time() - t0
print(f'Sequential fetch: {t_seq:.3f}s')

# 2. Parallel fetch
t0 = time.time()
with ThreadPoolExecutor(max_workers=2) as ex:
    f1 = ex.submit(s.get, url, params={'search': t1, 'per_page': 10}, headers=headers, timeout=12)
    f2 = ex.submit(s.get, url, params={'search': t2, 'per_page': 10}, headers=headers, timeout=12)
    res1 = f1.result()
    res2 = f2.result()
t_par = time.time() - t0
print(f'Parallel fetch: {t_par:.3f}s (Speedup: {t_seq / t_par:.2f}x)')

