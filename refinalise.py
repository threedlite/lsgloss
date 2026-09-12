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
from clean_gloss import clean, enforce

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--tsv', default='out/ls_glosses.tsv')
ap.add_argument('--out', help='default: rewrite --tsv in place')
ap.add_argument('--maxwords', type=int, default=5)
ap.add_argument('--dry-run', action='store_true', help='report the changes, write nothing')
A = ap.parse_args()

src = Path(A.tsv)
lines = src.read_text(encoding='utf-8').splitlines()
out, changed = [], []
for line in lines:
    if line.startswith('#'):
        out.append(line); continue
    f = line.split('\t')
    if len(f) < 4 or not f[2].strip():
        out.append(line); continue
    new = enforce(clean(f[2], A.maxwords), A.maxwords)
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
