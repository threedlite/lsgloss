#!/usr/bin/env python3
"""Re-gloss the entries a reader meets most often, in corpus-frequency order.

Quality work naturally drifts toward whatever is easy to sample. Entries are
uniform, running text is not: a few hundred words carry most of a page, and those
words have the longest, hardest dictionary articles. So a defect rate that looks
negligible per entry can dominate what a reader actually sees -- the `<tr>`
shortcut was 14% of entries and 44% of tokens.

This stage inverts that. It ranks every entry by how often its headword occurs in
a real Latin corpus, screens the top N for defects, and re-glosses the failures
with the hard prompt, highest-impact first. It is the same repair machinery used
elsewhere in the pipeline; only the ordering is different, and the ordering is
the point.

    python3 freqfix.py --xml <ls.xml> --freq <corpus-freq.tsv> --top 3000

Re-runnable: results are checkpointed, and a row is only replaced when the new
gloss clears the mechanical detectors that flagged the old one.
"""
import re, sys, argparse, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import (txt, focus, fold, chat, load_entries, load_rows, parse_score,
                    load_ckpt, checkpointed, XrefIndex, pos_marker as _pos_marker)
from suspect import reasons, gloss_vocabulary, function_entry
from common import pos_marker
from clean_gloss import clean, enforce
from namegloss import is_name_entry
from senses import sense_headings

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--freq', required=True, help='TSV of form<TAB>count from a Latin corpus')
p.add_argument('--out', default='out/ls_glosses.tsv')
p.add_argument('--ckpt', default='out/freqfix_ckpt.jsonl')
p.add_argument('--screen', action='store_true',
               help='judge each frequent entry\'s CURRENT gloss and target the poor ones. '
                    'A scores file goes stale as soon as the glosses change, and a stale '
                    'score is worse than none: it reported *ab* as 4 for a gloss that had '
                    'since been replaced by a wrong one.')
p.add_argument('--min-score', type=int, default=3,
               help='with --screen, also target frequent entries the judge rated this low. '
                    'Mechanical detectors cannot see a wrong-but-well-formed gloss: '
                    '"around, near, beside, among" for *ab* passes every one of them.')
p.add_argument('--skip', type=int, default=0,
               help='skip this many of the most frequent entries; with --top it selects a '
                    'band, so --skip 1500 --top 3000 screens ranks 1500-4500')
p.add_argument('--top', type=int, default=3000, help='how many of the most frequent entries to screen')
p.add_argument('--effort', default='low'); p.add_argument('--maxwords', type=int, default=5)
p.add_argument('--maxchars', type=int, default=800)
p.add_argument('-j', '--jobs', type=int, default=4)
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
p.add_argument('--dry-run', action='store_true', help='report the targets, change nothing')
p.add_argument('--screen-passes', type=int, default=1,
               help='with --screen, judge each incumbent this many times and keep the LOWEST '
                    'score. The judge is noisy -- two screenings of the same 500 entries '
                    'disagreed on 15 targets -- and a gloss that fails once is worth a look')
p.add_argument('--headings', action='store_true',
               help='judge against a map of the entry\'s senses (headword line, then "I. ..., '
                    'II. ..." from the XML sense markup) instead of its first 800 characters, '
                    'and offer that map to the glosser as its first window. See senses.py')
p.add_argument('--redecide', action='store_true',
               help='no screening and no glossing: take every entry with a candidate in the '
                    'checkpoint as a target and re-run the decision under the current rule')
p.add_argument('--function-words', action='store_true',
               help='target only entries whose headword line marks a function word (conj., '
                    'praep., adv., pron., interj., num.) and are not proper names -- the '
                    'words a reader meets on every line, whose long articles the model '
                    'glosses worst')
A = p.parse_args()

HARD = (ROOT/'prompts/gloss-hard.txt').read_text(encoding='utf-8').strip()
USR  = (ROOT/'prompts/gloss-user.txt').read_text(encoding='utf-8').strip()
JSYS = (ROOT/'prompts/judge-terse.txt').read_text(encoding='utf-8').strip()
JUSR = (ROOT/'prompts/judge-terse-user.txt').read_text(encoding='utf-8').strip()


def log(s): print(s, file=sys.stderr, flush=True)

