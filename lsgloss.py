#!/usr/bin/env python3
"""
Gloss every entry of Lewis & Short's *A Latin Dictionary* (1879) with a local LLM.

Single pass. For each entry, in order of preference:
  1. <tr>    -- the dictionary's own translation tag, when it is already 1-5 words (free)
  2. xref    -- a pure cross-reference ("v. condicio"); resolved to the target's gloss (free)
  3. model   -- everything else, sent to a local llama-server
Entries the model declines to gloss are retried with a repair prompt, then all
cross-references are resolved and every gloss is stripped of citations.

Resumable: results are checkpointed per entry, so re-running continues where it
stopped. A call that fails is not checkpointed, so it is retried next time.

    --offline   make no model calls: rebuild the TSV from the checkpoint alone,
                so a fix to a rule (clean, enforce, cross-reference resolution)
                reaches the shipped data without a day of model time. Rows with
                no checkpointed reply keep whatever the rules give them.
    --carry T   keep the rows a later model-verified stage (xrefix.py, freqfix.py) changed
                in TSV T, which a rebuild from the checkpoint would otherwise
                undo.
"""
import re, sys, json, hashlib, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import (txt, focus, chat, load_entries, XrefIndex, load_ckpt,
                    checkpointed, pos_marker)
from eval.xref import is_xref
from clean_gloss import clean, enforce
from ground import score as ground_score
from suspect import reasons as suspect_reasons, gloss_vocabulary, is_bare_echo

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--xml', required=True, help='path to lat.ls.perseus-eng2.xml (Perseus lexica repo)')
p.add_argument('--out', default='out/ls_glosses.tsv')
p.add_argument('--ckpt', default='out/ckpt.jsonl', help='per-entry checkpoint (resume)')
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
p.add_argument('-j', '--jobs', type=int, default=4, help='concurrent requests (4 is optimal on M4)')
p.add_argument('-n', '--limit', type=int, help='only process the first N entries (testing)')
p.add_argument('--maxchars', type=int, default=2000, help='truncate entry text sent to the model')
p.add_argument('--effort', default='low', help='reasoning effort passed to the chat template')
p.add_argument('--no-repair', action='store_true', help='skip the repair pass for declined entries')
p.add_argument('--hard-effort', default='medium',
               help="reasoning effort for the low-quality re-gloss pass. Needs llama-server "
                    "started WITHOUT --reasoning-budget 0, or this has no effect.")
p.add_argument('--no-hard', action='store_true', help='skip the low-quality re-gloss pass')
p.add_argument('--adapt', action='store_true',
               help='adapt inherited cross-reference glosses to the referring word. OFF by '
                    'default: the stage measured worse than doing nothing (README, "The '
                    'adaptation stage should be turned off").')
p.add_argument('--no-adapt', action='store_true', help=argparse.SUPPRESS)   # the old spelling of the default
p.add_argument('--maxwords', type=int, default=5, help='hard cap on gloss length; longer glosses are condensed')
p.add_argument('--use-tr', action='store_true',
               help="reuse the dictionary's own <tr> tag when it is 1-5 words. OFF by default: on a "
                    "long entry the first <tr> can belong to any sense, including an example buried "
                    "deep in the article, so the most frequent words (which have the longest entries) "
                    "get the worst glosses -- sum -> 'nor is she ashamed', fero -> 'to hold dear'.")
p.add_argument('--min-grounding', type=float, default=0.0,
               help='flag glosses whose content words are below this overlap with their entry '
                    '(0.0 = flag only fully ungrounded); such rows get source suffix "?"')
p.add_argument('--drop-ungrounded', action='store_true',
               help='blank flagged glosses instead of keeping them for review')
p.add_argument('--offline', action='store_true',
               help='no model calls: rebuild from the checkpoint with the current rules')
p.add_argument('--carry', metavar='TSV',
               help='keep the xrefix/refilled rows of this earlier TSV (see module doc)')
A = p.parse_args()

