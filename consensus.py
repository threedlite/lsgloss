#!/usr/bin/env python3
"""Second-judge pass: re-judge rows another judge already scored, and report consensus.

Two independent judges agreeing that a gloss is bad is a far more precise repair
signal than either alone; where they disagree by a wide margin, one of them has a
blind spot and the row needs a human or a third model.

    score.py (judge A) -> scoresA.tsv
    consensus.py --scores scoresA.tsv --below 3     (judge B, whichever is loaded)
        -> consensus.tsv with both scores per row
"""
import sys, argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import (txt, focus, chat, load_entries, load_rows, parse_score,
                    load_ckpt, checkpointed)

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--scores', required=True, help='scores from the first judge')
p.add_argument('--out', default='out/consensus.tsv')
p.add_argument('--ckpt', default='out/consensus_ckpt.jsonl')
p.add_argument('--below', type=int, default=3, help='re-judge rows the first judge scored at or below this')
p.add_argument('--judge', default='judge-terse')
p.add_argument('--maxtok', type=int, default=16)
p.add_argument('--maxchars', type=int, default=800)
p.add_argument('-j', '--jobs', type=int, default=4)
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
A = p.parse_args()

SYS = (ROOT/f'prompts/{A.judge}.txt').read_text(encoding='utf-8').strip()
_u = ROOT/f'prompts/{A.judge}-user.txt'
USR = (_u if _u.exists() else ROOT/'prompts/judge-user.txt').read_text(encoding='utf-8').strip()

def log(s): print(s, file=sys.stderr, flush=True)

ents = load_entries(A.xml)
bodies = [txt(e) for e in ents]
rows = load_rows(A.tsv)
by_key = {r[0]: i for i, r in enumerate(rows)}

first = {}
with open(A.scores, encoding='utf-8') as fh:
    for l in fh:
        if l.startswith('#'): continue
        f = l.rstrip('\n').split('\t')
        if len(f) >= 5 and f[0] in by_key:
            try: first[by_key[f[0]]] = int(f[4])
            except ValueError: pass
targets = sorted(i for i, s in first.items() if s <= A.below)
log(f"{len(first):,} rows scored by first judge | {len(targets):,} at or below {A.below}")

done = {}
for i, d in load_ckpt(A.ckpt).items():
    if i < len(rows) and d.get('s') is not None and d.get('g', rows[i][2]) == rows[i][2]:
        done[i] = d['s']
todo = [i for i in targets if i not in done]
log(f"  {len(done):,} cached, {len(todo):,} to judge")

def judge(i):
    prompt = USR.replace('{ENTRY}', focus(bodies[i])[:A.maxchars]).replace('{GLOSS}', rows[i][2])
    try:
        s = parse_score(chat(A.url, SYS, prompt, max_tokens=A.maxtok))
    except Exception as ex:
        log(f"  entry {i} ({rows[i][1]}): {ex}"); return None
    return None if s is None else {"i": i, "s": s, "g": rows[i][2]}

for d in checkpointed(A.ckpt, todo, judge, jobs=A.jobs, tag='consensus', every=50, log=log):
    done[d['i']] = d['s']

both_bad = disagree = 0
with open(A.out, 'w', encoding='utf-8') as f:
    f.write("# key\theadword\tgloss\tsource\tjudgeA\tjudgeB\tverdict\n")
    for i in targets:
        a = first[i]; b = done.get(i)
        if b is None: v = 'unjudged'
        elif a <= 2 and b <= 2: v = 'both-bad'; both_bad += 1
        elif abs(a - b) >= 3: v = 'disagree'; disagree += 1
        elif b >= 4: v = 'judgeB-ok'
        else: v = 'weak'
        f.write(f"{rows[i][0]}\t{rows[i][1]}\t{rows[i][2]}\t{rows[i][3]}\t{a}\t{b if b is not None else ''}\t{v}\n")
log(f"\nboth-bad {both_bad:,} (high-confidence repair) | disagree {disagree:,} (blind spot) -> {A.out}")
