"""Detailed quality breakdown of a held-out build against treebank gold.

Separates the four outcomes that matter, and for every wrong reading asks
whether it is a MISSING READING on an ending we already generate -- which is a
free fix, since a cell matches if any of its readings matches -- or something
that needs different data.
"""
from pathlib import Path
import os, sys, re, csv, io, glob, zipfile, collections
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inflect import parse_reading, merge_morph
from eval.treebank import gold_triples, compatible, CATEGORIAL as CAT

ZIP = sys.argv[1]
TB = os.environ.get('TREEBANK', 'data-sources/treebank_data/v2.0/Latin')

cells = collections.defaultdict(dict)
with zipfile.ZipFile(ZIP) as z:
    for r in csv.DictReader(io.TextIOWrapper(z.open('morphology.csv'), encoding='utf-8')):
        # the gold lemma is number-stripped; a minor homograph's own forms ship
        # under its numbered key, so key ours the same way
        _lem = __import__('re').sub(r'\d+$', '', r['lemma'])
        _cell = cells[r['word_form']].get(_lem)
        cells[r['word_form']][_lem] = merge_morph(_cell, r['morph_info']) if _cell else r['morph_info']

gold = gold_triples(TB)

def reading_ok(r, gd):
    return compatible(parse_reading(r), gd)

def classify(cell, g):
    if cell is None: return 'absent'
    if not cell: return 'blank'
    gd = parse_reading(g)
    if g in cell.split('|'): return 'exact'
    if any(reading_ok(r, gd) for r in cell.split('|')): return 'underspecified'
    return 'wrong'

# gold part of speech, from the tag's own first slot
def goldclass(g):
    d = parse_reading(g)
    if d.get('category') in CAT: return 'indeclinable'
    if 'person' in d or 'tense' in d: return 'verb form'
    if 'case' in d: return 'nominal form'
    return 'other'

out = collections.Counter(); byclass = collections.defaultdict(collections.Counter)
wrongpairs = collections.Counter()
for (form, lem, g), n in gold.items():
    st = classify(cells.get(form, {}).get(lem), g)
    out[st] += n
    byclass[goldclass(g)][st] += n
    if st == 'wrong':
        wrongpairs[(cells[form][lem], g)] += n

tot = sum(out.values())
print(f'gold tokens: {tot:,}\n')
print('%-16s %9s %7s' % ('outcome', 'tokens', 'share'))
for k in ('exact', 'underspecified', 'blank', 'absent', 'wrong'):
    print('%-16s %9s %6.1f%%' % (k, format(out[k], ','), 100*out[k]/tot))
answered = out['exact'] + out['underspecified'] + out['wrong']
print(f'\nof {answered:,} answered: {100*out["wrong"]/answered:.2f}% wrong, '
      f'{100*out["exact"]/answered:.2f}% exact')
print('\nby what the gold tag is:')
print('%-15s %9s %8s %7s %7s %7s' % ('', 'exact', 'undersp', 'blank', 'absent', 'wrong'))
for k, c in sorted(byclass.items(), key=lambda kv: -sum(kv[1].values())):
    print('%-15s %9s %8s %7s %7s %7s' % (k, format(c['exact'],','), format(c['underspecified'],','),
          format(c['blank'],','), format(c['absent'],','), format(c['wrong'],',')))

# is the wrong answer a missing reading on a form we already make?
print('\nmost common (ours -> gold) wrong pairs:')
for (ours, g), n in wrongpairs.most_common(20):
    print('  %5s  gold %-24s ours %s' % (format(n,','), g, ours[:52]))
