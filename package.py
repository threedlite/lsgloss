#!/usr/bin/env python3
"""Build a Classics Viewer importable dictionary ZIP.

Format is documented in DICTIONARY_IMPORT_FORMAT.md. Three members at the
archive root:

    morphology.csv           REQUIRED  inflected form -> lemma
    dictionary.csv           optional  lemma -> definition
    normalization_rules.csv  optional  diacritic folding for reader queries

Two things the format cares about that shape the output here:

* "Lemma consistency is the thing that matters most." The join between the two
  files is an exact string match, so both use the same lemma spelling: the plain
  L&S key with its homograph number stripped (`repente`, `sed`), never the
  accented headword (`rĕpentē`) and never a truncated stem.

* Homographs. L&S has sed1/sed2/sed3; a reader looks up `sed`. Their glosses are
  merged into a single dictionary row so the exact-string join stays unambiguous.

* `morph_info` is what the reader is shown when a form resolves, and the format
  documents it as morphology -- "3 s pres active ind". It is not a provenance
  field; `source_name` is. Every row therefore carries the parse, taken from the
  treebank postag where there is one and from the paradigm slot that generated
  the form otherwise, from the entry's part of speech where the paradigm tables
  could build nothing, and left empty where none of the three knows. The schema
  is Whitaker's, which is what `lemma_map` in the shipped database already holds
  1.96M Latin rows of: our rows land in that table beside theirs and a reader
  sees both under one word, so they have to read the same. See `inflect.py`.
  Which stage produced a row is printed to stderr at the end of the build.
"""
import re, csv, sys, zipfile, argparse, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import txt, plain, letters, load_entries, load_rows
from inflect import (forms_with_morph, postag_morph, split_enclitic, merge_morph, fold,
                     ENCLITIC_MORPH)
from suspect import reasons as suspect_reasons, gloss_vocabulary, function_entry
from common import focus, pos_marker, XrefIndex
from namegloss import is_name_entry

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--tsv', default='out/ls_glosses.tsv')
p.add_argument('--scores', help='per-gloss scores, used to set confidence')
p.add_argument('--lemma-map', default='out/lemma_map.tsv', help='model-supplied irregular forms')
p.add_argument('--treebank', help='directory of Perseus treebank XML; gold form/lemma pairs')
p.add_argument('--freq', help='corpus form frequencies; used to derank obscure lemmas in collisions')
p.add_argument('--out', default='out/lewis-short-glosses.zip')
p.add_argument('--source', default='Lewis & Short glosses')
p.add_argument('--min-score', type=int, default=0, help='drop glosses scoring below this')
p.add_argument('--keep-flagged', action='store_true',
               help='ship every gloss the TSV holds, including the rows the grounding check '
                    'flagged ("?" in the source column) and the rows a mechanical detector '
                    'says are not a gloss. Off by default: 527 flagged rows went out, 32 of '
                    'them "Athenian courtesan" on words that are not one, beside 334 bare '
                    'etymons ("pietas" -> "pius") and 86 "false reading" notes.')
A = p.parse_args()


ents = load_entries(A.xml)
bodies = [txt(e) for e in ents]
rows = load_rows(A.tsv)
assert len(rows) == len(ents), f"row/entry mismatch {len(rows)} vs {len(ents)}"

scores = {}
if A.scores:
    with open(A.scores, encoding='utf-8') as fh:
        for l in fh:
            if l.startswith('#'): continue
            f = l.rstrip('\n').split('\t')
            if len(f) >= 5:
                try: scores[f[0]] = int(f[4])
                except ValueError: pass

# ---------------------------------------------------------------- dictionary.csv
# one row per lemma; homograph glosses merged, best-scoring first
#
# The TSV keeps every gloss, marked rather than dropped, so a defect can be
# reviewed and repaired. The package is what a reader sees. A gloss the
# grounding check could not tie to its entry ("?") is more often invented than
# right, and a gloss a mechanical detector calls not-a-gloss -- the bare etymon
# "pius" on *pietas*, the headword echoed back, "false reading in Vitruvius",
# a truncation fragment, a part-of-speech description -- is not one. Those
# rows are left out and the app's own Whitaker data fills the gap. Detectors
# that flag a gloss as merely imperfect (a diacritic left in, an adverb given
# its verb's sense, the headword in front of a real gloss) do not exclude it.
NOT_A_GLOSS = {'etymology-leak', 'bare-echo', 'editorial-apparatus', 'fragment', 'word-class', 'form-note'}
# An adverb entry that is a cross-reference inherits its target's gloss whatever
# the target is: `magis` ("v. magnus") shipped as "great, large, vast", `vero`
# as "true, real, genuine", `celeriter` as "swift, fleet, quick". An adverb
# glossed as an adjective or a verb is wrong for a reader, and the app's own
# data has the adverb; the row is left out.
FUNC_POS = ('conj', 'praep', 'adv', 'pron', 'interj', 'num')
def _pos(i):
    return pos_marker(bodies[i])
