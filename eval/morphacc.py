"""Accuracy of generated morph_info against Perseus treebank gold tags.

    python3 eval/morphacc.py <package.zip> <treebank dir>

The treebanks are HELD OUT: build the package under test without --treebank, so
every reading it offers came from the paradigm tables or the L&S headword line.
Each annotated token is then a gold (form, lemma, reading) triple.

Two numbers, and the difference between them matters:

  exact         we state the gold reading
  compatible    nothing we state contradicts it, but we say less -- "nom s"
                against a gold "nom s m" is not an error, it is silence about
                gender, and the schema omits a slot it cannot fill
  CONTRADICTED  every reading we offer disagrees with the annotator on some
                slot we both filled. This is the number to drive down; it is
                the only one that means we told a reader something false.

A gender of `c` (common) is compatible with `m` or `f` by definition.
"""
import sys, csv, io, zipfile, collections
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from inflect import parse_reading as parse
from eval.treebank import gold_triples, compatible
ZIP, TB = sys.argv[1], sys.argv[2]

rows = collections.defaultdict(dict)
with zipfile.ZipFile(ZIP) as z:
    for r in csv.DictReader(io.TextIOWrapper(z.open('morphology.csv'), encoding='utf-8')):
        rows[r['word_form']][r['lemma']] = r['morph_info']

gold = gold_triples(TB)

tok = collections.Counter(); cat = collections.Counter()
wrong = collections.Counter(); spread = []
for (form, lemma, g), n in gold.items():
    cands = rows.get(form)
    if not cands:                       tok['form not indexed'] += n; continue
    if lemma not in cands:              tok['lemma not offered'] += n; continue
    cell = cands[lemma]
    if not cell:                        tok['no reading offered'] += n; continue
    readings = cell.split('|')
    spread.append(len(readings))
    gd = parse(g)
    if g in readings:
        tok['exact'] += n
    elif any(compatible(parse(r), gd) for r in readings):
        tok['compatible (we say less)'] += n
    else:
        tok['CONTRADICTED'] += n
        wrong[(g, cell)] += n
        for r in readings:
            rd = parse(r)
            for s in set(rd) & set(gd):
                if rd[s] != gd[s]: cat[f'{s}: we say {rd[s]}, gold {gd[s]}'] += n
            for s in set(gd) - set(rd): cat[f'{s}: we say nothing, gold {gd[s]}'] += n
            break

total = sum(tok.values())
print(f"gold triples: {len(gold):,}   tokens: {total:,}\n")
for k, v in tok.most_common():
    print(f"  {k:<24} {v:>9,}  {100*v/total:5.1f}%")
judged = tok['exact'] + tok['compatible (we say less)'] + tok['CONTRADICTED']
if judged:
    ok = tok['exact'] + tok['compatible (we say less)']
    print(f"\nof {judged:,} tokens we answer: {100*ok/judged:.2f}% not contradicted, {100*tok['exact']/judged:.2f}% exact")
    print(f"mean readings offered per cell: {sum(spread)/len(spread):.2f}")
print("\ntop systematic gaps:")
for k, v in cat.most_common(12): print(f"  {k:<34} {v:>8,}")
print("\nworst individual misses:")
for (g, cell), v in wrong.most_common(12):
    print(f"  {v:>7,}  gold {g!r}\n           ours {cell[:88]!r}")

