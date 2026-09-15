#!/usr/bin/env python3
"""Re-apply clean() and enforce() to an existing gloss TSV. No model needed.

lsgloss.py runs this as its `finalise()` step, but only as part of a full run --
and a full run rewrites the whole TSV, discarding the repairs that freqfix made
afterwards. So a fix to the cleaner had no way to reach the shipped data without
either a day of model time or losing work.

This applies exactly the same two functions to the file in place. It is a rule
applied uniformly to every row, not an edit to chosen rows: re-running it on the
same input always gives the same output, and it can never invent text, only trim
what the cleaner already considers non-gloss.

    python3 refinalise.py --tsv out/ls_glosses.tsv [--dry-run]
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_gloss import clean, enforce, strip_unstated_nationality
from namegloss import is_name_entry, name_clean, NAME_MAXWORDS, SOURCE as LS

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--tsv', default='out/ls_glosses.tsv')
ap.add_argument('--xml', help='the dictionary; with it, an ethnic adjective the entry never '
                              'states is dropped too (strip_unstated_nationality)')
ap.add_argument('--out', help='default: rewrite --tsv in place')
ap.add_argument('--maxwords', type=int, default=5)
ap.add_argument('--dry-run', action='store_true', help='report the changes, write nothing')
A = ap.parse_args()

src = Path(A.tsv)
lines = src.read_text(encoding='utf-8').splitlines()
bodies = None
if A.xml:
    from common import load_entries, txt
    bodies = [txt(e) for e in load_entries(A.xml)]
out, changed = [], []
row = -1                                   # the TSV is positional: row i is entry i
for line in lines:
    if line.startswith('#'):
        out.append(line); continue
    row += 1
    f = line.split('\t')
    if len(f) < 4 or not f[2].strip():
        out.append(line); continue
    cap = NAME_MAXWORDS if is_name_entry(f[1]) else A.maxwords
    if f[3].rstrip('~?!') == LS:
        new = name_clean(f[2], cap, f[1])
    else:
        new = clean(f[2], cap)
        if bodies is not None and row < len(bodies):
            new = strip_unstated_nationality(new, bodies[row], f[3])
    new = enforce(new, cap)
    if new != f[2]:
        changed.append((f[0], f[2], new))
        f[2] = new
    out.append('\t'.join(f))

for k, o, n in changed:
    print(f"  {k:16} {o!r}  ->  {n!r}", file=sys.stderr)
print(f"{len(changed):,} of {len(lines):,} rows changed", file=sys.stderr)

if A.dry_run:
    sys.exit(0)
dst = Path(A.out or A.tsv)
dst.write_text('\n'.join(out) + '\n', encoding='utf-8')
print(f"-> {dst}", file=sys.stderr)