def _head_pos(i):
    """The part-of-speech marker in the headword line itself: parentheses
    removed (L&S opens `Cum` with a 120-character note on spelling) and read
    only from the first 60 characters, so a marker inside a citation further
    on (`os, ossis ... Varr. ap. Charis.` is not an adverb) does not count."""
    head = re.sub(r'\([^()]*\)', ' ', bodies[i])
    return pos_marker(head[:60])
def _is_function(i, _hop=True):
    # the entry for the letter `a` reads "indecl." and is not the preposition
    if _head_pos(i) in FUNC_POS or (function_entry(focus(bodies[i])) and len(letters(rows[i][1])) > 1):
        return True
    # a bare pointer to a function word (`uti`, "v. ut init.") is one too; a
    # prefix note (`sum-`, "in composition, for sub") or a form note
    # ("sum = eum, v. is") is not a word at all
    b = bodies[i]
    return (_hop and i in target_row and len(b) < 60 and '=' not in b
            and not rows[i][1].rstrip().endswith('-') and _is_function(target_row[i], _hop=False))
# which entry each pointer entry finally points at, following "v. ego" up to
# four hops -- but only while the entry reached is itself a pointer: a
# substantive article cites other entries ("v. bellus" inside *bonus*), and
# hopping on from there sent *melius* to *bellum*.
POINTER_MAX = 200
_xrefs = XrefIndex(rows, bodies)
target_row = {}
for _i in range(len(rows)):
    if len(bodies[_i]) >= POINTER_MAX: continue
    _j, _seen = _i, {_i}
    for _ in range(4):
        _n = _xrefs.target_of(_j)
        if _n is None or _n in _seen: break
        _seen.add(_n); _j = _n
        if len(bodies[_j]) >= POINTER_MAX: break
    if _j != _i: target_row[_i] = _j
vocab = gloss_vocabulary(rows)
by_lemma = collections.defaultdict(list)
excluded = collections.Counter()
dropped_lemmas = 0
bad_row = {}
for i, r in enumerate(rows):
    g = r[2].strip()
    if not g: continue
    bad = None
    if r[3].endswith('!'):                                   # unresolved rows excluded
        bad = 'unresolved (!)'
    elif not A.keep_flagged:
        if '?' in r[3]:
            bad = 'ungrounded (?)'
        else:
            why = NOT_A_GLOSS & set(suspect_reasons(r[1], g, r[3], bodies[i], vocab))
            if why: bad = 'detector: ' + ','.join(sorted(why))
            elif (r[3].startswith('xref') and _pos(i) == 'adv' and i in target_row
                  and _pos(target_row[i]) != 'adv' and not function_entry(focus(bodies[target_row[i]]))):
                bad = 'adverb inherits a non-adverb'
            # the detectors compare against the headword; the lemma is the key
            # with its number stripped, and a gloss that merely repeats THAT
            # ("Gnidus" for gnidus) is as empty as the headword echoed
            elif letters(g) == letters(re.sub(r'\d+$', '', r[0])):
                bad = 'echoes the lemma'
    if bad:
        bad_row[i] = bad
# A cross-reference that inherited a gloss the detectors reject is rejected
# with it: `a` ("prep. = ab, v. ab") carried a copy of *ab*'s gloss.
for i, j in target_row.items():
    if (i not in bad_row and bad_row.get(j, '').startswith('detector')
            and rows[i][3].startswith('xref') and rows[i][2].strip()):
        bad_row[i] = 'inherits a rejected gloss'
for bad in bad_row.values():
    excluded[bad] += 1
for i, r in enumerate(rows):
    g = r[2].strip()
    if not g: continue
    bad = bad_row.get(i)
    sc = scores.get(r[0])
    if sc is not None and sc < A.min_score: continue
    lem = plain(re.sub(r'\d+$', '', r[0])) or plain(r[1])
    mnum = re.search(r'(\d+)$', r[0])
    hnum = int(mnum.group(1)) if mnum else 0
    # A cross-reference entry is a pointer, not a sense a reader looks up:
    # litus1 is "Part., from lino" while litus3 is "sea-shore" -- the noun is
    # what appears in running text. Rank pointer entries last.
    pointer = 1 if r[3].startswith('xref') else 0
    # Article length is the best available proxy for which sense a reader meets.
    # L&S gives its most-used senses the longest treatment: litus3 "sea-shore"
    # runs far longer than litus2 "a smearing". Homograph numbering does not
    # track usage -- litus1 is merely a participle.
    elen = len(bodies[i])
    if lem: by_lemma[lem].append((sc if sc is not None else 3, g, i, hnum, pointer, elen, bad, r[0]))
