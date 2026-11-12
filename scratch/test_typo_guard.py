import difflib

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            # Note: handle transposition or standard substitution
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

# Damerau-Levenshtein distance (accounts for transpositions like hsuk <-> husk as 1 edit!)
def damerau_levenshtein(s1: str, s2: str) -> int:
    d = {}
    len1 = len(s1)
    len2 = len(s2)
    for i in range(-1, len1 + 1):
        d[(i, -1)] = i + 1
    for j in range(-1, len2 + 1):
        d[(-1, j)] = j + 1

    for i in range(len1):
        for j in range(len2):
            cost = 0 if s1[i] == s2[j] else 1
            d[(i, j)] = min(
                d[(i - 1, j)] + 1,        # deletion
                d[(i, j - 1)] + 1,        # insertion
                d[(i - 1, j - 1)] + cost,  # substitution
            )
            if i > 0 and j > 0 and s1[i] == s2[j - 1] and s1[i - 1] == s2[j]:
                d[(i, j)] = min(d[(i, j)], d[(i - 2, j - 2)] + cost) # transposition

    return d[(len1 - 1, len2 - 1)]

def is_likely_typo(query: str, target: str, min_ratio: float = 0.82) -> bool:
    q = query.strip().lower()
    t = target.strip().lower()
    if q == t:
        return False

    # 1. Overall sequence similarity check
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    if ratio < min_ratio:
        return False

    # 2. Maximum absolute edit distance guard
    max_len = max(len(q), len(t))
    total_dist = damerau_levenshtein(q, t)
    # Allow at most 1 edit for <= 5 chars, 2 edits for <= 14 chars, 3 for longer
    allowed_edits = 1 if max_len <= 5 else (2 if max_len <= 14 else 3)
    if total_dist > allowed_edits:
        return False

    # 3. Word-level token guard for multi-word phrases
    q_words = q.split()
    t_words = t.split()
    if len(q_words) == len(t_words) and len(q_words) > 1:
        for qw, tw in zip(q_words, t_words):
            if qw == tw:
                continue
            w_dist = damerau_levenshtein(qw, tw)
            w_ratio = difflib.SequenceMatcher(None, qw, tw).ratio()
            # If word is short (<= 4 chars), at most 1 edit allowed (e.g. hsuk vs husk is 1 transposition edit)
            max_w_edits = 1 if max(len(qw), len(tw)) <= 4 else 2
            if w_dist > max_w_edits or w_ratio < 0.70:
                return False

    return True

test_cases = [
    ('corn starch', 'cane starch', False),
    ('potato starch', 'pea starch', False),
    ('wheat straw', 'oat straw', False),
    ('rice husk', 'rice straw', False),
    ('corn stach', 'corn starch', True),
    ('rice hsuk', 'rice husk', True),
    ('potato strach', 'potato starch', True),
    ('baggasse', 'bagasse', True),
    ('sugarcne', 'sugarcane', True),
    ('banana pel', 'banana peel', True),
]

all_correct = True
for q, t, expected in test_cases:
    res = is_likely_typo(q, t)
    status = 'PASS' if res == expected else 'FAIL'
    if res != expected:
        all_correct = False
    print(f'[{status}] "{q}" vs "{t}" -> {res} (expected {expected})')

print('ALL CORRECT:', all_correct)

