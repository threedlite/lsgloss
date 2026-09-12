"""Which gold tokens got worse between two checkpoints."""
from pathlib import Path
import os, sys, re, csv, io, glob, zipfile, collections
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval.treebank import gold_triples, state
CK = os.environ.get('CK', 'out/ckpt') + '/'
A, B = sys.argv[1], sys.argv[2]
def load(n):
    with zipfile.ZipFile(CK + n + '/heldout.zip') as z:
        d = collections.defaultdict(dict)
        for r in csv.DictReader(io.TextIOWrapper(z.open('morphology.csv'), encoding='utf-8')):
            d[r['word_form']][r['lemma']] = r['morph_info']
    return d
a, b = load(A), load(B)
gold = gold_triples(os.environ.get('TREEBANK', 'data-sources/treebank_data/v2.0/Latin'))
worse = collections.Counter(); better = collections.Counter(); ex = collections.defaultdict(list)
for (form, lem, g), n in gold.items():
    sa = state(a.get(form, {}).get(lem), g); sb = state(b.get(form, {}).get(lem), g)
    if sa == sb: continue
    if sb == 'CONTRADICTED' and sa != 'CONTRADICTED':
        worse[(sa, sb)] += n
        if len(ex['worse']) < 12:
            ex['worse'].append((n, form, lem, g, a.get(form, {}).get(lem), b.get(form, {}).get(lem)))
    elif sa == 'CONTRADICTED' and sb != 'CONTRADICTED':
        better[(sa, sb)] += n
print(f'{A} -> {B}')
print('  became contradicted:', sum(worse.values()), dict(worse))
print('  stopped being contradicted:', sum(better.values()), dict(better))
print()
for n, form, lem, g, av, bv in sorted(ex['worse'], reverse=True):
    print(f'  {n:>4}  {form:<12} {lem:<12} gold={g}')
    print(f'        was={av!r}\n        now={bv!r}')