for what, n in excluded.most_common():
    print(f"glosses excluded, {what}: {n:,}", file=sys.stderr)

homograph_lemmas = {lem for lem, items in by_lemma.items() if len(items) > 1}

# Every paradigm, built once. lemma_frequencies used to build all 51,643 of them
# a second time for the frequency weighting, doubling the build.
paradigms = {}
for _body, r in zip(bodies, rows):
    lem = plain(re.sub(r'\d+$', '', r[0])) or plain(r[1])
    paradigms[r[0]] = forms_with_morph(r[1], _body[:200], pos_text=_body,
                                       strict_gender=lem not in homograph_lemmas)

# How often each ENTRY's own forms occur in the corpus (per numbered key, so
# `sero1` and `sero2` are told apart where their paradigms differ).
_bykey = {}
if A.freq:
    from lemmafreq import load_form_counts, lemma_frequencies
    _counts = load_form_counts(A.freq)
    _bykey = lemma_frequencies(rows, bodies, _counts, paradigms)

# Perseus treebanks carry human-verified form/lemma pairs. They generalise: "cui"
# is a form of qui in every text, not only the annotated ones. Their lemmas also
# carry L&S's own homograph numbers (`magnus1` 241 tokens, `Magnus2` 2), which
# is a direct count of which sense readers meet. Read once here; the rows are
# added to the morphology below, after the dictionary keys exist.
def _numbered(lemma):
    """`Magnus2` -> `magnus2`: the join key with its homograph number kept."""
    m = re.match(r'(.*?)(\d*)$', lemma)
    return plain(m.group(1)) + m.group(2)

tb_counts = collections.defaultdict(collections.Counter)
tb_tags = collections.defaultdict(collections.Counter)
tb_entry = collections.Counter()
n_tb = 0
if A.treebank:
    import glob as _glob
    for fp in _glob.glob(str(Path(A.treebank) / '*.xml')):
        try:
            with open(fp, encoding='utf-8', errors='ignore') as fh: raw = fh.read()
        except Exception: continue
        for w in re.findall(r'<word\b[^>]*/?>', raw):
            fm = re.search(r'\bform="([^"]*)"', w); lm = re.search(r'\blemma="([^"]*)"', w)
            if not (fm and lm and fm.group(1) and lm.group(1)): continue
            form, lemma = plain(fm.group(1)), plain(re.sub(r'\d+$', '', lm.group(1)))
            tb_counts[form][lemma] += 1
            tb_entry[_numbered(lm.group(1))] += 1
            # the annotators' own parse of this token: the morphology is in the
            # source and only had to be read off it
            pt = re.search(r'\bpostag="([^"]*)"', w)
            if pt and pt.group(1).strip('-'): tb_tags[(form, lemma)][pt.group(1)] += 1
            n_tb += 1
    print(f"treebank pairs read: {n_tb:,}", file=sys.stderr)