PROMPTS = {k: (ROOT / f'prompts/{f}').read_text(encoding='utf-8').strip() for k, f in (
    ('SYS', 'gloss-system.txt'), ('USR', 'gloss-user.txt'), ('REPAIR', 'gloss-repair.txt'),
    ('SHORTEN', 'gloss-shorten.txt'), ('NAME', 'gloss-name.txt'), ('HARD', 'gloss-hard.txt'),
    ('ADAPT', 'gloss-adapt.txt'), ('ADAPT_U', 'adapt-user.txt'))}
SYS, USR, REPAIR, SHORTEN = PROMPTS['SYS'], PROMPTS['USR'], PROMPTS['REPAIR'], PROMPTS['SHORTEN']
NAME, HARD, ADAPT, ADAPT_U = PROMPTS['NAME'], PROMPTS['HARD'], PROMPTS['ADAPT'], PROMPTS['ADAPT_U']
# Every prompt, not just the first three: the manifest used to under-record what
# produced the file, and a change to the hard or name prompt went unnoticed.
PROMPT_ID = hashlib.sha256('\x00'.join(PROMPTS[k] for k in sorted(PROMPTS)).encode()).hexdigest()[:12]

def log(s):
    print(s, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- parse + classify
ents = load_entries(A.xml)
XML_ID = hashlib.sha256(Path(A.xml).read_bytes()).hexdigest()[:12]
if A.limit: ents = ents[:A.limit]
if not ents: sys.exit(f"no <entryFree> elements found in {A.xml}")

rows, bodies, focused = [], [], []
for i, e in enumerate(ents):
    key  = (re.search(r'key="([^"]*)"', e) or [None, ''])[1]
    orth = txt((re.search(r'<orth\b[^>]*>(.*?)</orth>', e, re.S) or [None, ''])[1]) or key
    body = txt(e); bodies.append(body); focused.append(focus(body))
    trs   = re.findall(r'<tr\b[^>]*>(.*?)</tr>', e, re.S)
    first = txt(trs[0]) if trs else ''
    if A.use_tr and first and 1 <= len(first.split()) <= 5:
        rows.append([key, orth, first, 'tr'])
    elif is_xref(body):
        rows.append([key, orth, '', 'xref'])
    else:
        rows.append([key, orth, '', 'model'])
xrefs = XrefIndex(rows, bodies)

Path(A.out).parent.mkdir(parents=True, exist_ok=True)
Path(A.ckpt).parent.mkdir(parents=True, exist_ok=True)

# A checkpoint written under different prompts or a different dictionary is
# still resumed from -- the alternative is a day of model time -- but say so.
_manifest = Path(A.out).with_name('manifest.json')
if _manifest.exists() and not A.limit:
    try:
        _m = json.loads(_manifest.read_text(encoding='utf-8'))
        if _m.get('prompt_id') not in (None, PROMPT_ID):
            log(f"note: prompts changed since the last run ({_m.get('prompt_id')} -> {PROMPT_ID}); "
                f"checkpointed replies were produced under the old prompts")
        if _m.get('xml_id') not in (None, XML_ID):
            log(f"note: the dictionary XML changed since the last run; the checkpoint is "
                f"positional, so a changed entry order would misalign it")
    except Exception:
        pass

# ---------------------------------------------------------------- model helpers
def ask(system, body, temp, maxtok):
    return clean(chat(A.url, system, USR.replace('{ENTRY}', body),
                      temperature=temp, max_tokens=maxtok, effort=A.effort))

def cached(prefix, indices, inputs=None):
    """{i: gloss} for the rows of `indices` this pass has already answered.

    `inputs` maps i -> the text the pass was given (shorten and adapt take the
    current gloss, not the entry); a record made from a different input is
    stale and is ignored, so a repaired main gloss is not re-shortened from
    its predecessor's cache. Records without an input field are trusted."""
    done = load_ckpt(A.ckpt, prefix)
    out = {}
    for i in indices:
        d = done.get(i)
        if d is None: continue
        if inputs is not None and 'in' in d and d['in'] != inputs[i]: continue
        out[i] = d['g']
    return out

def run_pass(indices, system, tag, ckpt_prefix):
    """Gloss `indices` with `system`, checkpointing as it goes. Returns {i: gloss}.

    Returns ONLY results for the rows this pass actually covers. The checkpoint
    accumulates every row a pass has ever handled, so returning all of it
    re-applies stale results to rows that a changed classification rule has
    since moved elsewhere -- silently undoing the rule change."""
    done = cached(ckpt_prefix, indices)
    todo = [] if A.offline else [i for i in indices if i not in done]
    log(f"[{tag}] {len(indices):,} entries, {len(done):,} cached, {len(todo):,} to do"
        + (" (offline: skipped)" if A.offline and len(done) < len(indices) else ""))

    def work(i):
        b = focused[i][:A.maxchars]
        try:
            return {"i": i, "g": ask(system, b, 0, 96) or ask(system, b, 0.6, 192)}
        except Exception as ex:
            log(f"  [{tag}] entry {i} ({rows[i][1]}): {ex}")
            return None

    for rec in checkpointed(A.ckpt, todo, work, jobs=A.jobs, tag=tag,
                            extra={"p": ckpt_prefix}, log=log):
        done[rec['i']] = rec['g']
    return done

# ---------------------------------------------------------------- 1. main model pass
main_idx = [i for i, r in enumerate(rows) if r[3] == 'model']
for i, g in run_pass(main_idx, SYS, 'gloss', 'main').items():
    rows[i][2] = g

# ---------------------------------------------------------------- 2. repair declines
# The model answers "XREF" when it finds no definition. Where the entry really does
# point elsewhere that is correct (resolved below); where it does not, the entry
# usually *does* describe its word, so re-ask with a prompt that forbids declining.
if not A.no_repair:
    # Only a structurally-detected cross-reference is exempt from repair. Testing for
    # "v." anywhere in the body wrongly exempts every long entry -- they all cite
    # something -- which is precisely the high-frequency words (ab, tu, an).
    declined = [i for i in main_idx if rows[i][2].strip().upper() in ('XREF', 'NONE')
                and not is_xref(bodies[i])]
    for i, g in run_pass(declined, REPAIR, 'repair', 'repair').items():
        rows[i][2] = g; rows[i][3] = 'repaired'

# ---------------------------------------------------------------- 2b. condense long glosses
# Most over-length glosses are a single tight phrase with no clause to trim, so
# they are re-asked rather than truncated. The gloss itself is the input, which
# keeps the wording (and therefore the grounding) tied to the entry.
def shorten(text):
    return clean(chat(A.url, SHORTEN, text, max_tokens=48, effort=A.effort),
                 maxwords=A.maxwords)

long_idx = [i for i, r in enumerate(rows)
            if r[3] in ('model', 'repaired') and len(clean(r[2], A.maxwords).split()) > A.maxwords]
if long_idx:
    inputs = {i: rows[i][2] for i in long_idx}
    done = cached('shorten', long_idx, inputs)
    todo = [] if A.offline else [i for i in long_idx if i not in done]
    log(f"[shorten] {len(long_idx):,} over {A.maxwords} words, {len(done):,} cached, {len(todo):,} to do")

    def _s(i):
        try: return {"i": i, "g": shorten(rows[i][2]), "in": rows[i][2]}
        except Exception as ex:
            log(f"  [shorten] entry {i}: {ex}"); return None
    for rec in checkpointed(A.ckpt, todo, _s, jobs=A.jobs, tag='shorten',
                            extra={"p": "shorten"}, log=log):
        done[rec['i']] = rec['g']
    for i in long_idx:
        g = done.get(i, '')
        if g and len(g.split()) <= len(rows[i][2].split()): rows[i][2] = g

# ---------------------------------------------------------------- 2bb. bare-echo repair
# Some entries come back as the headword itself ("Melos" -> "Melos, i"), which
# carries no information. Re-ask with a prompt that forbids repeating it.
echo_idx = [i for i, r in enumerate(rows)
            if r[3] in ('model', 'repaired') and r[2].strip() and is_bare_echo(r[1], r[2])]
if echo_idx:
    for i, g in run_pass(echo_idx, NAME, 'name', 'name').items():
        if g and g.strip().upper() != 'NONE' and not is_bare_echo(rows[i][1], g):
            rows[i][2] = g; rows[i][3] = 'named'

# ---------------------------------------------------------------- 2d. re-gloss suspects
# Screen every gloss with cheap mechanical detectors and re-ask for the ones that
# look wrong, this time with reasoning enabled -- worth the cost on a few percent.
def hard_pass(tag, prefix, finalised=False):
    # The vocabulary is rebuilt here rather than once: the passes above have
    # changed the glosses, and it is what tells a Latin echo from an English
    # cognate.
    vocab = gloss_vocabulary(rows)
    idx, why = [], {}
    for i, r in enumerate(rows):
        w = suspect_reasons(r[1], r[2], r[3], bodies[i], vocab)
        if w: idx.append(i); why[i] = w
    if not idx:
        return
    from collections import Counter
    log(f"[{tag}] {len(idx):,} suspect glosses: "
        + ", ".join(f"{k}={v}" for k, v in Counter(x for v in why.values() for x in v).most_common()))
    prev_effort, A.effort = A.effort, A.hard_effort
    try:
        for i, g in run_pass(idx, HARD, tag, prefix).items():
            if finalised:
                g = enforce(clean(g, A.maxwords), A.maxwords)
            if g and g.strip().upper() != 'NONE' and not suspect_reasons(rows[i][1], g, 'model', bodies[i], vocab):
                rows[i][2] = g; rows[i][3] = prefix
    finally:
        A.effort = prev_effort

if not A.no_hard:
    hard_pass('hard', 'hard')

# ---------------------------------------------------------------- 3. resolve cross-refs
res = unres = 0
glosses = [r[2] for r in rows]
for i, r in enumerate(rows):
    if r[3] != 'xref' and r[2].strip().upper() not in ('XREF', 'NONE'): continue
    hit = xrefs.resolve(i, glosses)
    if hit: r[2] = hit[1]; r[3] = 'xref-resolved'; res += 1
    else: r[2] = ''; r[3] = 'no-gloss'; unres += 1

# ---------------------------------------------------------------- 3b. adapt inherited glosses
# A cross-reference inherits its target's gloss verbatim, which is wrong whenever
# the two words differ in part of speech: "obsutus" (participle) inheriting
# "to sew on", "impure" (adverb) inheriting "unclean, filthy". Ask the model to
# restate the target's sense in the form of this headword.
if A.adapt and not A.no_adapt:
    # Narrowed to ADVERBS after an A/B against a --no-adapt build. Adapting adverbs
    # is a clear win ("impure" -> "impurely", not the adjective's "unclean, filthy").
    # Adapting participles is not: "bibitus" is a perfect PASSIVE participle, and
    # adaptation produced the present active "drinking". Over all cross-references
    # the two effects cancelled (3.95 unadapted vs 3.93 adapted), so only the
    # adverbs are adapted. The entry's own marker decides where it has one; the
    # shape of the headword only where it has none, because `-ter` and `-im` also
    # end `pater`, `Jupiter` and `enim`.
    ADVERB = re.compile(r'(?:[^aeiou]ē|iter|ter|im)$')
    def is_adverb(i):
        m = pos_marker(bodies[i])
        return m == 'adv' if m else bool(ADVERB.search(rows[i][1].rstrip('.')))
    adapt_idx = [i for i, r in enumerate(rows)
                 if r[3].startswith('xref-resolved') and r[2].strip() and is_adverb(i)]
    if adapt_idx:
        inputs = {i: rows[i][2] for i in adapt_idx}
        done = cached('adapt', adapt_idx, inputs)
        todo = [] if A.offline else [i for i in adapt_idx if i not in done]
        log(f"[adapt] {len(adapt_idx):,} inherited cross-reference glosses, "
            f"{len(done):,} cached, {len(todo):,} to do")

        def _adapt(i):
            prompt = (ADAPT_U.replace('{HEAD}', rows[i][1])
                             .replace('{ENTRY}', focused[i][:400])
                             .replace('{TARGET}', rows[i][2]))
            try:
                return {"i": i, "in": rows[i][2],
                        "g": clean(chat(A.url, ADAPT, prompt, max_tokens=64, effort=A.effort), A.maxwords)}
            except Exception as ex:
                log(f"  [adapt] entry {i}: {ex}"); return None
        for rec in checkpointed(A.ckpt, todo, _adapt, jobs=A.jobs, tag='adapt',
                                extra={"p": "adapt"}, log=log):
            done[rec['i']] = rec['g']
        BADADAPT = re.compile(r'\((?:verb|adj|adjective|adverb|noun|n|v)\.?\)|'
                              r'\b\w*(?:llly|lyly|eded|inging)\b|'
                              # concatenations like "beforebearing", "wellly"
                              r'\b(?:before|after|under|over|out|up|down)(?:bear|carry|go|come|put|take)\w*\b', re.I)
        adapted = 0
        for i in adapt_idx:
            g = done.get(i, '')
            if g and BADADAPT.search(g): g = ''        # coined word or grammar note: keep the original
            if g and g.strip().upper() != 'NONE' and g.strip() != rows[i][2].strip():
                rows[i][2] = g; rows[i][3] = 'xref-adapted'; adapted += 1
        log(f"[adapt] {adapted:,} glosses changed")

# ---------------------------------------------------------------- 4. grounding check
# A gloss whose words appear nowhere in its entry is usually invented. Entries
# defined only in Latin are correct but score 0, so this flags rather than deletes.
# Every source the model wrote from the entry is checked -- the hard and name
# passes were exempt, so an invented gloss that arrived through them went out
# unmarked.
flagged = 0
for i, r in enumerate(rows):
    if r[3] not in ('model', 'repaired', 'hard', 'hard2', 'named') or not r[2].strip(): continue
    if ground_score(r[2], bodies[i]) <= A.min_grounding:
        if A.drop_ungrounded: r[2] = ''
        r[3] += '?'; flagged += 1

# ---------------------------------------------------------------- 5. clean + write
def finalise():
    """clean + hard word cap; returns (cleaned, trimmed) counts."""
    c_n = t_n = 0
    for r in rows:
        c = clean(r[2], A.maxwords)
        if c != r[2]: c_n += 1
        e = enforce(c, A.maxwords)
        if e != c:
            t_n += 1
            if not r[3].endswith('~'): r[3] += '~'
        r[2] = e
    return c_n, t_n

cleaned, trimmed = finalise()

# A second screen after the text is final: shorten() and enforce() can themselves
# produce a bad gloss ("one who is of the"), which the earlier screen cannot see.
if not A.no_hard:
    hard_pass('hard-2', 'hard2', finalised=True)
    finalise()

# ---------------------------------------------------------------- 6. carry over
# xrefix.py and freqfix.py change rows only after an independent judging call,
# and their judge verdicts are not checkpointed, so a rebuild cannot reproduce
# them. Keep them.
CARRY_SOURCES = ('xrefix', 'refilled', 'freqfix')
carried = 0
if A.carry:
    from common import load_rows
    prev = {r[0]: r for r in load_rows(A.carry)}
    for r in rows:
        q = prev.get(r[0])
        if q and q[3].rstrip('~?!') in CARRY_SOURCES and q[2].strip():
            if r[2] != q[2] or r[3] != q[3]:
                r[2], r[3] = q[2], q[3]; carried += 1
    log(f"[carry] {carried:,} rows kept from {A.carry}")

with open(A.out, 'w', encoding='utf-8') as f:
    f.write(f"# prompt_id\t{PROMPT_ID}\n# entries\t{len(rows)}\n")
    f.write("# columns\tkey\theadword\tgloss\tsource\n")
    for r in rows: f.write('\t'.join(r) + '\n')

from collections import Counter
mix = Counter(r[3] for r in rows)
with open(_manifest, 'w', encoding='utf-8') as f:
    json.dump({"prompt_id": PROMPT_ID, "xml_id": XML_ID, "system": SYS, "user": USR, "repair": REPAIR,
               "xml": str(A.xml), "jobs": A.jobs, "maxchars": A.maxchars, "effort": A.effort,
               "offline": A.offline, "carried": carried,
               "entries": len(rows), "source_mix": dict(mix)}, f, indent=2, ensure_ascii=False)
log(f"\nxref resolved {res:,} | unresolved {unres:,} | citations stripped {cleaned:,} "
    f"| ungrounded flagged {flagged:,} | trimmed to cap {trimmed:,}")
log("source mix: " + ", ".join(f"{k}={v:,}" for k, v in mix.most_common()))
log(f"-> {A.out}")
