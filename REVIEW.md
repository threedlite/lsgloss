# lsgloss review — improving gloss quality

Reviewed the pipeline and audited the shipped `out/ls_glosses.tsv` (51,643 rows)
weighted by corpus frequency, since that is the metric that decides what a reader
actually meets. No files were changed.

**Updated 2026-09-11.** The fixes below were then applied; after that, the
`morph_info` column of the shipped package was repaired as a separate task
(`MORPHOLOGY_TRACKING.md`). That work changed `inflect.py` substantially and
lifted the share of corpus tokens that resolve to a lemma from 61% to 74%, which
moves every token-weighted number in this review. See **[Since this review: the
`morph_info` fix](#since-this-review-the-morph_info-fix)** for the current state.
The gloss findings are unchanged — no gloss changed — and the paradigm findings
(3b, 10, 11) went further than what is recorded against them here.

**Updated 2026-09-12.** A second review (see `README.md`, *Revision 2026-09-12*,
and `baseline/changelog/15-*.txt`, `16-*.txt`) accepted the stale baseline, fixed
the word-cap truncation, the cross-reference false targets, the checkpointing of
failures, and the paradigm stems recorded below as 3b/13-adjacent, and changed
what `package.py` ships. Finding 13 (compound verb principal parts) is still
open. Test counts in this file are as of the date each section was written; the
suite is 254 tests, 3 expected failures.

## Regression harness (built first, before any fix)

Nothing in this repo previously guarded the model-free code: `make test` was a
500-entry run against a live model, and there were no unit tests at all. A fix to
`clean_gloss` or `inflect` rewrites the whole corpus at once, and the failure mode
is silent — a paradigm that stops generating a form does not raise, the reader
just gets nothing. So the harness came first.

```bash
make check      # suite + corpus diff, no model, no network, ~45s
make test       # 145 unit/integration tests
make regress    # diff every model-free function over all 51,643 entries
make baseline   # rewrite the baseline, after reviewing the diff
```

**Three layers.**

1. **Unit tests** (`lsgloss/tests/`) pin behaviour the README documents as
   deliberate — the three normalisers staying distinct, citation stripping that
   keeps register labels, `v.` as *verbum* not *vide*, the `vigintivir` compound
   guard, `-ne` never being split as an enclitic. Also `common.chat`, including
   the missing-`content` case that used to crash `refine.py` and `score.py`.

2. **Corpus characterisation** (`lsgloss/regress.py`) runs eight probes over all
   51,643 entries and diffs against a committed baseline. The cleaner probes read
   `out/ckpt.jsonl` — 64,007 *raw* model replies — because the shipped TSV has
   already been cleaned and probing it tests nothing. The point is not that the
   diff stays empty; every fix below is meant to change rows. The point is that a
   fix which should touch 3 rows can be *shown* to touch 3 rows.

3. **Scripted-model integration** (`lsgloss/tests/fakemodel.py`) runs the real
   `freqfix.py` against a fake llama-server, so targeting and accept/reject
   decisions are covered without a model and without refactoring the script.

**Verified to go red.** Applying finding 2's one-line fix produced exactly this,
then was reverted:

```
  clean      CHANGED  +4 -0 ~0  (baseline 4,837 -> 4,841)
      + main:16299: and (conjunction)	->	and
      + main:15360: holla! or soho! (interjection)	->	holla! or soho!
      + adapt:2150: around (preposition)	->	around
      + main:50321: ve- (particle)	->	ve-
  [all seven other probes unchanged]
```

**Each finding has an executable spec.** `tests/test_findings.py` holds one test
per defect, marked `@unittest.expectedFailure`, so the suite is green against
current code. When a fix lands the test reports an *unexpected success*, which
fails the run and forces the marker to be deleted — a fix cannot be declared done
without something asserting it. Each spec is paired with a guard test that pins
what must **not** change: the metalinguistic detector must not fire on `from, away
from`; the headword-echo detector must not fire on `orator -> speaker, orator`.

**A metrics baseline** (`baseline/metrics.json`) freezes every defect count and
`form_coverage_tokens`. `make regress` flags any metric that moves the wrong way,
so a fix that repairs one class while breaking another is caught even when the
per-probe diffs look reasonable in isolation.

What this does **not** cover: gloss *content* regression from a changed prompt
still needs a model run against `eval/gold.tsv`. The harness covers the
deterministic 80% — which is where all twelve findings below live (finding 13
was added later and has no spec yet).


## Status

| # | finding | state |
|---|---|---|
| 1 | metalinguistic glosses on function words | **mostly fixed** — one sub-case open |
| 2 | `POSNOTE` misses function-word classes | **fixed** |
| 3a | homographs collapse onto one frequency key | **fixed** |
| 3b | abbreviated genitive mis-stems (`Spāco` -> `c`) | **fixed** for nouns — verbs open, see 13 |
| 4 | cross-reference ignores case and word class | **fixed** — `xrefix.py`, 138 rows |
| 5 | etymology leaking into glosses | **mostly fixed** — bracketed case open |
| 6 | leading headword echo | **mostly fixed** — one sub-case open |
| 7 | `freqfix` accept test favours the challenger | **fixed**, but stage stays off — see below |
| 8 | blank token in the frequency list | **fixed and regenerated** |
| 8b | 828 lemmas with no gloss | **partly fixed** — 63 filled, 815 remain |
| 9 | stale duplicate `prompts/` directory | **withdrawn — I was wrong, see below** |
| 10 | 5th-declension branch unreachable | **fixed** |
| 11 | verb ending tables unfolded | **fixed** |
| 12 | `enforce` emits a dangling article | **fixed** |
| 13 | abbreviated verb principal parts taken literally | **open — found 2026-09-11** |

Nine fixed, done one at a time with the corpus diff reviewed and recorded under
`lsgloss/baseline/changelog/` before each baseline was accepted. `make check` is
green: **153 tests, 4 expected failures** (down from 21).

Three new detectors now flag classes nothing saw before — these are not
regressions, they are the detectors' scope widening onto pre-existing defects:

| detector | rows | tokens |
|---|---|---|
| `etymology-leak` | 334 | 2,630 |
| `head-echo` | 59 | 15,067 |
| `word-class` (extended) | 7 -> 17 | 97 -> 223,056 |

Two cautions on that table. The token counts are as of this review, and
`etymology-leak` and `head-echo` have since risen with wider lemma attribution
without any gloss changing — see the `morph_info` section. The `word-class`
figure of 223,056 is a *pre-fix* measurement: it still counted `et`
"and (conjunction)" and its 189,485 tokens, which finding 2's fix then cleaned.
The committed baseline records 36,847 for that detector, and it is 36,880 now.

### What is still open, and why

- **`ab` -> "departure from a fixed point"** names no word class and uses no
  metalinguistic verb; it is an ordinary noun phrase. Every rule that catches it
  also flags `sed` -> "but, yet, except" and `per` -> "through, across" — about 75
  false positives against a handful of true ones. Left to the prompt and judge.
- **`tamen` -> "tamen, nevertheless"** is missed because one other entry
  (*attamen*, which inherits it) uses `tamen` in its gloss, so the vocabulary test
  reads it as English. Loosening the threshold also catches `angina`, `inertia`
  and `squalor`, which are genuine English. Since `lsgloss.py`'s hard pass accepts
  a replacement with no score gate, a false positive there can come back worse.
  Needs an English wordlist.
- **Finding 4** needs design plus model time, not a detector.
- **The prompt rule for finding 1 was deliberately NOT written.** The README's own
  guidance is that prompt changes for gpt-oss are experiments to be measured
  against `eval/gold.tsv`, not edits. Making one blind would be exactly the
  unmeasured regression risk this whole exercise was meant to avoid.

### Finding 9 was wrong — withdrawn

I claimed the README pointed at a stale duplicate `prompts/` directory. It does
not. `lsgloss/.git` exists, so **`lsgloss/` is the repository root**, and the
README's `prompts/gloss-system.txt` resolves to `lsgloss/prompts/` — the live
copy. The stale directory sits at `../prompts`, outside the repo, untracked and
never shipped. It is only a hazard to someone browsing the working directory. I
have not deleted it; that is your call.

### Data products — regenerated and verified

All three were rebuilt. `out/_backup_prefix/` holds the previous versions.

| file | how | result |
|---|---|---|
| `out/latin_freq.tsv` | `corpusfreq.py` | blank token gone (exactly 9,480 tokens) |
| `out/ls_glosses.tsv` | new `refinalise.py` | 14 definitions improved, incl. `et` and `Cotta` |
| `out/lewis-short-glosses.zip` | `package.py` | +4,717 morphology rows, 686 bogus links dropped |

`refinalise.py` is new: `finalise()` only ran inside a full `lsgloss.py` run, which
rewrites the whole TSV and would have discarded freqfix's 339 repairs. It applies
`clean`+`enforce` to an existing TSV in place — a uniform rule, idempotent, no
model.

**Regression check on the rebuilt ZIP:**

- corpus coverage **80.927% -> 80.929%** (+158 tokens) — flat, no loss
- dictionary: same 50,765 lemmas, 0 removed, 14 definitions improved
- morphology: +5,929 pairs, -1,212, of which **686 were bogus links** now gone
  (`cum`->*Spaco*, `usus`->*abutor*, `factum`->*expergefio*)
- **1,333 forms got a better top-ranked lemma**: `reum`/`reos`/`reis` now resolve
  to *reus* rather than *res*, `reo` to *reor*, `turbatus` to *turbo*
- integrity: 0 dead lemma links, 0 forms over the 3-candidate cap

**One honest caveat.** 408 forms (855 corpus tokens) left the package because the
old paradigm bug was producing them accidentally. Most are junk (`xu`, `xui`,
`cu`), but `aptum` (144 tokens) and `fessum` (79) are real words. They were only
ever covered by wrong links — `aptum` via *apiscor*'s mis-stemmed paradigm — and
their own entries (`aptus, a, um`, `fessus, a, um`) generate no paradigm because
adjectives are not handled. That is a pre-existing gap the fix exposed rather than
caused; net coverage still rose.

**Now closed.** Adjective paradigms were added during the `morph_info` work, and
both words are back from their own entries: `aptum -> aptus` and
`fessum -> fessus`, each with a reading.

### Findings 4 and 8b — `xrefix.py`

A new stage repairs the two classes that needed a model rather than a detector:
cross-references that inherit a gloss across a part-of-speech boundary, and
entries with no gloss at all.

The earlier "adapt" stage tried the first and measured **worse** than doing
nothing (3.91 vs 4.22). Two things were wrong with it, both fixed here:

- It adapted *every* cross-reference. This one selects on a measured signal — the
  entry's own POS marker differing from its target's — which is 1,197 rows of the
  7,756, not all of them.
- It kept whatever came back. This applies verify.py's bar: a replacement is kept
  only if it clears the detectors, an independent judging call scores it >= 4, and
  it beats the incumbent. **777 of 981 candidates were rejected.**

Result: 2,075 targets, **204 kept, 777 rejected, 1,094 unchanged**. Then two more
filters cut it to 201, both found by reading the output rather than by a test:

- **Coined adverbs.** The model returned `bodilyly`, `propheticly`, `adulously`,
  `effusedly`. The adapt prompt forbids coinage and it coined anyway. L&S is
  itself 183,297 distinct English word types, so it serves as the wordlist with no
  new dependency: every real adverb produced appears in it (`gloriously` 4,
  `timidly` 6), every coinage appears zero times. Dropped 32 more.
- **Target echoes.** `Bohemi, v. Boil.` is an OCR error for *Boii*; glossing it
  "boil" is worse than leaving the row empty. 3 rows reverted.

Sample of what landed: `abundans` "overflowing, to abound" -> "abounding",
`athletice` "athletic" -> "athletically", `arbitrario` "arbitration, arbitrating"
-> "arbitrarily", `care` "beloved, dear, precious, valued" -> "dear".

**765 empty rows remain.** They are the ones where the model produced nothing
usable or the judge would not pass it — declining is the designed behaviour, not a
gap to paper over.

### Final package

| | original | final |
|---|---|---|
| corpus coverage | 80.927% | **80.944%** (+1,172 tokens) |
| dictionary lemmas | 50,765 | **50,828** (0 removed) |
| definitions changed | — | 154 |
| morphology rows | 1,536,939 | 1,543,203 |
| dead lemma links | 0 | 0 |
| forms over the 3-candidate cap | 0 | 0 |

`make check`: **166 tests, 3 expected failures**, baseline clean. Both halves of
that are now out of date — 211 tests, and the baseline is intentionally stale on
three probes. See the `morph_info` section.

### freqfix stays off — the window fix exposed a second bias

With finding 7 fixed, a re-run over the top 1,200 lemmas was tried and **its
output was discarded**. It produced 13 changes: about four clear gains (`facile`
"easy, without difficulty" -> "easily", `venenum` "any liquid substance that
powerfully" -> "poison", `sive` "disjunctive conditional particle" -> "either
or") and three clear regressions:

| headword | window 0 says | replaced with | from |
|---|---|---|---|
| `animal` | "a living being, an animal" | "pernicious brute" | deep in the article |
| `accedo` | "to go or come to, to approach" | "agree with, approve of" | char 3,200 |
| `paro` | "to make or get ready, to prepare" | "to procure, acquire, obtain" | char 3,200 |

The cause is a bias I introduced. Finding 7's fix scores each gloss at its own
best window, which removes the challenger's home-turf advantage — but a gloss
extracted from window K always scores well against window K, so taking the
maximum over windows systematically rewards whichever sense sits deepest in the
article. L&S puts the primary sense first, so "best window" is close to "wrong
sense".

The correct rule is probably the earliest window that contains a definition,
judging every candidate against that one window; later windows exist only to
rescue an entry whose opening is pure philology, like `ab`. That is a design
change needing its own measurement, so the stage stays off — as the project's own
history with it already concluded.

`ab` was not repaired: the run rated the replacement no better. Note that
`out/scores_full.tsv` records `ab` -> "from, away from", so the gloss was correct
at some earlier point and an earlier freqfix run replaced it. The regression is
real and still shipping.

### The scores file does not reach the package

`out/scores_full.tsv` is 3.2% stale (1,629 rows record a gloss that has since
changed). It does not matter for the deliverable: building with `--scores` and
without produces **byte-identical** `dictionary.csv` and `morphology.csv`.
Homograph order is decided by pointer-status, then article length, and the score
tiebreak is never reached. Worth knowing before anyone trusts that column.

### Two data directories

Worth knowing: `lsgloss/out/` is the repo's committed copy and `../out/` is where
the pipeline writes. They were identical, and both are now updated. An early
version of `regress.py` preferred the repo copy and so reported "no change" after
a run that had changed 14 rows; it now prefers the working tree and prints every
path it opens.

## Since this review: the `morph_info` fix

The package in the table above was then taken as `.orig` for a separate task:
repairing `morphology.csv`'s `morph_info` column, which shipped pipeline
provenance (`generated paradigm`, `headword`, `treebank` — all 1,543,203 rows)
where `DICTIONARY_IMPORT_FORMAT.md` documents the parse. Full record in
`MORPHOLOGY_TRACKING.md`. Three of its outcomes change what this review says.

**1. It rewrote parts of `inflect.py`, and the paradigm findings here go further
than "fixed" now implies.** Attaching a reading to every ending made the generator
checkable for the first time — `make morphacc` scores it against *held-out*
treebank tags — and that surfaced content defects this review had not found: verb
entries run through the noun declension, `qui, quae, quod` declined as a
first-declension noun, the part-of-speech marker cut off by truncation so `fero`,
`video` and `jubeo` were not read as verbs, adjectives with no paradigm at all,
and 1,970 third-declension adjectives (`omnis`, `fortis`, `gravis`) that generated
their headword and nothing else. All applied bar two, each behind its own
checkpoint — B10 was closed as miswritten and B11 (`adv` against `conj`) cannot be
settled from L&S at all. **Not-contradicted 94.22% -> 96.96%** of answered tokens
(the 96.96% re-measured here; the starting point is from the checkpoint log), blank
`morph_info` 0.65% -> 0.43%.

**2. The adjective caveat above is closed.** `aptum` (144 tokens) and `fessum`
(79) were listed as real words that left the package when a mis-stemmed paradigm
stopped producing them, because their own adjective entries generated nothing.
Both now resolve from those entries: `aptum -> aptus`, `fessum -> fessus`, each
with a reading.

**3. The gloss defects below now reach about 1.6x as many readers.** No gloss
changed: `regress.py`'s `clean`, `enforce`, `suspect`, `xref` and `norm` probes are
all still unchanged against the baseline, so `out/ls_glosses.tsv` is
byte-identical. What changed is that far more corpus forms resolve to a lemma, so
`attributed_tokens` went 5,907,727 -> 9,257,696 and every token-weighted defect
count rose with it:

| detector | tokens then | tokens now | share of corpus |
|---|---|---|---|
| `ungrounded` | 36,990 | 57,343 | 0.538% -> 0.834% |
| `empty` | 99,578 | 112,988 | 1.449% -> 1.644% |
| `etymology-leak` | 2,630 | 3,975 | 0.038% -> 0.058% |
| `latin-chars` | 1,142 | 1,728 | 0.017% -> 0.025% |
| `head-echo` | 15,067 | 15,259 | 0.219% -> 0.222% |
| `bare-echo` | 1,726 | 1,846 | 0.025% -> 0.027% |

This is not an artifact to discount in either direction. The glosses were always
this good or bad; the difference is that a reader now actually meets them. It
raises the priority of findings 1, 4, 5 and 8b rather than changing what they are.

### Current package state

| | this review's final | after `morph_info` |
|---|---|---|
| morphology rows | 1,543,203 | **2,956,405** |
| distinct forms indexed | 1,517,547 | **1,726,493** |
| corpus coverage (the metric this review used) | 80.944% | **88.032%** (+487,189 tokens) |
| dictionary lemmas | 50,828 | 50,828 (unchanged) |
| `regress.py` `form_coverage_pct` | 61.219 | **73.604** |
| provenance strings in `morph_info` | 1,543,203 | **0** |
| off-schema `morph_info` values | — | 0 of 716 distinct |
| blank `morph_info` | — | 0.43% |
| dead lemma links | 0 | 0 |
| forms over the 3-candidate cap | 0 | 0 |

Every row above was re-checked against the built ZIP rather than taken from the
companion doc, along with: 0 provenance strings and 0 off-schema values among the
716 distinct `morph_info` values (validated against `inflect.SLOT_ORDER` and
`SLOT_VALUES`), 0 values needing CSV quoting, 0 duplicate (form, lemma) pairs, 0
confidences out of range.

Note that `form_coverage_pct` is the weaker of the two coverage numbers:
`regress.py` calls `forms_for(r[1], body[:200])` without the `pos_text=` argument
that `package.py:196` passes, so the probe sees a truncated entry and understates
what the package actually indexes. The 88.032% is measured on the ZIP itself.

`make test`: **211 tests, 3 expected failures** (30s). The built ZIP is 14.8 MB,
written to the pipeline's `out/` — the working-tree copy, not the repo's (see
"Two data directories"). It rebuilds **byte-identical** from the committed inputs:
two fresh builds match each other and match the shipped archive, member by member
(sha256 of `dictionary.csv`, `morphology.csv`, `normalization_rules.csv`).

### `make check` is not clean, by intent (cleared 2026-09-12)

*The diff below was reviewed and accepted on 2026-09-12 (`baseline/changelog/15-*`),
and `make check` has been green since. Kept as the record of why it was red.*

The three paradigm probes differ from the committed baseline because the paradigm
fixes changed them:

```
  stem       CHANGED  +495 -0 ~79        (22,360 -> 22,855)
  forms      CHANGED  +0 -0 ~32817       (51,643 rows, 32,817 changed)
  lemmafreq  CHANGED  +4595 -294 ~9592   (29,002 -> 33,303)
  [clean, enforce, suspect, xref, norm all unchanged]
```

**`make baseline` has not been run.** Until that diff is reviewed and accepted,
`make check` cannot guard the next change — it reports 47,879 differences whatever
else is wrong. This is the first thing to clear.

### Open, and belonging to this review rather than to the format fix

- **966 readings are known wrong**, 2.0% of the 31,820 tokens we answer
  (re-measured). 400 of them are `adv` against `conj` on indeclinables — 221 one
  way, 179 the other — which L&S cannot settle: it marks `etiam` as `conj.` only
  and `quam` as `adv.` only, and both words are genuinely both. There is no second
  marker in the entry to read. The shipped package is better than that figure,
  because `make morphacc` holds out the treebank on purpose and the treebank
  supplies the missing category.
- **`absent` is fifteen times larger than `wrong`** — 14,657 held-out tokens
  (9,132 forms not indexed + 5,525 lemmas not offered) against 966. Forms that are
  never generated are where the remaining quality is, and closing that gap costs
  nothing in accuracy. Finding 13 names one cause.
- **`morphology.csv` is 206 MB raw** (14.8 MB zipped), 57% larger than the 131 MB
  `DICTIONARY_IMPORT_FORMAT.md` cites for a complete Latin package.
- **Nobody has imported the package into the application.** Every check so far is
  static validation of the CSVs against the written spec.
- **The deliverable is no longer a one-column relabel.** 1,543,203 rows ->
  2,956,405. It should be reviewed as a content change.

## What is already right

The architecture is sound and unusually well-reasoned: cheapest-path resolution,
uncorrelated multi-model judging, absolute-bar verification, frequency-ordered
repair, the consolidated normalisers, and the discipline of recording failed ideas
(`xref-adapted`) rather than deleting them. The `--no-adapt` decision and the
"judge must see the referenced entry" fix are both correct. Most of what follows
is about a defect class the current screening is structurally blind to.

## 1. Metalinguistic descriptions of function words — the biggest reader-facing defect

The highest-frequency words are glossed with *descriptions of their grammatical
role* instead of translations:

| headword | gloss | tokens | source |
|---|---|---|---|
| `et` | "and (conjunction)" | 189,485 | model? |
| `nec2` | "inseparable negative particle" | 26,144 | hard |
| `ab` | "departure from a fixed point" | 22,459 | freqfix |
| `ne2` | "asks, emphasizing the following" | 18,150 | freqfix |
| `quidem` | "example introducer" | 12,894 | freqfix |
| `nam` | "to introduce an explanation" | 11,614 | freqfix |
| `an` | "Possibly a particle expressing doubt" | 6,822 | freqfix |
| `cujus` | "whose? of whom? interrogative pronoun" | 5,279 | model |
| `sive` / `seu` | "disjunctive conditional particle" | 4,724 | model / xref |

**Why nothing catches it.** `suspect.py:13` anchors `POSDESC` with `^`, so it only
fires when the gloss *begins* with a part-of-speech noun — "and (conjunction)" and
"departure from a fixed point" both pass. Worse, `suspect.py:40-52`:
`FUNCTION_ENTRY` disables the grounding check *and* the fragment check for any
entry marked `praep./conj./pron./adv.` The exemption is right for grounding (a
pronoun's English gloss will not appear in Latin entry text), but its effect is
that function words — the densest tokens in the corpus — receive **less** screening
than any other class, and nothing was added back in their place.

**This is not the sliding-window problem.** `ab`'s freqfix checkpoint records
`off=3200`, and "from, away from" sits at focused offset 3379 — inside that window.
The window worked. The model preferred L&S's own metalinguistic sentence, and no
detector or prompt rule objected. Fixing this is a detector + prompt change, not a
windowing change.

Suggested: make `POSDESC` unanchored, add verb-frame patterns
(`denotes|indicates|introduces|expresses|marks|asks|stands for|serves to|used to`),
and give function-word entries this check *instead of* the two that are switched
off. Add a positive rule to `gloss-hard.txt`: for a preposition/conjunction/
particle/pronoun, give the English word a translator would put in the sentence,
never a description of what it does.

## 2. `clean_gloss.POSNOTE` omits exactly the function-word POS names — FIXED

`clean_gloss.py:4` strips `(verb|adj|adjective|adverb|noun|n|v|pl|sing)` but not
`conjunction|preposition|pronoun|particle|interjection|numeral`. That single
omission is why the most frequent word in Latin ships as `and (conjunction)`.
Fixed by adding the function-word classes plus an optional single-word qualifier,
so `(reflexive pronoun)` and `(negative particle)` are caught too while a register
label like `(post-Aug.)` is still kept. Over the 64,007 raw model replies it
changes exactly **6**, and nothing else in the corpus moves:

```
+ main:16299: and (conjunction)          -> and
+ main:15360: holla! or soho! (interj.)  -> holla! or soho!
+ main:22135: un- (negative particle)    -> un-
+ main:31475: who? (interrogative pron.) -> who?
+ adapt:2150: around (preposition)       -> around
+ main:50321: ve- (particle)             -> ve-
```

## 3. The frequency ranking that drives `freqfix` is corrupted two ways

`freqfix` exists to spend model budget where readers are. Both inputs to that
ordering are wrong:

**(a) Homographs collapse onto one key.** `lemmafreq.py:30,35` strips the trailing
digit and takes `max()`, so all 16 `in` entries and all 15 `super` entries share one
key and one frequency. In the top-1200 screening band, **195 slots (16%) are
duplicate homographs** of a lemma already screened; at top-3000 it is 406.

**(b) 321 entries generate paradigms from a truncated stem.** `inflect.py:72-81`:
the `i` and `ae` branches guard against an abbreviated genitive; the `us` and `is`
branches do not. `Spāco, cūs` (nurse of Cyrus) yields stem `c`, generating `cum`,
`cui`, `cibus`, `cuum`. `Spaco` therefore ranks **#21 by frequency, above `ad`**, on
65,861 borrowed tokens. Across all 321 entries, 161,275 tokens (3.1%) are
mis-attributed. A sub-case: `HEAD` parses deponent principal parts as noun+genitive
(`populor, atus sum` → stem `at`, generating `atum`, `atus`).

The shipped package is fine — `cum,spaco,…,0.35` loses to `cum,cum,…,1.00` in
`morphology.csv` — so the damage is entirely to prioritisation, which is the one
thing this stage is for.

## 4. Cross-reference inheritance still ignores case and word class

Turning `--no-adapt` on was correct, but nothing replaced it, and this remains the
weakest source at the top of the frequency list:

`quid` → "who? which? what? what man?" (21,400) · `a2` → "around, near, beside,
among" (29,112) · `me` → "I, myself" (17,250) · `tibi` → "thou, you, you
(singular)" (10,905) · `quod2` → "eighth letter" (44,914) · `hoc` → "to this place,
hither" (19,732)

A narrower replacement than the old adapt stage: inherit verbatim only when
referrer and target share part of speech; for oblique pronoun forms, ask for the
English of *that case* and verify against the target entry with the existing
absolute bar.

## 5. Etymology leaking into glosses on frequent words

`vel` → "to choose, prefer" (12,348 — that is *volo*'s meaning), `animus` →
"Graeco-Italic form of wind", `se2` → "sine, without, aside", `dis` → "dis, particle
meaning asunder". `gloss-system.txt` tells the model to ignore the etymology but
describes it as sitting immediately after the part of speech; in these entries it
does not. A mechanical detector — gloss content-words drawn from the entry's
bracketed etymology span — would route these to the hard pass.

## 6. Leading headword echo — real but smaller than it looks

269 rows / 197k tokens have a comma-part identical to the headword, but most are
legitimate Latin–English cognates (`orator` → "speaker, orator", `victor`, `labor`,
`in` → "in, within, on, upon" are all correct). The genuine defects are where the
echoed token is not English: `tamen` → "tamen, nevertheless, however, still",
`verum` → "verum, true, real, genuine", `mas` → "mas, masculine, male", `do` → "do,
to put, place". `bare_echo`/`DECL` only fires when *every* part echoes. Worth
fixing, but it needs an English wordlist to avoid breaking the cognates — rank it
below 1–3.

## 7. `freqfix`'s accept test favours the challenger

`freqfix.py:193` — `rate(i, g, off) <= rate(i, old, off)` judges the *incumbent*
against the window the *new candidate* was generated from. An incumbent whose
supporting text lies elsewhere scores low against that window, so replacement wins
on home-turf advantage. Related, `freqfix.py:168-169`: `best_score` compares scores
taken against different windows, which are not commensurable, and `if sc >= 5:
break` stops at the first window that self-confirms. Scoring both candidates against
every window tried and taking the max per candidate would make the comparison
honest.

**Now confirmed by instrumentation.** Driving the real `freqfix.py` against a
scripted model on a long entry, the judge was called five times: **four for the
challenger** (once per window offset) and **once for the incumbent**, and that one
call used the challenger's window at offset 3,200 — which contains none of the text
supporting the incumbent. The incumbent is never judged against the start of its
own entry. `tests/test_findings.py::TestFreqfixJudgesTheIncumbentFairly` asserts it
must be.

This is consistent with what the `freqfix` output looks like on inspection —
alongside good repairs (`bellum` → "war", `cīvis` → "citizen") sit `Afrĭca` →
"south-west wind that blows" (that is *Africus*), `Constantĭus` → "Constantine,
emperor", `Crassus` → "of or belonging", `cămillus` → "small, diminutive",
`argūmentor` → "prove something by argumenting".

## 8. Two smaller things

- **Coverage holes.** 878 rows are empty; 50 have a glossed homograph sibling so the
  reader is still served, leaving **828 lemmas with no gloss anywhere (0.53% of
  tokens)**. Notable: `ejus` (13,314), `impenetrale` (5,285), `nullus`, `quom`,
  `volt`.
- **`out/latin_freq.tsv` line 62 is a blank token with count 9,480** — it would rank
  ~63rd. `corpusfreq.py` should drop empty keys.

## 9. Repo hygiene that actively costs quality

There are two prompt directories. `lsgloss/prompts/` is live (`lsgloss.py` reads
`ROOT/'prompts'`); the top-level `prompts/` is a stale copy — its
`gloss-system.txt` is **missing the word-class rule**, and its `gloss-repair.txt`
still says "This entry DOES describe its word" without the `NONE` escape and the
anti-invention clause. The README refers to `prompts/gloss-system.txt` and
`prompts/judge-*.txt` throughout, so anyone following it tunes the dead copy.
Deleting the top-level directory is the fix.

Relatedly, the README's account of `ab` ("a fixed window shows the model nothing but
cognates, and it invents 'around, near, beside, among'") no longer matches the data:
that string is now `a2`'s, arriving via `xref-resolved`, and `ab` failed at
`off=3200` for a different reason.

## 10. The 5th-declension paradigm branch is unreachable

`inflect.py:73` tests `g.endswith('i')` before line 78 tests `g.endswith('ei')`, so
`rei` is captured by the earlier branch and *res* is inflected as a 2nd-declension
noun. It generates `reus, reum, reo, reos, reorum, reis` — all real forms of
*reus*, "defendant", 1,207 corpus tokens it should not claim — and never generates
`rem, rebus, rerum, re`, which are 20,162 corpus tokens.

The treebank rescues these for *res* itself (`rem,res,treebank,0.99` ships in the
package), so the damage is confined to 5th-declension nouns outside the treebank —
but the treebank is the test set, not the target. Reordering the two branches is
the fix.

## 11. Verb ending tables are unfolded while the stem is folded — FIXED

`VERB['are']` carries `avi`, `avit`, `averunt`; `VERB['ire']` carries `ivi`,
`ivit`, `iverunt`. The stem is folded (`amo` -> `am`) but these endings are not,
so `forms_for` returned `amavit` while a corpus token folds to `amauit`. 20,835
generated forms were dead.

**Correction to my first write-up.** I said this would recover 13,825 tokens of
*reader coverage*. It does not: `package.py:139` folds every form again at write
time, so `morphology.csv` already contained `amauit`. Rebuilding the package
confirms it — the form/lemma pair set is **identical**, 0 added and 0 removed.

What the dead forms actually corrupted is **frequency attribution**, because
`lemmafreq` matches `forms_for` output against a folded frequency list without
re-folding. So the fix lands on ranking, not coverage:

- 935 lemmas' corpus frequencies changed, all upward; 30 lemmas gained a
  frequency they previously scored 0 for.
- In a rebuilt package: **39,244 morphology rows gain confidence** (none lose),
  and **35 forms change their top-ranked lemma** — `turbatus` now ranks *turbo*
  above the participle entry, `iuratus` ranks *juro*, `excitatus` ranks *excito*.
  Those are the lemmas the treebank agrees with, so this is the reader-useful
  answer by the README's own definition.

Fixed by folding at the boundary in `forms_for` rather than pre-folding the
tables, so "every generated form is a word_form key" is a property of the
function rather than of whoever last edits a table. One paradigm shrank by a form
(`flo`: `flavi` and `flaui` deduplicated).

## 12. `enforce` can still emit a dangling article — FIXED

`enforce('one who is of the household', 5)` returns `'one who is of the'`. The
`_contentless` guard correctly rejects the phrase-boundary cut, then falls back to
`' '.join(w[:maxwords])` without re-applying the dangling-word trim — swapping one
bad output for another.

Fixed by extracting `_undangle` and running it on every fallback path. Affects 3
entries in the raw-reply corpus (`one who is of the` -> `one who is`, `of or
lasting half a` -> `of or lasting half`). The results are still fragments, but
they are now well-formed ones, and `suspect.py`'s `fragment` detector already
routes them to re-glossing.


## 13. Abbreviated verb principal parts are taken literally — NEW, open

Finding 3b closed this for nouns (`Spāco, cūs` -> stem `c`). The verb half is open,
and it fails in both directions, because L&S elides a simple verb's perfect stem
and prints a compound's principal parts without the prefix:

| entry | L&S citation | what ships | what is missing |
|---|---|---|---|
| `scribo` | `scrībo, psi, ptum` | `scribpsi`, `scribpserim` — the fragment glued onto the present stem | `scripsi`, `scriptum` |
| `sentio` | `sentĭo, si, sum` | `sentsa`, `sentsum` | `sensi`, `sensum` |
| `perago` | `per-ăgo, ēgi, actum` | `peragacta` | `peregi`, `peractum` |
| `discribo` | `dī-scrībo, scripsi, scriptum` | `scripsi`, `scripseram` — the *simple* verb's | `discripsi` |
| `excedo` | `ex-cēdo, cessi, cessum` | `cessa`, `cesseram` | `excessi` |
| `suadeo` | `suādĕo, si, sum, 2` | `sa`, `sae`, `si`, `so` — *noun* endings | `suasi`, `suasum` |

**407 verb entries** cite a perfect that does not share the headword's stem, so
roughly half of each one's paradigm (37–38 of about 75 forms) is generated for the
simple verb instead: `intercedo` -> `cessa`, `detineo` -> `tenta`, `transpono` ->
`posita`. That count is solid; twelve sampled at random were all genuine.

The other half of the defect is harder to count exactly. 2,244 verb entries cite a
fragment perfect (four characters or fewer, infinitives excluded); 80 of them
generate no perfect stem at all, and a detector for the glued-on shape flags 231
more — but that 231 is an **upper bound**, because it cannot yet separate
`clepo, psi` -> `clepsi`, which is right because the stem ends exactly where the
fragment begins, from `scribo, psi` -> `scribpsi`, which is not. Sixteen further
entries truncate to a one- or two-letter stem and then run the noun declension,
`suadeo` among them.

What a reader of the built package gets:

- `scripsi` (373 corpus tokens) is offered as *discribo* and *interscribo*.
  *scribo* is not offered at all — it ships `scribpsi` instead.
- `sensum` (343) is offered as *praesentio*, *consentio*, *sensus*. Not *sentio*,
  which ships `sentsum`.
- `lata` (265) is offered as *praefero*, *lyo*, *latus*. Not *fero*.
- `tenta` is offered as *contineo*, *sustineo*, *retineo*. All three are wrong.
- `facta` (2,484) is right twice — *facio*, *factum* — then spends its third and
  last slot on *arefacio*.

The invented forms are nearly harmless in themselves: `scribpsi`, `sentsum`,
`peragacta` and `sarum` are 0 corpus tokens, `sa` is 26. The damage is the missing
perfect and supine of every affected verb, and candidate slots spent on lemmas that
cannot produce the form. This is a named cause inside the `absent` bucket, which
the morphology work measured as the largest of its five outcomes — and unlike most
of this review, fixing it *adds* correct forms rather than removing wrong ones.

In the same family: `fero` generates `feroe`, `feroeam`, `feroeamus` from
`fĕro, tŭli, lātum, ferre`. Impossible, 0 corpus tokens, and they ship.

## Where to spend effort

First, **review and accept the regression baseline** (see above) -- done
2026-09-12; `make check` is green. Every item below is verified by `make check`.

Findings 1–12 are each covered by an executable spec, so they can be fixed in any
order without risking each other; finding 13 still needs one. Items 11, 2 and 12 are done. Remaining, cheapest and
safest first:

1. **1** — highest reader impact (~4% of corpus tokens), a detector plus a prompt
   clause. The guard tests matter most here: the risk is over-firing on correct
   function-word glosses like `from, away from`.
2. **3a, 3b, 10** — the frequency and paradigm bugs. None fixes a gloss directly,
   but 3a/3b restore the aim of every future `freqfix` run, so they belong before
   the next repair pass rather than after. Finding 11 has already moved frequency
   attribution in the right direction; these finish the job.
3. **6, 5, 7, 8, 9** — smaller or more contained.
4. **13** — mechanical, and it is the one item that adds *correct* forms rather
   than removing wrong ones: 407 compounds are missing their perfect and supine.
   The fix is to re-attach the headword's prefix to a cited principal part that
   does not carry it, and to expand a fragment (`psi`) against the headword.
   Guardable by `make morphacc` without a model.
5. **4** — the largest remaining structural weakness and the most work; worth
   designing separately once the rest is stable.

Items 1 and 5 change what the model is asked, so they also need a model run
against `eval/gold.tsv`; everything else is verifiable with `make check` alone.

## Appendix — how the numbers were produced

- Corpus weighting: `lemmafreq.lemma_frequencies` over `out/latin_freq.tsv`,
  total 5,179,951 lemma-attributed tokens at the time of this review; **9,257,696
  now**, against 6,873,450 corpus tokens. The sum exceeds the corpus because two
  entries can both generate the same form, which is why `regress.py` divides by
  the corpus and not by the sum.
- Existing `suspect.py` detectors on the final output: `ungrounded` 492 rows /
  1.11% of tokens, `latin-chars` 150 / 0.02%, `bare-echo` 34 / 0.03%,
  `adv-inherits-verb` 29 / 0.02%, `word-class` 7 / 0.01%, `fragment` 5 / 0.67%,
  empty 878 / 2.48% (0.53% after excluding rows with a glossed homograph sibling).
  These shares are as of this review; see the `morph_info` section for the current
  token weights.
- Regression baseline: 5.1 MB across 9 files under `lsgloss/baseline/`.
  `make check-size` still passes — **16 MB across 96 files** committable against
  the 50 MB limit. The README's "7 MB across 41 files" is stale.
- Source mix in `out/ls_glosses.tsv`: model 35,967, xref-resolved 6,910, model~
  2,922, repaired 2,058, no-gloss 801, hard 631, xref-resolved~ 521, named 344,
  freqfix 339, hard2 297, plus flagged variants. No `xref-adapted` rows, so
  `--no-adapt` is in force.