# Homographs. L&S has four unrelated `sero` entries and sixteen `in`; keying on
# the bare headword silently drops all but one (2,164 entries for this corpus).
# The format has no disambiguator field, so it has to live in the lemma string:
# the primary sense keeps the bare lemma, so ordinary lookup still finds it, and
# the others are retained as lemma2, lemma3 ... so nothing is lost from the
# dictionary panel.
definitions = {}
# row index -> the key its gloss ships under (`sion` or `sion2`), and the row
# whose entry is the primary sense of each bare lemma
dictkey, primary_row = {}, {}
homograph_kept = homograph_extra = 0
decided = collections.Counter()               # which signal chose the primary sense
TB_MIN_TOKENS, TB_MARGIN = 5, 2               # the annotators' count decides when it is this clear
for lem, items in by_lemma.items():
    # Which sense is the primary. A substantive sense before a pointer, then the
    # longest article (L&S gives its most-used senses the longest treatment),
    # then gloss score. Where one of the homographs is a proper name -- `Magnus`
    # beside *magnus*, `Castor` beside the beaver -- article length is a poor
    # guide, and the treebank annotators' count decides first when it is
    # decisive: their lemmas carry L&S's own numbers (`magnus1` 241 tokens,
    # `Magnus2` 2). The per-entry corpus frequency was tried as a second signal
    # and dropped: it attributes a shared form to one entry, so homographs that
    # decline alike came out arbitrarily (`flamen` "blowing, blast", `spongia`
    # "proper name"). Common-word homographs keep the article rule, by
    # decision, 2026-09-13.
    # L&S keys the conjunction `Cum2` with a capital; a capitalised headword
    # whose entry carries a function-word marker is not a name
    def _is_name(i):
        return (is_name_entry(rows[i][1]) and not function_entry(focus(bodies[i]))
                and pos_marker(bodies[i]) not in ('conj', 'praep', 'adv', 'pron', 'interj', 'num'))
    # A function word leads its homographs by default: the adverb `vero` over
    # the verb "to speak the truth", the conjunction `nec` over the prefix,
    # `magis` over the dish. A reader meets the function word thousands of
    # times and the content word seldom, and the article rule ranked the
    # pointer entries these usually are last. Where the function-word entry
    # is then excluded (an adverb inheriting an adjective), the lemma goes
    # to the app's own data rather than to the content word.
    for t in items:
        if _is_function(t[2]) and not _is_name(t[2]):
            items[items.index(t)] = t[:4] + (-1,) + t[5:]      # ahead of substantives and pointers
    named = any(_is_name(t[2]) for t in items)
    decisive = named and len(items) > 1
    if decisive:
        # ...and only where a name is one of the two contenders: a name against
        # a common word (`Crassus` / *crassus*) or a name against a name
        # (`Gallus` the Gaul against the river, `Teucer` the Trojan ancestor
        # against the son of Telamon). A vote between two common words stays
        # with the article rule even when a name homograph exists elsewhere in
        # the group.
        by_tb = max(items, key=lambda t: (-t[4], tb_entry.get(_numbered(t[7]), 0), t[5]))
        by_art = max(items, key=lambda t: (-t[4], t[5], t[0]))
        lead, held = tb_entry.get(_numbered(by_tb[7]), 0), tb_entry.get(_numbered(by_art[7]), 0)
        # decisive against the article winner: enough tokens, and the article
        # winner has under half of them (`Gallus` the Gaul 9 tokens, the river 0;
        # the surname's 7 do not matter)
        decisive = (by_tb is not by_art and lead >= TB_MIN_TOKENS and held * TB_MARGIN < lead
                    and (_is_name(by_tb[2]) or _is_name(by_art[2])))
    if decisive:
        items.sort(key=lambda t: (t[4], -tb_entry.get(_numbered(t[7]), 0), -t[5], -t[0], len(t[1])))
    else:
        items.sort(key=lambda t: (t[4], -t[5], -t[0], len(t[1])))
    if named and len(items) > 1:
        a, b = items[0], items[1]
        if a[4] != b[4]: decided['pointer'] += 1
        elif decisive and tb_entry.get(_numbered(a[7]), 0) != tb_entry.get(_numbered(b[7]), 0): decided['treebank'] += 1
        else: decided['article length'] += 1
    # An excluded gloss takes its lemma with it when it is the PRIMARY sense.
    # Dropping only the row let the next homograph move up: with *pietas*
    # ("pius") gone, `pietas` was defined as "Roman surname, a ship" -- the
    # name of the personification -- which is worse for a reader of Cicero
    # than no entry at all. Whitaker's own data supplies the common word. An
    # excluded minor homograph is simply left out.
    # ...with one refinement: when the excluded primary is a function-word
    # entry (an adverb that inherited its adjective's gloss), the next
    # homograph takes over unless the function word is what readers meet --
    # `sero` keeps its verb (the adverb *sero* has 1 token, the verb 7), while
    # `magis` (the adverb 53, the dish 2) goes to the app's own data.
    while items[0][6] and _is_function(items[0][2]) and not _is_name(items[0][2]):
        rest = [t for t in items[1:] if not t[6]]
        if not rest or tb_entry.get(_numbered(items[0][7]), 0) > tb_entry.get(_numbered(rest[0][7]), 0):
            break
        items = items[1:]
    if items[0][6]:
        dropped_lemmas += 1
        continue
    items = [t for t in items if not t[6]]
    definitions[lem] = (items[0][1], items[0][0])
    dictkey[items[0][2]] = lem; primary_row[lem] = items[0][2]
    homograph_kept += 1
    for n, (sc, g, _i, *_rest) in enumerate(items[1:], start=2):
        definitions[f"{lem}{n}"] = (g, sc)
        dictkey[_i] = f"{lem}{n}"
        homograph_extra += 1