ents = load_entries(A.xml)
bodies = [txt(e) for e in ents]
rows = load_rows(A.tsv)

# A pointer entry ("forte, adv. v. fors") has no definition of its own: the
# judge shown its 20 characters has nothing to judge against, and noise
# decided -- *forte* became "strongly", *sane* "healthy". For such an entry the
# judge and the glosser are shown the TARGET entry's material, with a note
# that the gloss is for the pointing word (an adverb, usually).
# The chase follows pointers only while the entry reached is itself a pointer:
# a substantive article cites other entries ("v. bellus" inside *bonus*) and
# hopping on from there sent *melius* to "war" and *similiter* to "ape".
POINTER_MAX = 200
_xrefs = XrefIndex(rows, bodies)
_target = {}
for _i in range(len(rows)):
    if len(bodies[_i]) >= POINTER_MAX: continue
    _j, _seen = _i, {_i}
    for _ in range(4):
        _n = _xrefs.target_of(_j)
        if _n is None or _n in _seen: break
        _seen.add(_n); _j = _n
        if len(bodies[_j]) >= POINTER_MAX: break      # a real article: stop here
    if _j != _i: _target[_i] = _j

def material(i):
    """(text to gloss from, sense map to judge against) for entry i."""
    if i in _target:
        j = _target[i]
        pos = _pos_marker(bodies[i]) or 'form'
        note = (f"{rows[i][1]} is a {pos} that the dictionary refers to the entry {rows[j][1]}; "
                f"the gloss must be for {rows[i][1]} itself (an {pos} form of the sense below), "
                f"not for {rows[j][1]}.\n")
        return note + focus(bodies[j]), note + sense_headings(ents[j])
    return focus(bodies[i]), sense_headings(ents[i])

from lemmafreq import load_form_counts, lemma_frequencies
form_counts = load_form_counts(A.freq)
lemfreq = lemma_frequencies(rows, bodies, form_counts)

# rank by how often the LEMMA occurs, summed over its inflected forms -- not by
# the frequency of its headword spelling, which misses fatum (met as fato, fata)
FUNC_POS = ('conj', 'praep', 'adv', 'pron', 'interj', 'num')
def is_function_word(i):
    """The entry's own headword line marks a function word: parentheses
    removed (L&S opens `Cum` with a 120-character note on spelling), read from
    the first 60 characters so a marker inside a citation does not count."""
    head = re.sub(r'\([^()]*\)', ' ', bodies[i])
    return ((pos_marker(head[:60]) in FUNC_POS or function_entry(focus(bodies[i])))
            and not is_name_entry(rows[i][1]))

ranked = []
for i, r in enumerate(rows):
    f = lemfreq.get(r[0], 0)
    if not f: continue
    if A.function_words and not is_function_word(i): continue
    ranked.append((f, i))
ranked.sort(reverse=True)
head = ranked[A.skip:A.skip + A.top]

def _call(system, user, maxtok):
    return chat(A.url, system, user, max_tokens=maxtok, effort=A.effort)

def rate(i, gloss, off=0, view=None):
    """Score a candidate against the entry. Mechanical checks cannot tell that
    'around, near, beside, among' is wrong for *ab* -- it is well formed, English,
    grounded, and simply not what the word means.

    `view` is 'map' (the sense headings), 'open' (the article text at `off`),
    or None for whichever --headings selects."""
    if not gloss: return -1
    try:
        text, smap = material(i)
        # Judge against the window the candidate came from. Scoring everything
        # against the first 800 characters is useless for a long entry: *ab*
        # does not define itself until character 3,760, so in window 0 a correct
        # gloss and a wrong one are indistinguishable and the incumbent survives.
        window = text[off:off + A.maxchars] if off else text[:A.maxchars]
        if view == 'map' or (view is None and A.headings):
            # ...or, better, the map of senses in the dictionary's own order,
            # where the first line is the primary sense a gloss has to match
            window = ("Senses in the dictionary's order; the first numbered sense is the main one.\n"
                      + smap)
        s = parse_score(_call(JSYS, JUSR.replace('{ENTRY}', window).replace('{GLOSS}', gloss), 16))
        return -1 if s is None else s
    except Exception:
        return -1


