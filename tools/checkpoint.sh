#!/bin/sh
# Checkpoint: build, measure, record, snapshot the source. Usage: checkpoint.sh <name>
set -e
NAME="$1"
LS=$(cd "$(dirname "$0")/.." && pwd)
CK=${CK:-$LS/out/ckpt}
XML=${XML:?set XML to the L&S TEI file}
TB=${TREEBANK:?set TREEBANK to the Perseus Latin treebank dir}
D="$CK/$NAME"; mkdir -p "$D"
cd "$LS"
cp inflect.py package.py "$D/"
rm -rf "$D/tests"; cp -R tests "$D/tests" 2>/dev/null || true
python3 package.py --xml "$XML" --tsv out/ls_glosses.tsv --scores out/scores_full.tsv \
    --lemma-map out/lemma_map.tsv --treebank "$TB" --freq out/latin_freq.tsv \
    --out "$D/package.zip" > "$D/build.log" 2>&1
python3 package.py --xml "$XML" --tsv out/ls_glosses.tsv --scores out/scores_full.tsv \
    --lemma-map out/lemma_map.tsv --freq out/latin_freq.tsv \
    --out "$D/heldout.zip" >> "$D/build.log" 2>&1
python3 eval/morphacc.py "$D/heldout.zip" "$TB" > "$D/morphacc.txt" 2>&1
python3 -m unittest discover -s tests -t . > "$D/tests.txt" 2>&1 || true
python3 - "$D" "$LS" <<'PY'
import sys, json, zipfile, io, csv, collections, re, hashlib
D, LS = sys.argv[1], sys.argv[2]
sys.path.insert(0, LS)
from inflect import SLOT_ORDER, SLOT_VALUES
freq = {}
for line in open(LS + '/out/latin_freq.tsv', encoding='utf-8'):
    if line.startswith('#'): continue
    f = line.rstrip('\n').split('\t')
    if len(f) >= 2:
        try: freq[f[0]] = int(f[1])
        except ValueError: pass
z = zipfile.ZipFile(D + '/package.zip')
rows = list(csv.DictReader(io.TextIOWrapper(z.open('morphology.csv'), encoding='utf-8')))
forms = {r['word_form'] for r in rows}
vals = collections.Counter(r['morph_info'] for r in rows)
bad = []
for v in set(vals):
    for reading in v.split('|'):
        i = 0
        for t in reading.split():
            while i < len(SLOT_ORDER):
                if t in SLOT_VALUES[SLOT_ORDER[i]]: i += 1; break
                i += 1
            else: bad.append(v); break
m = open(D + '/morphacc.txt').read()
g = lambda p: (re.search(p, m).group(1) if re.search(p, m) else '?')
t = open(D + '/tests.txt').read()
json.dump({
  'rows': len(rows),
  'distinct_morph': len(vals),
  'blank_pct': round(100*vals['']/len(rows), 3),
  'offschema': len(bad),
  'coverage_tokens': sum(n for f, n in freq.items() if f in forms),
  'exact': g(r'exact\s+([\d,]+)'),
  'contradicted': g(r'CONTRADICTED\s+([\d,]+)'),
  'not_contradicted_pct': g(r'([\d.]+)% not contradicted'),
  'tests': re.search(r'Ran (\d+) tests', t).group(1) if 'Ran' in t else '?',
  'tests_ok': 'OK' if re.search(r'\nOK', t) else 'FAIL',
  'sha_morph': hashlib.sha256(z.read('morphology.csv')).hexdigest()[:12],
}, open(D + '/metrics.json', 'w'), indent=1)
print(open(D + '/metrics.json').read())
PY
