#!/usr/bin/env python3
"""Re-gloss the rows a scoring pass rated poorly.

Mechanical detectors (suspect.py) catch malformed glosses. They cannot catch a
gloss that is well formed and simply wrong -- "sabucus" glossed as "sambuca
player" when the entry says elder-tree. Those only surface by scoring, so this
closes the loop:

    score.py  ->  scores.tsv  ->  refine.py  ->  updated TSV  ->  score.py

A replacement is accepted only if it beats the original on a re-score, so the
pass cannot make the file worse.
"""
import sys, argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import (txt, focus, chat, load_entries, load_rows, parse_score,
                    load_ckpt, checkpointed)
from clean_gloss import clean, enforce
from suspect import reasons

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--scores', default='out/scores.tsv')
p.add_argument('--out', default='out/ls_glosses.tsv')
p.add_argument('--ckpt', default='out/refine_ckpt.jsonl')
p.add_argument('--max-score', type=int, default=2, help='re-gloss rows scoring at or below this')
p.add_argument('-j', '--jobs', type=int, default=4)
p.add_argument('--effort', default='low')
p.add_argument('--maxwords', type=int, default=5)
p.add_argument('--maxchars', type=int, default=800)
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
A = p.parse_args()

HARD  = (ROOT/'prompts/gloss-hard.txt').read_text(encoding='utf-8').strip()
USR   = (ROOT/'prompts/gloss-user.txt').read_text(encoding='utf-8').strip()
JSYS  = (ROOT/'prompts/judge-system.txt').read_text(encoding='utf-8').strip()
JUSR  = (ROOT/'prompts/judge-user.txt').read_text(encoding='utf-8').strip()

def log(s): print(s, file=sys.stderr, flush=True)

ents   = load_entries(A.xml)
bodies = [txt(e) for e in ents]
rows   = load_rows(A.tsv)
by_key = {r[0]: i for i, r in enumerate(rows)}

low = []
with open(A.scores, encoding='utf-8') as fh:
    for l in fh:
        if l.startswith('#'): continue
        f = l.rstrip('\n').split('\t')
        if len(f) >= 5 and f[0] in by_key:
            try:
                if int(f[4]) <= A.max_score: low.append((by_key[f[0]], int(f[4])))
            except ValueError: pass
log(f"{len(low):,} rows scored <= {A.max_score}")
if not low: sys.exit(0)

def call(system, user, maxtok=96):
    return chat(A.url, system, user, max_tokens=maxtok, effort=A.effort)

def rescore(i, gloss):
    return parse_score(call(JSYS, JUSR.replace('{ENTRY}', focus(bodies[i])[:A.maxchars]).replace('{GLOSS}', gloss), 32))

# a verdict is about the gloss that was in the row when it was judged
done = {}
for i, d in load_ckpt(A.ckpt).items():
    if i < len(rows) and d.get('in', rows[i][2]) == rows[i][2]:
        done[i] = d
todo = [(i, s) for i, s in low if i not in done]
log(f"  {len(done):,} cached, {len(todo):,} to do")

def work(item):
    i, old_score = item
    try:
        g = enforce(clean(call(HARD, USR.replace('{ENTRY}', focus(bodies[i])[:A.maxchars])), A.maxwords), A.maxwords)
        if not g or g.upper() == 'NONE' or g == rows[i][2]:
            return {"i": i, "g": "", "s": old_score, "kept": True, "in": rows[i][2]}
        if reasons(rows[i][1], g, 'model', bodies[i]):        # still malformed
            return {"i": i, "g": "", "s": old_score, "kept": True, "in": rows[i][2]}
        new_score = rescore(i, g)
        if new_score is None:
            return None                                       # judge failed: retry next run
        if new_score > old_score:                             # only accept a genuine gain
            return {"i": i, "g": g, "s": new_score, "kept": False, "in": rows[i][2]}
        return {"i": i, "g": "", "s": old_score, "kept": True, "in": rows[i][2]}
    except Exception as ex:
        log(f"  entry {i} ({rows[i][1]}): {ex}"); return None

for d in checkpointed(A.ckpt, todo, work, jobs=A.jobs, tag='refine', every=100, log=log):
    done[d['i']] = d

improved = 0
for i, _ in low:
    d = done.get(i)
    if d and d.get('g'):
        rows[i][2] = d['g']; rows[i][3] = 'refined'; improved += 1
with open(A.out, 'w', encoding='utf-8') as f:
    f.write("# columns\tkey\theadword\tgloss\tsource\n")
    for r in rows: f.write('\t'.join(r) + '\n')
log(f"\n{improved:,} of {len(low):,} low-scoring rows improved (rest kept: replacement scored no better)")
log(f"-> {A.out}")
