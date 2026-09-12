#!/usr/bin/env python3
"""Build the Latin corpus frequency list used to weight QA and repair.

Every quality number in this project is weighted by how often a word actually
occurs in running Latin, not by how many dictionary entries it appears in --
common words have the longest articles, so an entry-sampled score hides exactly
the failures a reader meets most (see README, "frequency-weighted QA").

That weighting needs a frequency list, so this script builds one from the
Perseus canonical Latin corpus. Output is TSV, `form<TAB>count`, descending.

    python3 corpusfreq.py --corpus data-sources/canonical-latinLit \
                          --out out/latin_freq.tsv
"""
import argparse, collections, os, re, sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent))
from common import fold

# Perseus names editions by language: `...-lat1.xml`, `...-lat2.xml`. Anything
# else under the repo is a translation, an English intro, or build metadata --
# counting those would put English words in a Latin frequency list.
LATIN_EDITION = re.compile(r'-lat\d*\.xml$')

# Non-text elements whose contents are editorial, not the work being read.
#
# One regex per tag, and no backreference. The obvious single pattern --
# `<(note|bibl|...)\b.*?</\1>` -- is quadratic here: the backreference stops
# Python from anchoring the search, so every failed start rescans the rest of a
# file. On the 13 MB Livy that took over two minutes; per-tag takes 0.07s.
DROP_TAGS = ('note', 'bibl', 'ref', 'head', 'speaker', 'figure', 'orig', 'del')
DROP = [re.compile(r'<%s\b[^>]*>.*?</%s\s*>' % (t, t), re.S) for t in DROP_TAGS]
TAG  = re.compile(r'<[^>]+>')
# NB not [A-Za-z\u00C0-\u00FF...]: that Latin-1 range contains the multiplication
# and division signs, which then surface as words ('s\u00f7'). Match on letters only.
WORD = re.compile(r'[^\W\d_]+', re.UNICODE)




def main():
    p = argparse.ArgumentParser()
    p.add_argument('--corpus', default='data-sources/canonical-latinLit')
    p.add_argument('--out', default='out/latin_freq.tsv')
    p.add_argument('--min-count', type=int, default=1)
    A = p.parse_args()

    counts, files = collections.Counter(), 0
    for root, _, names in os.walk(A.corpus):
        for n in names:
            if not LATIN_EDITION.search(n):
                continue
            try:
                raw = open(os.path.join(root, n), encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            # the header is one span at the top; cut it by index rather than regex
            h = raw.find('</teiHeader>')
            body = raw[h + 12:] if h >= 0 else raw
            for pat in DROP:
                body = pat.sub(' ', body)
            body = TAG.sub(' ', body)
            # fold() strips non-letters, so a numeral or a bare punctuation
            # token folds to '' -- which then ranks ~63rd as a blank word
            counts.update(f for f in (fold(w) for w in WORD.findall(body)) if f)
            files += 1

    os.makedirs(os.path.dirname(A.out) or '.', exist_ok=True)
    with open(A.out, 'w', encoding='utf-8') as fh:
        for w, c in counts.most_common():
            if c >= A.min_count:
                fh.write(f'{w}\t{c}\n')
    print(f'{files:,} Latin editions -> {sum(counts.values()):,} tokens, '
          f'{len(counts):,} distinct forms -> {A.out}', file=sys.stderr)


if __name__ == '__main__':
    main()
