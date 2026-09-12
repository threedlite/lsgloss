"""Perseus treebank gold and the one definition of "compatible".

Three evaluation scripts (morphacc, tools/quality, tools/diffck) each carried
their own copy of the treebank reader and of the rule for whether a reading
contradicts a gold tag, and a change to the schema had to be made three times.
"""
import re, glob, collections, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import plain
from inflect import fold, postag_morph, parse_reading

CATEGORIAL = ('adv', 'prep', 'conj', 'interj')


def gold_triples(tb_dir):
    """Counter of (folded form, plain lemma, rendered reading) over every
    annotated token in the treebank directory."""
    gold = collections.Counter()
    for fp in glob.glob(str(Path(tb_dir) / '*.xml')):
        with open(fp, encoding='utf-8', errors='ignore') as fh:
            raw = fh.read()
        for w in re.findall(r'<word\b[^>]*/?>', raw):
            f = re.search(r'\bform="([^"]*)"', w); l = re.search(r'\blemma="([^"]*)"', w)
            t = re.search(r'\bpostag="([^"]*)"', w)
            if not (f and l and t and f.group(1) and l.group(1)): continue
            m = postag_morph(t.group(1))
            if not m: continue
            gold[(fold(f.group(1)), plain(re.sub(r'\d+$', '', l.group(1))), m)] += 1
    return gold


def compatible(ours, gold):
    """True when nothing we state contradicts the gold tag.

    A reading that is nothing but a category -- `adv`, `prep`, `conj` -- shares
    no slot with an inflected one, so a naive slot comparison called `adv`
    compatible with `voc s m` and scored a plain disagreement as silence. An
    indeclinable and an inflected form are mutually exclusive readings of the
    same token, so they contradict. `pron` is not in this list: it rides along
    with case and number. The `clitic` slot marks the enclitic half of a joined
    token and says nothing about the reading itself, so it is ignored.

    A gender of `c` (common) is compatible with `m` or `f` by definition."""
    ours = {k: v for k, v in ours.items() if k != 'clitic'}
    gold = {k: v for k, v in gold.items() if k != 'clitic'}
    cat_o = ours.get('category') in CATEGORIAL and len(ours) == 1
    cat_g = gold.get('category') in CATEGORIAL and len(gold) == 1
    if cat_o != cat_g: return False
    if cat_o and cat_g: return ours['category'] == gold['category']
    return all(ours[s] == gold[s] or (s == "gender" and "c" in (ours[s], gold[s]))
               for s in set(ours) & set(gold))


def state(cell, g):
    """How a morphology cell answers a gold reading: absent, blank, exact,
    compatible, or CONTRADICTED."""
    if cell is None: return 'absent'
    if not cell: return 'blank'
    readings = cell.split('|')
    if g in readings: return 'exact'
    gd = parse_reading(g)
    if any(compatible(parse_reading(r), gd) for r in readings): return 'compatible'
    return 'CONTRADICTED'
