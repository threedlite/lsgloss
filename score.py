#!/usr/bin/env python3
"""Score the generated glosses against their dictionary entries, 0-5.

The judge is the same model that wrote the glosses, but it grades a candidate
against source text it is shown, with no indication of the gloss's provenance --
verification, not preference -- so the self-preference effect reported for
comparative LLM judging does not apply. Observed behaviour bears this out: the
judge marks the pipeline's own headword-echo glosses 0.

The limitation that does apply is correlated error: one model, so a construction
misread during glossing may be misread the same way during judging. Hence the
cross-check against ground.py, which is model-independent -- if the judge stops
separating grounded from ungrounded glosses, it has stopped measuring anything.
"""
import sys, random, argparse, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import (txt, focus, chat, load_entries, load_rows, XrefIndex, parse_score,
                    load_ckpt, checkpointed)
from ground import score as ground_score

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--ckpt', default='out/score_ckpt.jsonl')
p.add_argument('--out', default='out/scores.tsv')
p.add_argument('-n', '--sample', type=int, default=2000, help='0 = score everything')
p.add_argument('-j', '--jobs', type=int, default=4)
p.add_argument('--seed', type=int, default=0, help='sample seed; fixed so runs are comparable')
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
p.add_argument('--maxchars', type=int, default=800)
p.add_argument('--judge', default='judge-system', help="prompt pair in prompts/: 'judge-system' (rubric, for gpt-oss) "
                                                       "or 'judge-terse' (one digit, for Gemma/Glimmer with reasoning off)")
p.add_argument('--maxtok', type=int, default=32)
p.add_argument('--offline', action='store_true', help='no model calls; rewrite the scores file from the checkpoint')
A = p.parse_args()

SYS = (ROOT/f'prompts/{A.judge}.txt').read_text(encoding='utf-8').strip()
_u = ROOT/f'prompts/{A.judge}-user.txt'
USR = (_u if _u.exists() else ROOT/'prompts/judge-user.txt').read_text(encoding='utf-8').strip()

def log(s): print(s, file=sys.stderr, flush=True)

ents = load_entries(A.xml)
bodies = [txt(e) for e in ents]
rows = load_rows(A.tsv)
assert len(rows) == len(ents), f"row/entry mismatch {len(rows)} vs {len(ents)}"
xrefs = XrefIndex(rows, bodies)

# A cross-reference entry ("asperiter, adv., v. asper") contains no definition of
# its own -- its gloss legitimately comes from the target. Judging it against the
# stub makes every correct gloss look unsupported, so follow the reference and
# show the judge the target entry too.
def entry_for_judging(i):
    """The entry text a gloss should be judged against, following a cross-reference."""
    base = focus(bodies[i])[:A.maxchars]
    if not rows[i][3].startswith('xref'):
        return base
    j = xrefs.target_of(i)
    if j is None: return base
    return base + "\n\nIT CROSS-REFERENCES THIS ENTRY:\n" + focus(bodies[j])[:A.maxchars]

# Sample over ALL row indices, not just the ones that currently have a gloss:
# the glossed set changes between runs, so sampling from it would select
# different rows each time and make before/after comparisons meaningless.
if A.sample and A.sample < len(rows):
    random.seed(A.seed)
    picked = sorted(random.sample(range(len(rows)), min(len(rows), int(A.sample * 1.15))))
    pool = [i for i in picked if rows[i][2].strip()][:A.sample]
else:
    pool = [i for i, r in enumerate(rows) if r[2].strip()]
log(f"scoring {len(pool):,} glosses (of {len(rows):,} rows, {len(rows)-len([r for r in rows if r[2].strip()]):,} empty)")

# A score is a fact about one gloss. The checkpoint records the gloss it judged,
# and a record for a row whose gloss has since changed is stale and re-judged --
# otherwise a resume after a repair pass returned the pre-repair score.
done = {}
for i, d in load_ckpt(A.ckpt).items():
    if i < len(rows) and d.get('s') is not None and d.get('g', rows[i][2]) == rows[i][2]:
        done[i] = d
todo = [] if A.offline else [i for i in pool if i not in done]
log(f"  {len(done):,} cached, {len(todo):,} to do")

def judge(i):
    prompt = USR.replace('{ENTRY}', entry_for_judging(i)).replace('{GLOSS}', rows[i][2])
    try:
        out = chat(A.url, SYS, prompt, max_tokens=A.maxtok)
    except Exception as ex:
        log(f"  entry {i} ({rows[i][1]}): {ex}"); return None
    s = parse_score(out)
    if s is None:
        return None            # unparseable: retry next run rather than record nothing
    # one line: the reason goes into a TSV column and must not carry a newline or tab
    why = ' '.join(out.split())[:60]
    return {"i": i, "s": s, "g": rows[i][2], "why": why}

for d in checkpointed(A.ckpt, todo, judge, jobs=A.jobs, tag='score', log=log):
    done[d['i']] = d

scored = [(i, done[i]['s']) for i in pool if i in done]
dist = collections.Counter(s for _, s in scored)
tot = len(scored)
log(f"\n=== judge scores ({tot:,} glosses, {len(pool)-tot:,} unscored)")
for k in range(5, -1, -1):
    v = dist.get(k, 0)
    log(f"  {k}  {v:6,} ({v/max(1,tot)*100:5.1f}%) {'#'*int(v/max(1,tot)*44)}")
mean = sum(s for _, s in scored)/max(1, tot)
log(f"  mean {mean:.2f} / 5   |   >=4: {sum(1 for _,s in scored if s>=4)/max(1,tot)*100:.1f}%")

# by source, and cross-checked against the mechanical grounding measure
by = collections.defaultdict(list)
for i, s in scored: by[rows[i][3].rstrip('~?')].append(s)
log("\n  mean score by source:")
for k, v in sorted(by.items(), key=lambda x: -len(x[1])):
    if len(v) >= 20: log(f"    {k:16} {sum(v)/len(v):.2f}  (n={len(v):,})")
gs = [(ground_score(rows[i][2], bodies[i]), s) for i, s in scored]
lo = [s for g, s in gs if g == 0.0]; hi = [s for g, s in gs if g == 1.0]
if lo and hi:
    log(f"\n  cross-check vs mechanical grounding:")
    log(f"    ungrounded (grounding 0.0): mean judge score {sum(lo)/len(lo):.2f}  (n={len(lo):,})")
    log(f"    grounded   (grounding 1.0): mean judge score {sum(hi)/len(hi):.2f}  (n={len(hi):,})")

def _cell(s):
    return ' '.join(str(s).split())        # never a tab or newline inside a field

with open(A.out, 'w', encoding='utf-8') as f:
    f.write("# key\theadword\tgloss\tsource\tscore\treason\n")
    for i, s in scored:
        f.write(f"{rows[i][0]}\t{rows[i][1]}\t{_cell(rows[i][2])}\t{rows[i][3]}\t{s}\t{_cell(done[i].get('why', ''))}\n")
log(f"-> {A.out}")