print(f"lemmas left to the app's own dictionary (primary gloss excluded): {dropped_lemmas:,}",
      file=sys.stderr)
print("primary sense of a name homograph decided by: " + ", ".join(f"{k} {v:,}" for k, v in decided.most_common()),
      file=sys.stderr)
print(f"lemmas: {homograph_kept:,} primary + {homograph_extra:,} homograph senses retained",
      file=sys.stderr)

# ---------------------------------------------------------------- morphology.csv
# every inflected form we can derive, mapped to the same lemma spelling
# How often each lemma's own headword occurs in real Latin. When two lemmas claim
# the same inflected form -- "cui" from both qui and Spaco, "mari" from mare and
# Marus -- the obscure one should lose. Without this, a rare word's paradigm can
# capture a form that belongs to one of the commonest words in the language.
lemma_freq = {}
if A.freq:
    for _i, _r in enumerate(rows):
        _lem = plain(re.sub(r'\d+$', '', _r[0])) or plain(_r[1])
        # lemma_frequencies is keyed per entry; the max below is what
        # turns that back into a per-lemma figure for the dictionary key
        _v = _bykey.get(_r[0], 0)
        if _v: lemma_freq[_lem] = max(lemma_freq.get(_lem, 0), _v)
        # a numbered key is one entry, and gets that entry's own figure
        _k = dictkey.get(_i)
        if _v and _k and _k != _lem: lemma_freq[_k] = _v
    print(f"lemma frequencies loaded for {sum(1 for v in lemma_freq.values() if v):,} lemmas",
          file=sys.stderr)

import math
def freq_weight(lemma):
    """0.5 for a lemma never seen in the corpus, rising to ~1.0 for common ones."""
    n = lemma_freq.get(lemma, 0)
    if not lemma_freq: return 1.0
    return 0.5 + 0.5 * min(1.0, math.log10(n + 1) / 4.0)

# form -> {lemma: (confidence, note)}. An ambiguous form keeps ALL its candidate
# lemmas, not just the winner: `oris` is a real form of both os ("mouth") and ora
# ("shore"), and which one is meant depends on the sentence. The format ranks
# candidates by confidence rather than demanding a single answer, so discarding
# the alternatives throws away information the app is built to use.
# -que and -ve are words. L&S glosses them ("co-ordination of words", "choice
# between two"), so the join target for the second half of `virumque` exists.
ENCLITIC_LEMMA = {'que': 'que', 've': 've'}
# every lemma as it would be spelled in the word_form column
lemma_forms = {fold(k) for k in definitions}

forms = collections.defaultdict(dict)
MAX_CANDIDATES = 3
def add(form, lemma, conf, morph, origin, weighted=True):
    """Record `form` as a form of `lemma`.

    `morph` is what the form IS -- "dat/abl p", "3 s pres act ind" -- and is the
    only thing that reaches morphology.csv. `origin` is how we came to believe
    it (treebank, generated paradigm, ...) and stays in this process, reported
    to stderr at the end of the build. The two used to be one argument written
    to the `morph_info` column, so every one of the 1.5M shipped rows told the
    reader which stage of this script produced it and nothing about the word."""
    # forms always resolve to the primary sense; the numbered ones exist so the
    # dictionary panel can show them, not to be matched from running text
    # Stored forms use one convention (i/u); normalization_rules.csv folds the
    # reader's j/v spelling onto it. Trying to store both spellings by blind
    # letter substitution corrupts words ("uirumque" -> "virvmqve").
    form = fold(form.lstrip('-'))
    if not form or not lemma or lemma not in definitions: return
    if len(form) < 2 or len(form) > 40: return
    # The particle is an enclitic whatever produced the row: the treebank tags
    # the bare `que` and `ue` "conj", and those three rows were the only ones
    # under the lemma that did not carry the marker.
    if lemma in ENCLITIC_LEMMA.values(): morph = ENCLITIC_MORPH
    # Treebank pairs already record which lemma this FORM actually is, counted in
    # real text, so lemma frequency must not override them: `os` is the commoner
    # word overall, but `oris` is annotated as *ora* three times to *os* once.
    eff = conf * freq_weight(lemma) if weighted else conf
    cur = forms[form].get(lemma)
    if cur is None:
        forms[form][lemma] = (eff, morph, origin)
        return
    # Confidence ranks the LEMMA; it does not choose between readings. Both
    # sources are describing the same form of the same word, so the readings
    # union rather than compete: a treebank tag records what `portis` was in the
    # passages Perseus annotated (ablative), and on its own it would replace the
    # paradigm's full "abl p f|dat p f|loc p f" -- telling a reader whose
    # sentence has the dative that the form is ablative.
    merged = merge_morph(cur[1], morph)
    forms[form][lemma] = ((eff, merged, origin) if eff > cur[0]
                          else (cur[0], merged, cur[2]))