def offsets_for(i, text=None):
    """The windows to try for this entry -- the SAME set for every candidate.

    Both the incumbent and the challenger have to be scored over the same
    windows. Judging the incumbent only at the challenger's offset gave the
    challenger home-turf advantage: a correct gloss supported at the start of a
    long entry scores 0 against a window 3,200 characters in, so it lost to
    whatever the model had just produced, however wrong.
    """
    text = focus(bodies[i]) if text is None else text
    offs = [0]
    if len(text) > A.maxchars * 2:
        offs += [A.maxchars * k for k in (2, 4, 6)]
    return [o for o in offs if len(text[o:o + A.maxchars]) >= 60]


def best_rate(i, gloss):
    """The gloss's score at the article's OPENING.

    Comparing on the best window over the whole article rewarded whatever
    sense sits deepest: *moneo* came out "punish, chastise", a late sense far
    down the article, and *quidem* "example, for instance" from a window 1,600
    characters in, when the article opens "quidem, adv. Indeed". The opening of
    a focused article is where L&S states the primary sense, and a candidate
    has to beat the incumbent there. An article that opens with pages of
    philology (*ab* does not say "from" until character 3,760) cannot be
    repaired this way, and is left to the detectors and the app's own data
    rather than to whichever deep sense the judge liked best."""
    if not gloss:
        return -1
    return rate(i, gloss, 0)


MAP_MIN = 4              # a candidate must be at least "close" on the sense map

def _words(g):
    return {w for w in re.findall(r"[a-z]+", g.lower()) if len(w) > 2}

def adverb_reuses_adjective(i, new):
    """An adverb pointer (`sane`, "v. sanus") glossed with its adjective's own
    words ("healthy, sound, whole") is the target's gloss, not the adverb's.
    The judge scores meaning and lets it through; this does not."""
    if i not in _target or (_pos_marker(bodies[i]) or '') != 'adv':
        return False
    tgt = _words(rows[_target[i]][2])
    cand = _words(new)
    if not cand or not tgt:
        return False
    first = re.findall(r"[a-z]+", new.lower())[:1]
    return (len(cand & tgt) * 2 >= len(cand)) or (first and first[0] in tgt)

def better(i, new, old):
    """Does `new` beat `old` for entry i?

    Under --headings a candidate has to score at least MAP_MIN on the sense
    map, win there against the incumbent, and not lose on the article's
    opening text. The map alone was self-fulfilling: the model copies a
    heading's wording and the judge, shown the same heading, rates the copy 5
    -- so *sine* became "without weight, without force" and *ex* "from a
    certain point onward", descriptions of a sense rather than glosses of the
    word. The opening text is where those lose. Every score is logged."""
    if not old:
        return True
    if not A.headings:
        return best_rate(i, new) > best_rate(i, old)
    if adverb_reuses_adjective(i, new):
        log(f"  [decide] {rows[i][0]:14s} {new!r:40s} REJECT adverb reuses its adjective's gloss")
        return False
    mn, mo = rate(i, new, view='map'), rate(i, old, view='map')
    on, oo = (rate(i, new, view='open'), rate(i, old, view='open')) if mn > mo and mn >= MAP_MIN else (None, None)
    ok = mn >= MAP_MIN and mn > mo and on >= oo
    log(f"  [decide] {rows[i][0]:14s} {new!r:40s} map {mn}>{mo}? open {on}>={oo}? -> {'ACCEPT' if ok else 'reject'}"
        f"   (was {old!r})")
    return ok


judged = {}
if A.redecide:
    A.screen = False
if A.screen:
    print(f"screening the current gloss of {len(head):,} frequent entries...", file=sys.stderr, flush=True)
    def _screen(item):
        f, i = item
        if not rows[i][2].strip():
            return i, -1
        # the lowest of several verdicts; a failed call (-1) is not a verdict
        scores = [rate(i, rows[i][2]) for _ in range(A.screen_passes)]
        good = [s for s in scores if s >= 0]
        return i, (min(good) if good else -1)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=A.jobs) as ex:
        for k, (i, sc) in enumerate(ex.map(_screen, head), 1):
            judged[rows[i][0]] = sc
            if k % 200 == 0:
                print(f"  screened {k:,}/{len(head):,} {k/(time.time()-t0):.2f}/s", file=sys.stderr, flush=True)

