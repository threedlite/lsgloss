#!/usr/bin/env python3
"""QA summary of the gloss output: coverage, length, and suspicious rows."""
import re, sys, random, collections
path = sys.argv[1] if len(sys.argv) > 1 else 'out/ls_glosses.tsv'
rows = []
for line in open(path, encoding='utf-8'):
    if line.startswith('#'): continue
    p = line.rstrip('\n').split('\t')
    if len(p) >= 4: rows.append(p)
n = len(rows)
src = collections.Counter(r[3].split('->')[0] for r in rows)
print(f"=== {path}\nrows {n:,}\n")
print("source mix:")
for k, v in src.most_common(): print(f"  {k:18} {v:7,}  ({v/n*100:5.1f}%)")

wc = collections.Counter(len(r[2].split()) for r in rows)
print("\ngloss length (words):")
for k in sorted(wc):
    bar = '#' * int(wc[k]/n*60)
    print(f"  {k:2}{'+' if k>=11 else ' '} {wc[k]:7,} ({wc[k]/n*100:5.1f}%) {bar}")

LATIN = re.compile(r'\b(?:ae|ii|us|um|is|ōnis|ăre|ĕre|īre)\b', re.I)
issues = collections.defaultdict(list)
for r in rows:
    g = r[2]
    if not g.strip():                      issues['empty'].append(r)
    elif g.startswith('ERROR'):            issues['error'].append(r)
    elif g == 'XREF':                      issues['xref-literal'].append(r)
    elif len(g.split()) > 8:               issues['too long'].append(r)
    elif re.search(r'\(note|the user|instruction', g, re.I): issues['leaked reasoning'].append(r)
    elif re.search(r'[Ͱ-Ͽ]', g):  issues['greek in gloss'].append(r)
print("\nissues:")
if not issues: print("  none")
for k, v in sorted(issues.items(), key=lambda x: -len(x[1])):
    print(f"  {k:18} {len(v):6,} ({len(v)/n*100:.2f}%)")
    for r in v[:3]: print(f"      {r[1]:22} {r[2][:70]!r}")

random.seed(0)
print("\nrandom sample:")
for r in random.sample(rows, min(25, n)):
    print(f"  {r[1]:24} {r[2][:58]:60} [{r[3][:18]}]")