for i, (e, r) in enumerate(zip(ents, rows)):
    lem = plain(re.sub(r'\d+$', '', r[0])) or plain(r[1])
    if lem not in definitions: continue
    # An entry's gender speaks for its own sense only. Where L&S has several
    # entries under one lemma -- the proper noun `Magnus` beside the adjective
    # `magnus, a, um` -- the paradigm of one must not deny the genders of the
    # other, so the gender filter is switched off for those lemmas (see the
    # `strict_gender` argument where `paradigms` is built).
    paradigm = paradigms[r[0]]
    # A form only a minor homograph makes resolves to that homograph's key.
    # L&S has sĭon, ii, n. (water-parsley) and Sīon, ōnis (Jerusalem); the
    # neuter's *sii*, *sio*, *sia* were filed under the primary `sion` and a
    # reader of Pliny was told water-parsley is a hill of Jerusalem. The
    # numbered keys are in dictionary.csv, so the join holds. A form both
    # paradigms make (`sion` itself) still leads to the primary sense.
    key = dictkey.get(i, lem)
    own = None
    if key != lem:
        own = {f for f in paradigm if f not in paradigms[rows[primary_row[lem]][0]]}
    # The headword's own spellings. Take the label from the paradigm where a slot
    # produces the same string -- `porta` is the nominative singular and saying so
    # is more use than repeating that it is the headword.
    # forms_with_morph gives the headword its own reading -- the paradigm slot
    # that names it, or the entry's category where no paradigm could be built --
    # so the lemma spelling falls back to whatever the folded headword got.
    head_morph = paradigm.get(fold(r[1]), '')
    for hw in (plain(r[1]), lem):
        add(hw, lem, 1.0, paradigm.get(fold(hw), head_morph), 'headword')
    for f, minfo in paradigm.items():
        # Very short generated forms collide across unrelated words -- a 3-letter
        # form from an obscure paradigm ("cui" from Spaco) beats nothing and wins
        # by default. Only trust short forms when they ARE the headword.
        conf = 0.85 if len(f) >= 5 else 0.35
        if own is not None and f in own:
            add(f, key, conf, minfo, 'generated paradigm (minor homograph)')
        else:
            add(f, lem, conf, minfo, 'generated paradigm')

# Perseus treebanks carry human-verified form/lemma pairs. They generalise: "cui"
# is a form of qui in every text, not only the annotated ones. Highest confidence,
# so they override generated paradigms and model guesses alike.
if A.treebank:
    # rank the candidates for each form by how often the treebanks chose each one
    for form, cnt in tb_counts.items():
        total = sum(cnt.values())
        for lemma, k in cnt.items():
            # One form/lemma pair can be annotated with more than one reading:
            # `oris` is genitive singular in most passages and nominative plural
            # in a few. Ship the commonest, ties broken on the tag string so a
            # rebuild from the same treebanks is byte-identical.
            tags = tb_tags.get((form, lemma))
            tag = max(tags.items(), key=lambda kv: (kv[1], kv[0]))[0] if tags else ''
            add(form, lemma, 0.90 + 0.09 * (k / total), postag_morph(tag), 'treebank',
                weighted=False)

try:
    with open(A.lemma_map, encoding='utf-8') as fh:
        for l in fh:
            if l.startswith('#'): continue
            f = l.rstrip('\n').split('\t')
            if len(f) >= 3:
                # The model was asked which headword the form belongs to, not
                # what the form is, so no morphology is known here. `morph_info`
                # is optional in the format; an empty cell is the honest answer
                # and beats inventing a parse for a row that exists because the
                # regular paradigms could not produce it.
                add(plain(f[0]), plain(re.sub(r'\d+$', '', f[2])), 0.5, '', 'model lemma')
except FileNotFoundError:
    print("note: no lemma map found, skipping irregular forms", file=sys.stderr)

