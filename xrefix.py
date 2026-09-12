#!/usr/bin/env python3
"""Repair the two defect classes that need a model rather than a detector.

  1. Cross-references that inherit a gloss across a part-of-speech boundary.
     `vero` is an ADVERB pointing at the ADJECTIVE `verus`, so it inherits "true,
     real, genuine" when it means "in truth, certainly". 1,197 rows, 122,057
     corpus tokens.
  2. Entries left with no gloss at all -- 828 lemmas.

An earlier "adapt" stage tried (1) and measured WORSE than doing nothing (3.91 vs
4.22 on n=981). Two things were wrong with it and both are fixed here:

  * It adapted EVERY cross-reference. Most are same-part-of-speech and already
    correct, so it churned good rows. This one selects on a measured signal --
    the entry's own POS marker differing from its target's.
  * It kept whatever the model returned. This applies the bar verify.py arrived
    at: a replacement is kept only if it clears the mechanical detectors AND an
    independent judging call scores it >= 4 AND it beats the incumbent. Rows that
    fail stay exactly as they were.

    python3 xrefix.py --xml <ls.xml> [--only xref|empty] [--dry-run]

Resumable: every candidate is checkpointed before any row is changed.
"""
import argparse, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import (txt, focus, chat, letters, load_entries, load_rows, XrefIndex,
                    pos_marker, parse_score, xref_target_word, load_ckpt, checkpointed)
from clean_gloss import clean, enforce
from suspect import reasons, gloss_vocabulary

p = argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--out')
p.add_argument('--ckpt', default='out/xrefix_ckpt.jsonl')
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
p.add_argument('--only', choices=('xref', 'empty'), help='restrict to one class')
p.add_argument('--keep-min', type=int, default=4,
               help='absolute bar a replacement must clear. Comparing only against the '
                    'incumbent is too weak when the incumbent is already bad: that is how '
                    "bocas 'sea-fish' became 'box' in an earlier pass.")
p.add_argument('--maxchars', type=int, default=800)
p.add_argument('--maxwords', type=int, default=5)
p.add_argument('--effort', default='low')
p.add_argument('-j', '--jobs', type=int, default=4)
p.add_argument('-n', '--limit', type=int)
p.add_argument('--dry-run', action='store_true')
A = p.parse_args()

ADAPT   = (ROOT/'prompts/gloss-adapt.txt').read_text(encoding='utf-8').strip()
ADAPT_U = (ROOT/'prompts/adapt-user.txt').read_text(encoding='utf-8').strip()
REPAIR  = (ROOT/'prompts/gloss-repair.txt').read_text(encoding='utf-8').strip()
USR     = (ROOT/'prompts/gloss-user.txt').read_text(encoding='utf-8').strip()
JSYS    = (ROOT/'prompts/judge-system.txt').read_text(encoding='utf-8').strip()
JUSR    = (ROOT/'prompts/judge-user.txt').read_text(encoding='utf-8').strip()

def log(s): print(s, file=sys.stderr, flush=True)

ents = load_entries(A.xml)
bodies = [txt(e) for e in ents]

# ------------------------------------------------------- English word check
# Adapting an adverb invites coinage: the model returns "bodilyly", "propheticly",
# "adulously", "muddyly". The adapt prompt forbids it and the model does it anyway.
#
# L&S is itself a large body of English prose -- 183,297 distinct word types in
# its definitions -- so it can serve as the wordlist without adding a dependency
# or a data file. Every real adverb the model produced appears in it (gloriously
# 4, timidly 6, beautifully 11); every coinage appears zero times.
#
# Conservative by construction: a real word L&S happens not to use is rejected
# too, which keeps the incumbent gloss. A missed improvement, never a wrong one.
import collections as _c
ENGLISH = _c.Counter()
for _b in bodies:
    for _w in re.findall(r'[A-Za-z]{3,}', _b):
        ENGLISH[_w.lower()] += 1


def not_english(gloss):
    """The first word of the gloss that appears nowhere in L&S's English, or None."""
    for token in re.findall(r"[A-Za-z][A-Za-z'-]*", gloss):
        for part in re.split(r"[-']", token):
            part = part.lower()
            if len(part) >= 5 and not ENGLISH.get(part):
                return part
    return None

rows = load_rows(A.tsv)
if len(rows) != len(ents):
    sys.exit(f"row/entry mismatch {len(rows)} vs {len(ents)}")

xrefs = XrefIndex(rows, bodies)
target_of = xrefs.target_of


targets = []
for i, r in enumerate(rows):
    if not r[2].strip():
        if A.only in (None, 'empty'):
            targets.append((i, 'empty', None))
        continue
    if A.only in (None, 'xref') and r[3].startswith('xref'):
        j = target_of(i)
        if j is None:
            continue
        a, b = pos_marker(bodies[i]), pos_marker(bodies[j])
        if a and b and a != b:
            targets.append((i, 'pos-mismatch', j))
