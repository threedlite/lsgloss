#!/usr/bin/env python3
"""Frequency-weighted quality report.

Scoring a random sample of entries measures the dictionary. It does not measure
what a reader experiences, because word frequency in real Latin is extremely
skewed: the commonest few hundred forms account for a large share of every text,
and those words have the longest, hardest entries. A corpus can score well on a
uniform sample while failing on the words people actually meet -- that is exactly
how the <tr> shortcut passed entry-level QA while glossing `sum` as "nor is she
ashamed".

Reads a form-frequency list built from a Latin corpus and reports coverage and
gloss quality weighted by token frequency, plus the highest-impact failures.
"""
import re, sys, argparse, collections
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parent))
# Match on the same key the package stores forms under: the corpus frequency
# list is i/u-folded, so comparing with a letters-only key silently loses every
# v- and j- word and understates coverage badly.
from common import fold as norm, txt, load_entries, load_rows
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from suspect import reasons, gloss_vocabulary

p = argparse.ArgumentParser()
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--freq', required=True, help='TSV of form<TAB>count, most frequent first')
p.add_argument('--xml', help='dictionary XML, enables the mechanical suspect checks')
p.add_argument('--top', type=int, default=500, help='how many frequent forms to list')
p.add_argument('--out', default='out/freq_targets.tsv')
A = p.parse_args()


rows = load_rows(A.tsv)
vocab = gloss_vocabulary(rows)
idx = collections.defaultdict(list)
for i, r in enumerate(rows):
    k = norm(re.sub(r'\d+$', '', r[0]))
    if k: idx[k].append((i, r))

bodies = None
if A.xml:
    bodies = [txt(e) for e in load_entries(A.xml)]

freq = []
for line in open(A.freq, encoding='utf-8'):
    w, _, n = line.rstrip('\n').partition('\t')
    if n.isdigit(): freq.append((w, int(n)))
total = sum(n for _, n in freq)

covered = glossed = suspect_tok = 0
targets = []
for w, n in freq:
    cands = idx.get(norm(w))
    if not cands: continue
    covered += n
    good = [(i, r) for i, r in cands if r[2].strip()]
    if not good:
        targets.append((n, w, '(no gloss)', 'empty')); continue
    glossed += n
    if bodies:
        flags = set()
        for i, r in good:
            if i < len(bodies): flags |= set(reasons(r[1], r[2], r[3], bodies[i], vocab))
        if flags:
            suspect_tok += n
            targets.append((n, w, ' | '.join(r[2] for _, r in good)[:60], ','.join(sorted(flags))))

print(f"corpus tokens              : {total:,}")
print(f"forms with a dictionary entry: {covered:,} ({covered/total*100:.1f}% of tokens)")
print(f"forms with a gloss           : {glossed:,} ({glossed/total*100:.1f}% of tokens)")
if bodies:
    print(f"tokens whose gloss is flagged: {suspect_tok:,} ({suspect_tok/total*100:.2f}%)")
targets.sort(reverse=True)
with open(A.out, 'w', encoding='utf-8') as f:
    f.write("# freq\tform\tgloss\tflags\n")
    for n, w, g, fl in targets: f.write(f"{n}\t{w}\t{g}\t{fl}\n")
print(f"\nhighest-impact problems (frequency x defect) -> {A.out}")
for n, w, g, fl in targets[:A.top][:25]:
    print(f"  {n:8,}x {w:14} {g[:44]:46} [{fl}]")