# ---------------------------------------------------------------- the annotators' majority leads
# A headword row is added at confidence 1.0, so an obscure entry that happens
# to spell a pronoun form outranked the treebank's row for the real word: `se`
# led with the prefix ("sine, without, aside") over *sui*, `hoc` with the
# adverb over *hic*, `ac` with "sharp" over *atque*, `te` with the enclitic
# suffix over *tu* -- 179,006 corpus tokens, 2.6% of running Latin, on 29
# forms. Two rules, both from the annotators' count for the form:
#
# 1. Where they assign a form to one lemma by a two-thirds majority (at least
#    TB_MIN_TOKENS tokens), that lemma's row leads and every other candidate
#    ranks below it.
# 2. Where that lemma is not in the dictionary -- *suus* was left to the app's
#    own data because its gloss was a word-class description -- the form ships
#    NO row rather than a wrong one: `suo` was "to stitch", `suae` "a town in
#    Assyria", `suum` "swine". The one exception is an entry that is itself a
#    cross-reference to the missing lemma (`me`, "v. ego"), whose gloss is the
#    right word's.
tb_major = {}
for _form, _cnt in tb_counts.items():
    _total = sum(_cnt.values())
    if _total < TB_MIN_TOKENS: continue
    _lemma, _k = _cnt.most_common(1)[0]
    if 3 * _k >= 2 * _total: tb_major[_form] = _lemma
# which bare lemma each entry points at (`target_row`, above). Every entry is
# read, not only the rows glossed by resolution: `mecum` ("cum me, v. ego")
# carries a model gloss and is a pointer all the same.
pointer_target = collections.defaultdict(set)
for _i, _j in target_row.items():
    pointer_target[plain(re.sub(r'\d+$', '', rows[_i][0])) or plain(rows[_i][1])].add(
        plain(re.sub(r'\d+$', '', rows[_j][0])) or plain(rows[_j][1]))
n_lead = n_noform = n_dropped = 0
for _form, _maj in tb_major.items():
    if _form not in forms: continue
    _bare = {lem: re.sub(r'\d+$', '', lem) for lem in forms[_form]}
    if _maj in _bare.values():
        # the bare key is the primary sense and leads; a numbered key of the
        # same word (`alius2` "Elian", `populus2` "poplar") ranks just below it
        for lem, (conf, morph, origin) in list(forms[_form].items()):
            forms[_form][lem] = ((1.0, morph, origin) if lem == _maj
                                 else (0.99, morph, origin) if _bare[lem] == _maj
                                 else (min(conf, 0.89), morph, origin))
        n_lead += 1
    else:
        for lem in list(forms[_form]):
            if _maj not in pointer_target.get(_bare[lem], ()):
                del forms[_form][lem]; n_dropped += 1
        if not forms[_form]:
            del forms[_form]; n_noform += 1
print(f"annotators' majority: leads on {n_lead:,} forms; {n_dropped:,} rows dropped on {n_noform:,} forms "
      f"whose lemma is not in the dictionary", file=sys.stderr)

# -que and -ve attach to the inflected form: virum -> virumque. The enclitic
# does not change the host's case or tense, so the host's reading carries over
# unaltered. This runs after EVERY source has loaded: joined only to paradigm
# forms, `idque`, `eoque`, `hocque` and `cuique` -- whose hosts come from the
# treebank and the lemma map -- never existed.
#
# No host, no joined form. `add` rejects a form under two letters or a lemma
# with no dictionary row, and `f` can fail those while `f + que` passes them on
# length -- which would index `virumque` as a word whose first half the reader
# cannot look up. Iterating over what `forms` holds is what guarantees the host.
n_joined = 0
for f in list(forms):
    if split_enclitic(f)[1]:
        continue                                  # already a joined form
    for lem, (_eff, minfo, origin) in list(forms[f].items()):
        if lem in ENCLITIC_LEMMA.values():
            continue
        for enc in ENCLITIC_LEMMA:
            joined = fold(f + enc)
            # Only make a joined form we would split back. `split_enclitic`'s
            # length guard is what keeps `usque`, `namque`, `itaque` and
            # `quoque` -- words in their own right -- from being treated as a
            # host plus an enclitic.
            if split_enclitic(joined) != (f, enc): continue
            # A form that is itself a headword is that word, not this one
            # glued to an enclitic: `denique` is an adverb, not `deni` + -que,
            # and it has its own entry and its own gloss for the reader.
            if joined in lemma_forms: continue
            add(joined, lem, 0.75, minfo, f'host + -{enc}')
            # The enclitic is a SEPARATE WORD, and until now nothing recorded
            # it: a reader meeting `virumque` was told it is a form of *vir*
            # and never learnt there is an "and" in the token. Both parts are
            # emitted, the enclitic ranked below the host so ordinary lookup
            # still leads with the word being inflected. 0.30 is below the
            # floor a weighted host can reach (0.75 x the 0.5 minimum frequency
            # weight = 0.375), so the host wins even for a lemma the corpus
            # never attests. Its reading says what it is -- "conj enclitic" --
            # so a consumer can tell the two rows of `ductoresque` apart
            # without guessing from the lemma's spelling.
            add(joined, ENCLITIC_LEMMA[enc], 0.30, ENCLITIC_MORPH, 'enclitic',
                weighted=False)
            n_joined += 1