vocab = gloss_vocabulary(rows)
targets = []
if A.redecide:
    _ck = load_ckpt(A.ckpt)
    head = [(f, i) for f, i in head if i in _ck]
for f, i in head:
    r = rows[i]
    why = reasons(r[1], r[2], r[3], bodies[i], vocab) if r[2].strip() else ['empty']
    sc = judged.get(r[0])
    # -1 means the judge failed or answered unparseably; that is not a low score
    if sc is not None and 0 <= sc <= A.min_score and 'empty' not in why:
        why = why + [f'judge={sc}']
    if A.redecide and not why: why = ['redecide']
    if why: targets.append((f, i, why))
tokens = sum(f for f, _, _ in targets)
print(f"screened entries ranked {A.skip:,}-{A.skip + len(head):,} by lemma frequency", file=sys.stderr)
print(f"defective: {len(targets):,} entries, covering {tokens:,} corpus tokens", file=sys.stderr)
for f, i, why in targets[:15]:
    print(f"  {f:8,}x {rows[i][1][:16]:18} {rows[i][2][:34]!r:36} {','.join(why)}", file=sys.stderr)
if A.dry_run or not targets:
    sys.exit(0)

done = {i: (d.get('g', ''), d.get('off', 0)) for i, d in load_ckpt(A.ckpt).items()}
todo = [] if A.redecide else [(f, i) for f, i, _ in targets if i not in done]

def work(item):
    """Gloss one entry, sliding the window if the definition is buried.

    The commonest words have the longest articles, and L&S opens them with pages
    of philology: *ab* runs 30,000 characters and does not say "from, away from"
    until character 3,760. A fixed window from the start shows the model nothing
    but Indo-European cognates, and it invents a plausible-looking gloss. So for
    long entries, try successive windows and keep the first candidate that the
    judge rates well."""
    f, i = item
    text, smap = material(i)
    best, best_score, best_off, failed = '', -1, 0, 0
    windows = [(off, text[off:off + A.maxchars]) for off in offsets_for(i, text)]
    if A.headings:
        # the sense map first: it shows the primary sense where a long
        # article's opening shows philology
        windows.insert(0, (0, smap + '\n\n' + text[:A.maxchars // 2]))
    for off, window in windows:
        try:
            out = _call(HARD, USR.replace('{ENTRY}', window), 96)
        except Exception as ex:
            log(f"  entry {i} ({rows[i][1]}) window {off}: {ex}"); failed += 1
            continue
        cand = enforce(clean(out, A.maxwords), A.maxwords)
        if not cand or cand.upper() == 'NONE': continue
        sc = rate(i, cand, off)
        if sc > best_score: best, best_score, best_off = cand, sc, off
        if sc >= 5: break                       # good enough, stop paying
    if not best and failed:
        return None                             # the model was unreachable: retry next run
    return {"i": i, "g": best, "off": best_off}

for d in checkpointed(A.ckpt, todo, work, jobs=A.jobs, tag='freqfix', every=100, log=log):
    done[d['i']] = (d['g'], d['off'])

fixed = kept = rejected = 0
log("verifying replacements against the entry...")
def decide(item):
    f, i, why = item
    rec = done.get(i) or ('', 0)
    g, off = (rec if isinstance(rec, (list, tuple)) else (rec, 0))
    if not g or g.upper() == 'NONE' or reasons(rows[i][1], g, 'model', bodies[i], vocab):
        return i, None
    old = rows[i][2].strip()
    if old and not better(i, g, old):
        return i, False
    return i, g
with ThreadPoolExecutor(max_workers=A.jobs) as ex:
    for i, verdict in ex.map(decide, targets):
        if verdict is None: kept += 1
        elif verdict is False: rejected += 1
        else:
            rows[i][2] = verdict; rows[i][3] = 'freqfix'; fixed += 1
with open(A.out, 'w', encoding='utf-8') as fh:
    fh.write("# columns\tkey\theadword\tgloss\tsource\n")
    for r in rows: fh.write('\t'.join(r) + '\n')
print(f"\nrepaired {fixed:,}, rejected as no better {rejected:,}, unchanged {kept:,} -> {A.out}", file=sys.stderr)
