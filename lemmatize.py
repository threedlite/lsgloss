#!/usr/bin/env python3
"""Ask the model which headword a high-frequency inflected form belongs to.

inflect.py generates regular paradigms from each entry's own morphology, which
lifts corpus coverage from 49% to ~64% of tokens. What remains is irregular and
suppletive: `est`/`esse`/`sunt` (sum), `quae`/`quibus` (qui), `id`/`eius` (is),
`haec` (hic), `mihi` (ego). No regular rule produces those.

Rather than hand-writing irregular paradigms -- which fixes only the forms
someone thought of, and cannot be reproduced -- the model is asked for the lemma
of each unmatched form, ranked by how often a reader meets it. The answer is
accepted only if the proposed headword actually exists in the dictionary, so a
hallucinated lemma cannot enter the index.

    --offline   no model calls: rebuild the map from the checkpoint alone
"""
import re, os, sys, argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import txt, chat, load_entries, load_rows, load_ckpt, checkpointed
from inflect import forms_for, fold

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--freq', required=True)
p.add_argument('--out', default='out/lemma_map.tsv')
p.add_argument('--ckpt', default='out/lemma_ckpt.jsonl')
p.add_argument('-n', '--top', type=int, default=600, help='how many unmatched forms to resolve')
p.add_argument('-j', '--jobs', type=int, default=4)
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
p.add_argument('--offline', action='store_true', help='no model calls; use the checkpoint only')
A = p.parse_args()

def log(s): print(s, file=sys.stderr, flush=True)

ents = load_entries(A.xml)
bodies = [txt(e) for e in ents]
rows = load_rows(A.tsv)
index = {}
for i, (b, r) in enumerate(zip(bodies, rows)):
    if r[2].strip():
        for f in forms_for(r[1], b[:200]): index.setdefault(f, i)
head_index = {}
for i, r in enumerate(rows):
    if r[2].strip():
        head_index.setdefault(fold(r[1]), i)
        head_index.setdefault(fold(re.sub(r'\d+$', '', r[0])), i)

freq = []
with open(A.freq, encoding='utf-8') as fh:
    for line in fh:
        w, _, n = line.rstrip('\n').partition('\t')
        if n.isdigit(): freq.append((w, int(n)))
# The forms each headword line cites. L&S prints a word's irregular forms
# there -- "sum, fui, esse", "ego, mei, mihi", "hic, haec, hoc", "is, ea, id"
# -- so the entry for a suppletive form names the form itself. The line runs
# from the headword to the part-of-speech marker, parentheses included (that
# is where `ego` lists `mihi`); a token with a period is an abbreviation
# ("gen.", "id.", "Plaut.") and never a form.
POS_STOP = re.compile(r'\b(?:v|adj|adv|pron|praep|prep|conj|interj|num|subst|comm|m|f|n|indecl|part)\.')
def headline_forms(body):
    t = body[:600]
    m = POS_STOP.search(t)
    if m: t = t[:m.start()]
    return {fold(w) for w, dot in re.findall(r'([A-Za-zÀ-ɏ\^]+)(\.?)', t)
            if not dot and len(fold(w)) > 1}

cited = {}
for i, (b, r) in enumerate(zip(bodies, rows)):
    if not r[2].strip(): continue
    for w in headline_forms(b):
        cited.setdefault(w, set()).add(i)
missing = [(w, n) for w, n in freq if fold(w) not in index and len(w) > 1][:A.top]
log(f"{len(missing)} unmatched forms to resolve, covering {sum(n for _, n in missing):,} tokens")

SYS = ("You identify Latin dictionary headwords. Given an inflected Latin word, reply with "
       "ONLY the dictionary headword (lemma) it belongs to, in its standard citation form: "
       "nominative singular for nouns and adjectives, first person singular present for verbs. "
       "Reply with one word and nothing else. If it is not Latin, reply: NONE")
done = {w: d['l'] for w, d in load_ckpt(A.ckpt, key='w').items() if d.get('l') is not None}
todo = [] if A.offline else [(w, n) for w, n in missing if w not in done]
log(f"  {len(done):,} cached, {len(todo):,} to ask")

def ask(item):
    w, n = item
    try:
        out = chat(A.url, SYS, f"Latin form: {w}\nHeadword:", max_tokens=12, timeout=120).split()
    except Exception as ex:
        log(f"  {w}: {ex}"); return None
    return {"w": w, "l": out[0].strip('.,;:').lower() if out else ''}

for d in checkpointed(A.ckpt, todo, ask, jobs=A.jobs, tag='lemma', every=100, log=log):
    done[d['w']] = d['l']

def entry_lists_form(j, form):
    """Does entry j's headword line cite this form?"""
    return j in cited.get(fold(form), ())

kept = rejected = 0
how = {}
with open(A.out, 'w', encoding='utf-8') as f:
    f.write("# form\tlemma\tkey\theadword\tgloss\tfreq\n")
    for w, n in missing:
        lem = done.get(w, '')
        if not lem or lem == 'none':
            rejected += 1; continue
        # accept only if the proposed lemma is a real headword with a gloss:
        # a hallucinated lemma cannot get into the index
        j = head_index.get(fold(lem))
        # Existence is not correctness: "illuminus" is a real headword but the
        # wrong lemma for "illum". A real lemma shares a stem with its form and
        # is not much longer than it, since inflection mostly adds endings --
        # EXCEPT for the suppletives this stage exists for (`mihi` -> ego,
        # `haec` -> hic, `id` -> is), which share nothing. Those are accepted
        # when the entry itself cites the form.
        if j is not None:
            fw, fl = fold(w), fold(lem)
            shared = len(os.path.commonprefix([fw, fl]))
            regular = shared >= 2 and len(fl) <= len(fw) + 2
            if not regular and not entry_lists_form(j, w):
                j = None
        # An answer that is no headword -- `esse` for est, `haec` for haec, the
        # form itself echoed back -- is rejected. Reading the lemma off the
        # entries that cite the answer was tried and is unsafe: L&S's headword
        # lines are full of prose ("esse" is cited by `quam`), and the frequent
        # little words this stage exists for are exactly the ones that landed
        # on the wrong entry. The treebank supplies them in the full build.
        if j is None: rejected += 1; continue
        kept += 1
        f.write(f"{w}\t{lem}\t{rows[j][0]}\t{rows[j][1]}\t{rows[j][2]}\t{n}\n")
log(f"\naccepted {kept:,} form->headword links, rejected {rejected:,} "
    f"(lemma not in dictionary, or not a form of it) -> {A.out}")