print(f"enclitic forms joined: {n_joined:,}", file=sys.stderr)

# ---------------------------------------------------------------- write the zip
Path(A.out).parent.mkdir(parents=True, exist_ok=True)
def csv_bytes(header, rowiter):
    import io
    buf = io.StringIO(); w = csv.writer(buf, lineterminator='\n')
    w.writerow(header)
    n = 0
    for row in rowiter: w.writerow(row); n += 1
    return buf.getvalue().encode('utf-8'), n

dict_bytes, n_dict = csv_bytes(
    ['lemma', 'language', 'definition', 'source_name'],
    ([lem, 'latin', d, A.source] for lem, (d, _s) in sorted(definitions.items())))
# An enclitic row is only as good as its host. `virum` may lose its place among
# a form's three candidates while `virumque`, which fewer lemmas compete for,
# keeps it -- leaving a joined form whose first half the reader cannot look up.
# This has to run after the cap, because the cap is what drops the host.
def _capped(form):
    return sorted(forms[form].items(), key=lambda kv: -kv[1][0])[:MAX_CANDIDATES]

_shipped = {f: {lem for lem, _ in _capped(f)} for f in forms}
_orphaned = 0
for _f in list(forms):
    _stem, _e = split_enclitic(_f)
    if not _e: continue
    for _lem, (_eff, _morph, _origin) in list(forms[_f].items()):
        # only rows this script joined; a word that merely ends in these letters
        # (`abusque`, the vocative `ablatiue`) is indexed on its own account
        if not _origin.startswith('host + -'): continue
        if _lem not in _shipped.get(_stem, ()):
            del forms[_f][_lem]; _orphaned += 1
    # Nothing but the enclitic left means there is no host at all, and a token
    # that resolves only to "and" is no use to a reader. Judged on the lemma
    # rather than on which stage produced the row: the treebanks annotate
    # `tinuoque` to `que` with no host entry anywhere, and that row is as empty
    # as one we joined ourselves.
    if (_f not in lemma_forms and forms[_f]
            and all(_l in ENCLITIC_LEMMA.values() for _l in forms[_f])):
        _orphaned += len(forms[_f]); del forms[_f]
print(f"enclitic rows dropped for a missing host: {_orphaned:,}", file=sys.stderr)

origin_counts = collections.Counter()
def _morph_rows():
    for f in sorted(forms):
        cands = sorted(forms[f].items(), key=lambda kv: -kv[1][0])[:MAX_CANDIDATES]
        for lem, (conf, morph, origin) in cands:
            origin_counts[origin] += 1
            if not morph: origin_counts['(no morph_info)'] += 1
            yield [f, lem, 'latin', morph, f"{min(1.0, conf):.2f}", A.source]

morph_bytes, n_morph = csv_bytes(
    ['word_form', 'lemma', 'language', 'morph_info', 'confidence', 'source_name'],
    _morph_rows())
# fold the macrons and breves L&S prints, so a reader's typed query matches
norm_rows = [['latin', '[āăá]', 'a', 'fold long/short a', '10'],
             ['latin', '[ēĕé]', 'e', 'fold long/short e', '10'],
             ['latin', '[īĭí]', 'i', 'fold long/short i', '10'],
             ['latin', '[ōŏó]', 'o', 'fold long/short o', '10'],
             ['latin', '[ūŭú]', 'u', 'fold long/short u', '10'],
             ['latin', '[ȳy̆ý]', 'y', 'fold long/short y', '10'],
             ['latin', 'j', 'i', 'fold j to i', '20'],
             ['latin', 'v', 'u', 'fold v to u', '20']]
norm_bytes, n_norm = csv_bytes(
    ['language', 'pattern', 'replacement', 'description', 'priority'], norm_rows)

with zipfile.ZipFile(A.out, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('dictionary.csv', dict_bytes)
    z.writestr('morphology.csv', morph_bytes)
    z.writestr('normalization_rules.csv', norm_bytes)
print(f"dictionary.csv          {n_dict:,} lemmas")
print(f"morphology.csv          {n_morph:,} forms")
# Provenance is a fact about this build, not about the Latin, so it is reported
# here instead of being written into every shipped row.
for origin, n in origin_counts.most_common():
    print(f"  {origin:<22} {n:>9,}", file=sys.stderr)
print(f"normalization_rules.csv {n_norm} rules")
print(f"-> {A.out} ({Path(A.out).stat().st_size/1e6:.1f} MB)")
