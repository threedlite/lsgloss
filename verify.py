#!/usr/bin/env python3
"""Verify repaired glosses with a DIFFERENT model than the one that wrote them, and
revert any that got worse.

refine.py re-scores its own replacement with the model that produced it, which is
the correlated error a second model exists to remove. This runs after a repair
pass, with the other model loaded: it scores each changed row, compares against
that row's score before the repair, and reverts regressions.

    --before  a consensus/scores file holding the pre-repair gloss and its score
"""
import sys, argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import (txt, focus, chat, load_entries, load_rows, XrefIndex, parse_score,
                    load_ckpt, checkpointed)

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--before', required=True, help='file with pre-repair gloss (col 3), its source (col 4) and its score')
p.add_argument('--score-col', type=int, default=5, help='1-based column holding the pre-repair score')
p.add_argument('--out', default='out/ls_glosses.tsv')
p.add_argument('--ckpt', default='out/verify_ckpt.jsonl')
p.add_argument('--keep-min', type=int, default=4,
               help='keep a replacement only if the independent judge scores it at least this; '
                    'comparing only against a pre-repair score is weak when that score was already low')
p.add_argument('--judge', default='judge-terse'); p.add_argument('--maxtok', type=int, default=16)
p.add_argument('--maxchars', type=int, default=800); p.add_argument('-j','--jobs', type=int, default=4)
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
A = p.parse_args()

SYS = (ROOT/f'prompts/{A.judge}.txt').read_text(encoding='utf-8').strip()
_u = ROOT/f'prompts/{A.judge}-user.txt'
USR = (_u if _u.exists() else ROOT/'prompts/judge-user.txt').read_text(encoding='utf-8').strip()

def log(s): print(s, file=sys.stderr, flush=True)

ents = load_entries(A.xml)
bodies = [txt(e) for e in ents]
rows = load_rows(A.tsv)
idx = {r[0]: i for i, r in enumerate(rows)}
xrefs = XrefIndex(rows, bodies)

before = {}
with open(A.before, encoding='utf-8') as fh:
    for l in fh:
        if l.startswith('#'): continue
        f = l.rstrip('\n').split('\t')
        if len(f) > A.score_col-1 and f[0] in idx:
            try: before[idx[f[0]]] = (f[2], f[3] if len(f) > 3 else None, int(f[A.score_col-1]))
            except ValueError: pass
changed = [i for i, (g, _s, _) in before.items() if rows[i][2] != g]
log(f"{len(before):,} rows in before-file | {len(changed):,} changed by the repair pass")

# keyed by the gloss judged, so a row repaired again since is re-judged
done = {}
for i, d in load_ckpt(A.ckpt).items():
    if i < len(rows) and d.get('s') is not None and d.get('g', rows[i][2]) == rows[i][2]:
        done[i] = d['s']
todo = [i for i in changed if i not in done]

def entry_for_judging(i):
    """A cross-reference stub defines nothing; show the judge the target too."""
    base = focus(bodies[i])[:A.maxchars]
    if not rows[i][3].startswith('xref'):
        return base
    j = xrefs.target_of(i)
    if j is None: return base
    return base + "\n\nIT CROSS-REFERENCES THIS ENTRY:\n" + focus(bodies[j])[:A.maxchars]

def judge(i):
    prompt = USR.replace('{ENTRY}', entry_for_judging(i)).replace('{GLOSS}', rows[i][2])
    try:
        s = parse_score(chat(A.url, SYS, prompt, max_tokens=A.maxtok))
    except Exception as ex:
        log(f"  entry {i} ({rows[i][1]}): {ex}"); return None
    return None if s is None else {"i": i, "s": s, "g": rows[i][2]}

for d in checkpointed(A.ckpt, todo, judge, jobs=A.jobs, tag='verify', every=50, log=log):
    done[d['i']] = d['s']

kept = reverted = flagged = 0
for i in changed:
    old_gloss, old_source, old_score = before[i]
    new_score = done.get(i)
    if new_score is None: continue
    if new_score >= A.keep_min:
        kept += 1
    elif new_score < old_score:
        # revert the provenance with the text: a reverted row is not a repair
        rows[i][2] = old_gloss
        if old_source: rows[i][3] = old_source
        reverted += 1
    else:
        if not rows[i][3].endswith('!'): rows[i][3] += '!'
        flagged += 1
with open(A.out, 'w', encoding='utf-8') as f:
    f.write("# columns\tkey\theadword\tgloss\tsource\n")
    for r in rows: f.write('\t'.join(r)+'\n')
log(f"\nverified by the other model: kept {kept:,}, reverted {reverted:,}, unresolved {flagged:,} -> {A.out}")