if A.limit:
    targets = targets[:A.limit]
import collections
print(f"targets: {len(targets):,} "
      + ", ".join(f"{k}={v:,}" for k, v in collections.Counter(t[1] for t in targets).items()),
      file=sys.stderr)
for i, kind, j in targets[:10]:
    print(f"  {kind:12} {rows[i][1][:14]:16} {rows[i][2][:30]!r}"
          + (f" <- {rows[j][1][:12]}" if j is not None else ""), file=sys.stderr)
if A.dry_run or not targets:
    sys.exit(0)

# ------------------------------------------------------------------- the model
def judge(i, gloss, j=None):
    """Score a gloss 0-5 against the entry it should render.

    A cross-reference stub defines nothing, so the target entry is shown too --
    judging against the stub alone marks every correct gloss unsupported, which
    is the bug that made cross-references look like the corpus's worst class."""
    if not gloss:
        return -1
    entry = focus(bodies[i])[:A.maxchars]
    if j is not None:
        entry += "\n\nIT CROSS-REFERENCES THIS ENTRY:\n" + focus(bodies[j])[:A.maxchars]
    try:
        s = parse_score(chat(A.url, JSYS, JUSR.replace('{ENTRY}', entry).replace('{GLOSS}', gloss),
                             max_tokens=32, effort=A.effort))
        return -1 if s is None else s
    except Exception:
        return -1


def propose(item):
    i, kind, j = item
    try:
        if kind == 'pos-mismatch':
            prompt = (ADAPT_U.replace('{HEAD}', rows[i][1])
                             .replace('{ENTRY}', focus(bodies[i])[:400])
                             .replace('{TARGET}', rows[i][2]))
            out = chat(A.url, ADAPT, prompt, max_tokens=64, effort=A.effort)
        else:
            out = chat(A.url, REPAIR, USR.replace('{ENTRY}', focus(bodies[i])[:A.maxchars]),
                       max_tokens=96, effort=A.effort)
        return {"i": i, "g": enforce(clean(out, A.maxwords), A.maxwords)}
    except Exception as ex:
        log(f"  entry {i} ({rows[i][1]}): {ex}"); return None     # retried next run


done = {i: d['g'] for i, d in load_ckpt(A.ckpt).items()}
todo = [t for t in targets if t[0] not in done]
log(f"{len(done):,} cached, {len(todo):,} to propose")
for d in checkpointed(A.ckpt, todo, propose, jobs=A.jobs, tag='xrefix', every=100, log=log):
    done[d['i']] = d['g']

# ------------------------------------------------------------------ acceptance
vocab = gloss_vocabulary(rows)
kept = rejected = unchanged = 0


def decide(item):
    i, kind, j = item
    g = (done.get(i) or '').strip()
    if not g or g.upper() == 'NONE':
        return i, None
    if reasons(rows[i][1], g, 'model', bodies[i], vocab):
        return i, None
    coined = not_english(g)
    if coined:
        return i, False
    # A gloss that is just the word the entry points at carries no information,
    # and where the source is corrupt it actively misleads: "Bohemi, v. Boil."
    # is an OCR error for Boii, and glossing it "boil" is worse than leaving the
    # row empty. Correcting the source would be fabrication (see README), so the
    # only safe move is to decline.
    mt = xref_target_word(bodies[i])
    if mt and letters(g) == letters(mt[1]):
        return i, False
    if letters(g) == letters(rows[i][2]):
        return i, None
    sc = judge(i, g, j)
    if sc < A.keep_min:
        return i, False
    if rows[i][2].strip() and sc <= judge(i, rows[i][2], j):
        return i, False
    return i, g


log("judging candidates...")
changes = []
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=A.jobs) as ex:
    for i, verdict in ex.map(decide, targets):
        if verdict is None:
            unchanged += 1
        elif verdict is False:
            rejected += 1
        else:
            changes.append((i, rows[i][2], verdict))
            kept += 1

for i, old, new in changes:
    rows[i][2] = new
    rows[i][3] = 'xrefix' if old.strip() else 'refilled'

dst = A.out or A.tsv
with open(dst, 'w', encoding='utf-8') as fh:
    fh.write("# columns\tkey\theadword\tgloss\tsource\n")
    for r in rows:
        fh.write('\t'.join(r) + '\n')
print(f"\nkept {kept:,}, rejected {rejected:,}, unchanged {unchanged:,} -> {dst}", file=sys.stderr)
for i, old, new in changes[:20]:
    print(f"  {rows[i][1][:16]:18} {old[:30]!r:32} -> {new!r}", file=sys.stderr)
