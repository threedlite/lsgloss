# `morph_info` fix — tracking doc

Task record for repairing the `morph_info` column of `lewis-short-glosses.zip`.
Companion to `REVIEW.md`. Kept current as work proceeds.

---

## 1. The brief

`lewis-short-glosses.zip.orig` (sha256 `f0a9a2f1…93ab`, 6,485,867 bytes) is a
finished, working artifact with **one defect**: its `morph_info` column carries
pipeline provenance instead of morphology. All 1,543,203 rows, six values:

| shipped `morph_info` | rows |
|---|---|
| `paradigm + -ve` | 511,286 |
| `paradigm + -que` | 511,276 |
| `generated paradigm` | 459,162 |
| `headword` | 47,827 |
| `treebank` | 13,595 |
| `model lemma` | 57 |

`DICTIONARY_IMPORT_FORMAT.md:53` documents the column as the parse
(`3 s pres active ind`), and it is what the app shows a reader who taps a word.
Provenance already has a column — `source_name`.

**Fix that column. Change nothing else.**

## 2. Constraints

| # | Constraint | Source |
|---|---|---|
| C1 | Same rows. `word_form`, `lemma`, `language`, `confidence`, `source_name` byte-identical to `.orig`; `dictionary.csv` and `normalization_rules.csv` untouched | "fix only the morphology format, not the rest of the content" |
| C2 | Through the pipeline. The fix lives in `inflect.py` / `package.py` and appears on a rebuild. No hand-editing a CSV or a zip, no manual steps | "it can only be done thru the pipeline in a repeatable way" |
| C3 | One standard. `morph_info` is not free text — a single schema, applied to every row whatever produced it | "the morphology isnt free form, it has to always conform to the standard" |
| C4 | The release DB is a **format** reference only. Never a source of content | "not supposed to use release db as a source in any way except for format" |
| C5 | Accuracy. Do not state what is not known or not true | "accuracy is very important" |
| C6 | No provenance strings in the column | "we cant have garbage like 'headword' etc in the output" |

## 3. Acceptance criteria

0. **Enclitic forms are pre-split** so `virumque` resolves to both of its words
   (§9.1). The only sanctioned departure from AC2 — it adds and removes rows, and
   every one of them is a `-que`/`-ue` form.
1. Rebuild via `package.py` reproduces the package from the committed inputs.
2. Every column except `morph_info` byte-identical to `.orig`; the other two
   members byte-identical.
3. No value in `morph_info` is a provenance label.
4. Every value parses as schema slots, in order, from the closed vocabulary.
5. Two consecutive builds byte-identical.

**Status: all verified (§8).**

## 4. The schema

The one the shipped database already uses, so our rows read the same as the
1,955,715 Whitaker Latin rows they import alongside in `lemma_map`. Format
only — no content taken from it (C4).

```
nominal      case number gender             acc s f
verbal    person number tense voice mood    3 p perf active ind
participle   case number gender tense voice mood
                                            gen p pres active part
```

- Slot order: `person|case, number, gender, tense, voice, mood, category`.
- Closed vocabulary per slot; `inflect.render_morph` rejects anything outside it,
  so a typo in a paradigm table fails the build rather than shipping.
- A slot the source does not determine is **omitted**, never guessed.
- A form that is several things at once carries every reading, joined by `|`,
  sorted (`portae` → `dat s f|gen s f|nom p f|voc p f`). Collapsing them into one
  underspecified reading (`s/p gen/dat/nom/voc`) would also admit `nom s` and
  `gen p`, which `-ae` never is.
- No part-of-speech token on anything that inflects — a noun row says `acc s f`.
  `prep`/`conj`/`adv`/`interj` extend the vocabulary only for indeclinables,
  which Whitaker does not index at all (`ab`, `et`, `non`, `sed`, `cum`, `in`,
  `ad` have no row there), so nothing can disagree.
- No commas, so no row needs CSV quoting.

## 5. Where the readings come from

All from our own inputs (C4):

| source | what it supplies |
|---|---|
| `inflect.py` ending tables | the reading of the paradigm slot that produced the form. The tables always *were* the morphology; `forms_for()` returned a bare `set()`, discarding which ending made which form |
| Perseus treebank `postag` | `<word form="fatur" lemma="for1" postag="v3spip---"/>` is third singular present indicative passive. `package.py` read `form` and `lemma` and dropped the tag |
| L&S headword line | part of speech and gender — `porta, ae, f.`, `pertinenter, adv.` Fills the forms the tables cannot build: third-declension nominatives like `rex`, and indeclinables |

Confidence ranks the **lemma**; it does not choose between readings. A treebank
tag records what `portis` was in the annotated passages (ablative) and, being
higher-confidence, replaced the paradigm's `abl p f|dat p f` — telling a reader
whose sentence has the dative that the form is ablative. Readings now union.

Enclitics carry the host's reading unchanged: `-que` is a separate word written
joined, so `portisque` is what `portis` is. There is no slot for "has an
enclitic".

## 6. Changes to the pipeline

### `inflect.py`
- `SLOT_ORDER` / `SLOT_VALUES` / `render_morph` / `render_readings` — the schema
  and the only place a value is built.
- `NOUN` / `VERB` — **same endings as `.orig`**, each now carrying its readings.
  (Superseded 2026-09-12: the tables were changed -- dative singular added to
  the third declension, i-stem endings split out, nominative endings gated on
  the headword, deponents restricted -- see `README.md`, *Revision 2026-09-12*.)
- `postag_slots` / `postag_morph` — decode the Perseus tag.
- `strip_parens`, `pos_from_entry` — read every part of speech the headword line
  names. Three traps: `v.` opens a verb entry (`v. a.`) and also abbreviates
  *see* (`concitus, a, um, v. concieo`); L&S interrupts the headword line with
  parentheses long enough to hide the marker; an adjective is often cited by its
  three nominatives (`phreniticus, a, um`) rather than an abbreviation.
- `forms_with_morph` — returns `{form: morph_info}`. `forms_for` is a `set()`
  wrapper over it, so every form-only caller is unchanged.

### `package.py`
- `add()` takes `morph` and `origin` separately. Only `morph` reaches the CSV;
  provenance prints to stderr at the end of the build (C6).
- Treebank reader keeps `postag`.
- Readings union across sources instead of the highest confidence winning.

### Tests — `tests/test_inflect.py`, `tests/test_package.py`
Schema conformance per reading over every shipped row; sorted/unique
alternatives; no provenance value; no category token on anything that inflects;
no commas; `render_morph` refuses out-of-vocabulary values.

### `eval/morphacc.py` + `make morphacc`
Accuracy against **held-out** treebank tags: builds without `--treebank`, so
every reading came from the tables or the headword line, then scores against the
annotations left out. Reports `exact` / `compatible` (we say less — not an
error) / `CONTRADICTED` (the number that matters).

## 7. Course corrections

Three, all on my side, all from scope I should not have taken.

**A. Two vocabularies in one column.** First version rendered the same fact two
ways depending on which source produced it — `verb 3 s pres act ind` from a
treebank tag beside `3 s pres act ind` from a paradigm, `noun s m gen` beside
`dat/abl p` with the slots in opposite order. Fixed by C3: one schema, one
renderer, enforced.

**B. Sourced content from the release DB.** Took locative readings, participle
and gerundive reading sets, and a test asserting our strings equal theirs. All
removed; the schema stays, every reading re-derived from L&S or the paradigm
(C4).

**C. Rewrote the paradigm generator.** Measuring accuracy showed the generator
itself was wrong outside the first conjugation (`moneo` → `monees`, `moneet`;
third-conjugation `dicit` labelled perfect; verb entries also run through the
noun declension; `qui, quae, quod` declined as a first-declension noun; neuters
using the masculine paradigm). I fixed those — which changed **471,810 rows
removed and 1,129,820 added**, i.e. the content, not the format. Out of scope.
**Reverted**: the ending tables, stem logic and control flow of
`forms_with_morph` are back to what `.orig` was built from. (That reversion
was itself superseded by the later paradigm fixes; the current state is the
one `tests/test_fixes.py` pins.)

The shared `ere` table is why `dicit` was mislabelled: it serves the second
conjugation and the third, whose `-it` is a perfect and a present respectively.
Splitting the table would change which forms exist, so instead the ending
carries **both** readings — a labelling change, not a generation change.

Those generator defects are real and worth fixing, but as their own task against
`REVIEW.md`, not inside a format fix. Recorded in §9.

## 8. Verification — run

| AC | Check | Result |
|---|---|---|
| 1 | `package.py` rebuilds from the committed inputs | 1,543,203 forms, 50,828 lemmas |
| 2 | Every column but `morph_info` identical to `.orig` | **True** |
| 2 | `dictionary.csv`, `normalization_rules.csv` | **identical** (sha256) |
| 3 | Provenance values in `morph_info` | **none** |
| 4 | Values off-schema | **0** of 797 distinct; 0 contain commas |
| 5 | Two consecutive builds | **byte-identical** |
| 0 | Rows whose form does not end in `-que`/`-ue`, vs `.orig` | **520,317, identical** |
| 0 | `virumque` resolves to *vir* AND *que* | **yes**, host ranked first |

Test suite: 208 pass. `regress.py`: **all 8 probes unchanged from baseline** —
which is the independent confirmation that the generator is back to what `.orig`
was built from. `make baseline` was not run and is not needed.

Blank `morph_info`: 18,338 rows (1.19%). These are entries that name no part of
speech and build no paradigm — cross-reference stubs whose own text says nothing
about the word — plus their `-que`/`-ve` rows. Empty is what the format expects
for unknown.

### Regression found and fixed during verification

The first rebuild after the §7C revert came out 7,092 rows short. Cause:
`forms_with_morph` added the headword form only when something was known about
it, where the original `forms_for` added it unconditionally. That silently
dropped the `-que` and `-ve` rows of 3,546 entries. The headword is now always
indexed, with an empty `morph_info` when nothing is known. Caught by AC2 — which
is the reason to diff against `.orig` rather than trust the diff of the code.

## 9. Defects found, with proposed fixes

Found while labelling the column: attaching a claim to every form is what made
the generator checkable for the first time. **None of these are fixed** — §9.1 is
required and agreed, §9.2 are recorded for a separate content task. Each changes
which rows exist, so none of them belongs in a format fix (C1).

Measured impact, where given, is from `make morphacc` — held-out Perseus
treebank tags, 47,949 annotated tokens. Fixing B1–B4 together moved contradicted
readings from **11.5% to 4.6%** of answered tokens.

---

### 9.1 DONE — enclitic forms are now pre-split

**Symptom.** A reader meeting `virumque` ("and the man") is told it is a form of
*vir* and never learns there is an "and" in the token.

```
uirumque      vir     0.74  acc s m|acc s n|nom s n|voc s n
armaque       arma    0.70  n
senatusque    senatus 0.74  acc p|gen s|nom p|nom s|voc p
```

**Scale.** 1,017,454 rows — 508,695 `-que` and 508,759 `-ve` — are **66% of
`morphology.csv`**. Exactly **9** rows in the whole file carry the enclitic as
their lemma.

**The parts are already there.**

- `que` and `ve` are lemmas in `dictionary.csv` ("co-ordination of words",
  "choice between two"), so the join target exists.
- `inflect.split_enclitic()` exists, is documented, is unit-tested
  (`test_inflect.py:66-83`) — and **is called by nothing in the pipeline**. It
  was written for this and never wired in.
- The format supports several candidates per `word_form`, ranked by
  `confidence`, capped at `MAX_CANDIDATES = 3`.

**Cause.** `package.py` appends the enclitic blindly:

```python
for enc in ('que', 've'):
    add(f + enc, lem, 0.75, minfo, f'paradigm + -{enc}')
```

It produces the joined form and maps it only to the host lemma. Nothing records
that the token is two words.

**Proposed fix.**

1. Emit a second candidate row for every generated enclitic form, mapping it to
   the enclitic's own lemma: `uirumque → que`, `uirumue → ve`. Confidence below
   the host so the host still ranks first; `morph_info` is `conj` for `que` and
   `conj` for `ve` (both are co-ordinating conjunctions, and `conj` is already in
   the category vocabulary). The reader then sees both parts of the token.
2. Gate generation on `split_enclitic`, so the pipeline only creates a joined
   form it would itself split back: emit `f + enc` only where
   `split_enclitic(f + enc) == (f, enc)`. This is what the existing length guard
   (`len(f) > len(e) + 3`) is for, and it is why `-ne` is excluded — `-ne`
   collides with the ablative of every `-io/-ionis` noun.
3. **Fold the enclitic list first.** `ENCLITIC = ('que', 've')` is in
   conventional spelling, but stored forms are folded (`v` → `u`), so
   `split_enclitic` as written can never match a stored `-ue` form. It must
   compare against `('que', 'ue')` or fold its input. This is a latent bug in the
   unused function and would bite the moment it is wired in.

**Secondary — 66 generated enclitic forms are themselves L&S headwords.** The
blind append invents a host+enclitic reading for words that are not one:

| form | real word | our top candidate | real lemma's rank |
|---|---|---|---|
| `namque` | conj., "for indeed" | `nam` 0.99 | `namque` 0.90 |
| `itaque` | conj., "and so" | `ita` 0.99 | `itaque` 0.97 |
| `atque` | conj., "and" | `at` 0.73 | — |
| `denique` | adv., "finally" | `deni` 0.49 | `denique` 0.99 |
| `absque` | prep. | `abs` 0.62 | `absque` 0.76 |

`split_enclitic`'s length guard already blocks `absque`, `aeque`, `atque`,
`cumque`, `deque`, `namque`, `itaque`, `usque`, `quoque`; it does **not** block
`denique` → `deni` or `donique` → `doni`. Gating on it (fix 2) removes most;
suppressing a generated enclitic form that is itself a dictionary lemma removes
the rest.

**Risk, and what it turned out to be.** Fix 1 spends a candidate slot on every
enclitic form, which the 3-candidate cap could take from a genuine second lemma.
Measured: 17,079 enclitic candidates (1.7%) are cut by the cap. Accepted.

#### Implemented

`inflect.py`
- `ENCLITIC_SPELLINGS` — each stored spelling and the enclitic it names.
  `-que` is tested **before** `-ue`, because `que` itself ends in `ue` and
  `uirumque` would otherwise split as `uirumq` + `ve`.
- `split_enclitic` is fold-aware, and the first spelling that matches now decides
  whether or not it splits. Falling through on a failed length guard let
  `namque` — too short to split at `-que` — be torn apart at `-ue` instead.

`package.py`
- Generates a joined form only where `split_enclitic` would split it back, and
  never where the joined form is itself a headword: `denique` is an adverb with
  its own entry, not `deni` + `-que`.
- Emits the enclitic as its own candidate at a fixed 0.30, below the 0.375 floor
  a frequency-weighted host can reach, so the host always leads.
- Requires the host to be indexed for that lemma before joining it at all.
- After the candidate cap, drops any enclitic row whose host did not survive it,
  and any joined form left resolving to nothing but "and". Judged on the lemma,
  not the producing stage: the treebanks annotate `tinuoque` to `que` with no
  host entry anywhere, and that row is as empty as one we joined ourselves.

#### Result

```
uirumque  -> vir   0.74  acc s m|acc s n|nom s n|voc s n
uirumque  -> que   0.30  conj
uirumue   -> ve    0.30  conj
```

| | |
|---|---|
| rows | 1,543,203 → 2,546,580 |
| added | 1,004,513, of which 1,004,478 are the enclitic lemma |
| removed | 1,136, every one a `-que`/`-ue` form — short hosts the guard refuses (`abque`, `absue`) |
| dropped for a missing host | 515 |
| rows not ending `-que`/`-ue` | 520,317, **identical to `.orig`** |

Words that only look like enclitic forms now lead with their own entry:
`usque`, `denique`, `undique`, `absque`, `quoque`. Three tests pin this
(`test_package.py`): the token resolves to both words with the host first; no
joined form exists without its host; a word that merely ends in `-que` is not
split.

---

### 9.2 Content bugs — recorded, not fixed

**B1. The verb paradigm is wrong outside the first conjugation.** One table,
`ere`, serves conjugations 2 and 3, and the stem is derived by stripping only
`-o`.

```
moneo, ui, itum, 2   ->  moneebam, monees, moneet, moneetis, monei, moneit
dico, dixi, dictum, 3 -> dicit labelled "3 s perf active ind"   (it is a present)
                         dices, dicet labelled present          (they are future)
```

*Cause.* The second conjugation's stem is the headword minus `-eo` (`mon-`), not
minus `-o` (`mone-`). The third conjugation's present is `-is/-it` where the
second's is `-es/-et`, and its future is `-es/-et`. And the perfect is not
predictable from the present in either: `moneo` → `monui`, `dico` → `dixi`.

*Proposed fix.* Group endings by the stem they attach to, and read the stems off
the principal parts L&S prints in the headword line — `dico, dixi, dictum` gives
`dic-`, `dix-`, `dict-`. An abbreviated part names the end of the word
(`amo, avi` is am-AV-i), told apart from a full one by whether it starts like the
headword, the same test `_noun_stem_and_key` already uses for genitives. Where a
perfect stem is not printed, generate no perfect forms rather than invent them.
Split `ere` into separate tables for conjugations 2 and 3.

*Impact.* Largest single source of both dead keys and wrong labels. In the
prototype this also **raised** corpus form coverage (61.219% → 61.576%), because
the forms it stops generating are non-words and the ones it starts generating are
real.

*Interim.* The shared `ere` endings currently carry **both** readings
(`it` → `3 s perf active ind|3 s pres active ind`), which is honest and changes
no forms, but it means every such form offers a reading it does not have.

---

**B2. Verb entries are also run through the noun declension.** `moneo, ui` and
`dico, dixi` match `HEAD` as "headword, genitive".

```
moneo  ->  moneous, moneoi, moneoorum, moneoos, moneoum, moneoe, moneoer
dico   ->  dixe, dixer, dixis, dixo, dixorum, dixos, dixum, dixus
```

*Proposed fix.* Skip the declension when `pos_from_entry` returns `verb`.
**Not** when `CONJ` matched — see §9.3, where that form of the fix was measured
and would delete the paradigms of ~8,700 genuine nouns, 276,180 corpus tokens.

*Impact.* Deletion of dead keys, but only once the fix is narrowed. **Unsafe as
first written** — §9.3.

---

**B3. Gendered citations are read as genitives.** L&S cites a noun by its
genitive (`rex, regis, m.`) and a gendered word by its three nominatives
(`qui, quae, quod`, `bonus, a, um`). The parser reads only the first two tokens,
so `qui, quae` declines the relative pronoun as a first-declension noun with the
stem `qu-`:

```
quae -> "dat s|gen s|nom p|voc p"      gold: nom s f pron
quas, quarum, quam ... all invented
```

*Proposed fix.* The third token separates them: a gender abbreviation ends in a
period, a third nominative does not.

**Unsafe on its own** — §9.3. Measured, the entries it actually catches are
verbs (`lego, legi, lectum`), whose mapping it deletes without replacing:
`lege` alone is 1,432 corpus tokens. It only becomes safe after the revised B2
has taken verbs out of the set.

*Impact.* ~137 tokens of the treebank sample, all on the commonest pronoun in
Latin.

---

**B4. Neuters use the masculine paradigm.** The second and third declensions have
distinct neuter sub-paradigms and the tables have only one each:

```
bellum, i, n.  ->  belle, beller   (masculine endings on a neuter)
                   belli claims "nom p"   (a neuter plural is -a: bella)
nomen, inis, n. -> nomina, nomini never generated
```

*Proposed fix.* Add `i-n` and `is-n` tables and select on the entry's own gender.
A neuter's nominative, accusative and vocative are one form in both numbers and
its plural is `-a`.

**Needs an adjective paradigm alongside it** — §9.3. It correctly stops
`alium, i, n.` (garlic) claiming `alios`, but nothing else supplies that form,
because `_noun_stem_and_key('alius', 'a')` returns nothing.

---

**B5. A masculine noun is given the neuter readings of `-um`.** Visible in the
example the enclitic work is about:

```
uirum   vir    acc s m|acc s n|nom s n|voc s n
equum   equus  acc s m|acc s n|nom s n|voc s n
```

*vir* and *equus* are masculine and have no neuter forms. The second-declension
`-um` entry carries the masculine accusative and the neuter nominative /
accusative / vocative together, and `nominal()` cannot suppress the wrong half
because those readings hard-code `gender: n`, which `setdefault` will not
override.

*Proposed fix.* This one is **readings-only and changes no rows** — filter a
table reading whose explicit gender contradicts the entry's gender. It is
deferred here only because it is the same code path as B4 and should be done with
it. Roughly 40% of all generated second-declension rows carry a neuter reading
they should not.

---

**B6. A parenthesis in the headword line blocks the declension entirely.**

```
bellum (ante-class. and poet. duel-lum), i, n.
```

`HEAD` expects `word , word` and the parenthesis breaks the match, so `bellum`
declines not at all and the whole entry contributes one row.

*Proposed fix.* Strip balanced parentheses before matching `HEAD`, as
`pos_from_entry` already does via `strip_parens`. Affects `terra`, `virtus`,
`pecu`, `operio` and every other entry with a parenthetical variant.

---

**B7. Plurale tantum entries are called singular.** `divitiae, arum, f.` has no
singular, but the headword row claims `nom s f`.

*Proposed fix.* A genitive in `-arum`/`-orum`/`-uum` is a genitive **plural**, so
the entry is cited in the plural. Readings-only where the declension already
parses.

---

**B8. The gender-only fallback is emitted beside real readings.**

```
arma    acc p n|n
armaque arma  n
```

The bare `n` is the "we know only the gender" fallback and is noise next to
`acc p n`.

*Proposed fix.* Emit the gender-only reading only when no other reading exists
for that form. Readings-only, changes no rows.

---

**B9. The third-declension table gives masculine nouns a neuter plural.**
`rex, regis, m.` generates `rega` — `acc p n|nom p n|voc p n`. The `-a` ending
belongs to the neuter sub-paradigm of B4.

*Proposed fix.* Move it there, where gender selects it.

**Depends on gender detection** — §9.3. 6,986 of 7,436 third-declension entries
do not currently resolve a neuter gender, so moving `-a` without improving
detection loses real neuter plurals such as `ora` (1,459 tokens).

---

**B10. Homograph merging leaks a part of speech across senses.** `qui` (relative
pronoun) and `qui` (adverb) are separate L&S entries that merge onto one lemma,
so the pronoun's rows pick up `adv`.

```
qui   adv|nom s        gold: nom p m pron
```

*Proposed fix.* Needs the homograph number to survive into `forms_with_morph`,
which currently sees one entry at a time and cannot know. ~160 tokens.

---

**B11. L&S and Perseus disagree on the part of speech of some indeclinables.**
`etiam` is `conj.` in L&S and adverb in the treebanks; `ubi` likewise. ~330
tokens. **Not a bug on our side** — we report our source, and the entry is the
thing we are licensed to represent. Recorded so it is not re-investigated.

## 9.3 Regression check on the proposed fixes

Each fix in §9.2 that **removes** rows was measured against the corpus frequency
list before being recommended. Three of them, applied as written and on their
own, would have destroyed working coverage.

| fix | forms it stops generating | occur in corpus | tokens | verdict |
|---|---|---|---|---|
| B2 no declining verb entries | 58,166 | 6,849 | 276,180 | **unsafe as written** |
| B3 three-gender guard | 19,640 | 315 | 47,397 | **unsafe as written** |
| B1 drop unparseable perfects | 47,356 | 1,151 | 39,217 | safe in sequence |
| B4 neuter tables | 10,538 | 579 | 44,978 | safe in sequence |
| B9 move `-a` to the neuter table | 6,773 | 377 | 17,509 | safe in sequence |

### B2 is unsafe because `CONJ` is wrong, not because the guard is

Of the 13,819 entries where `CONJ` matches, only **5,116 (37%)** are verbs by
their own part-of-speech marker. The rest are nouns whose entry happens to
contain a digit 1–4:

```
abactus, us, m. abigo, a driving away        CONJ matched ", 4."
abavia, ae, f. avus, avia, mother of a ...   CONJ matched ", 1,"
abdicatio, onis, f. abdico, a renouncing     CONJ matched ", 4,"
```

Skipping the declension whenever `CONJ` matches would therefore delete the
paradigms of ~8,700 genuine nouns — `sine`, `suis`, `suo`, `senatus`, `natura`,
`solum`, `uerum` among them, 276,180 corpus tokens.

**Revised fix.** Skip the declension only where `pos_from_entry` returns `verb`,
which is the explicit `v. a.` / `v. n.` / `v. dep.` marker, never on `CONJ`
alone.

### B12 (new) — `CONJ` matches citation numbers

The same measurement is a defect in its own right: **~8,700 non-verb entries are
generating a full verb paradigm.** `abactus, us, m.` is inflected as a fourth
conjugation verb because a citation contains ", 4.".

*Proposed fix.* L&S writes the conjugation as part of the principal parts and
always follows it with the part of speech — "amo, avi, atum, 1, v. a." Require
`v.` after the digit. The present regex accepts `(`, `,`, `.` or a space, which
is what lets a citation through.

*Regression risk.* Tightening it removes the verb paradigm from every entry that
prints a conjugation number without `v.`; that has to be measured before the
change, the same way as the rest of this table.

### B3 is unsafe because it catches verbs, not three-gender citations

The entries it blocks are not `qui, quae, quod` — they are verbs whose third
principal part is a bare word:

```
lego, legi, lectum, 3, v. a.       ->  blocked
findo, fidi, fissum, 3, v. a.      ->  blocked
cieo, civi, citum, 2               ->  blocked
```

These currently decline (`lego, legi` parses as headword + genitive, stem `leg-`)
and produce `lege`, `legi`, `legos`… Their **readings are wrong** — `lege` is
labelled a vocative when it is an imperative — but the form→lemma mapping is
right, and `lege` alone is 1,432 corpus tokens. Blocking the declension deletes
the mapping and nothing replaces it.

**Revised fix.** Apply the revised B2 first: a verb entry does not decline, which
removes `lego`, `findo` and `cieo` from this set for the right reason. Only then
does the three-gender guard need to handle what remains, which is the genuine
`qui, quae, quod` case.

### The remaining fixes are safe only in sequence

B1, B4 and B9 each remove forms that a *different* fix is supposed to supply.

- **B4** drops `alius`, `alios`, `bonus`, `bonos` from the neuter entries
  `alium, i, n.` and `bonum, i, n.` — which is correct, those forms belong to
  `alius` and `bonus, a, um`. But `_noun_stem_and_key('bonus', 'a')` returns
  nothing, so no entry supplies them and the coverage is simply lost. B4 needs
  an adjective paradigm alongside it.
- **B9** drops `ora` from `os, oris` unless the neuter table picks it up, which
  needs the gender detected: **6,986 of 7,436** third-declension entries do not
  currently resolve a neuter gender.
- **B1** drops `lege`, `legi`, `petit` from the noun path; the corrected verb
  tables put them back with the right readings.

This is consistent with the prototype measured earlier: applied **together** they
moved corpus form coverage **up** (61.219% → 61.576%) while contradicted readings
fell from 11.5% to 4.6%. Applied piecemeal, each is a net loss.

**Rule for whoever picks this up: no fix in §9.2 ships alone.** Land B12 + revised
B2 + B1 as one change, then B3, then B4 + B9 with an adjective paradigm. Measure
`make morphacc` *and* `regress.py`'s `form_coverage_tokens` at each step; the
first must go up and the second must not go down.

### DONE — the readings-only fixes

These change no rows at all, so they carry none of the risk above and are legal
under the format-only constraint (C1). Verified readings-only: the row set and
every other column are identical to the build before them.

| fix | what it does | result |
|---|---|---|
| B5 | drop a table reading whose explicit gender contradicts the entry's | `uirum`, `equum`: `acc s m\|acc s n\|nom s n\|voc s n` → `acc s m` |
| B7 | a genitive in `-arum`/`-orum`/`-uum` means the entry is cited in the plural, read before the declension is attempted because the entries it matters for are the ones that do not parse | `diuitiae`: `f` → `nom p f` |
| B8 | drop any reading another reading in the same cell already covers | `arma`: `acc p n\|n` → `acc p n` |

B8 generalised while being written. The bare gender beside a full reading is one
instance of a rule: **a reading that states strictly less than another in the
same cell is not an alternative, it is noise.** `merge_morph` now parses each
rendered reading back into slots — the schema is positional and the slot
vocabularies are disjoint, so this is unambiguous — and drops the proper
subsets. It runs both inside `render_readings` and where `package.py` merges
readings from different sources.

#### B5 needed a guard, found by measuring

As first written B5 measured **worse**: −20 exact and +17 contradicted against
held-out treebank tags. Every one of the 20 was the same shape:

```
magnum   magnus   gold "acc s n"   we had  acc s m|acc s n|nom s n|voc s n
                                   B5 gave acc s m
```

`magnus`, `secundus`, `quintus`, `mundus`, `malus` are **adjectives**, which
inflect for all three genders — but the paradigm behind `magnum` comes from the
homograph proper noun `Magnus, i, m.`, and its `m.` was then used to deny the
adjective its real neuter. B5's premise — that the entry's gender applies to
every form of the lemma — is false exactly where a lemma has more than one entry
(B10).

`forms_with_morph` now takes `strict_gender`, and `package.py` switches it off
for the 2,176 homograph lemmas it already computes.

| | exact | contradicted | readings/cell |
|---|---|---|---|
| without B5 | 18,777 | 1,189 | 1.91 |
| B5 as first written | 18,757 | 1,206 | 1.85 |
| **B5 with the homograph guard** | **18,777** | **1,187** | **1.87** |

Zero regression, two tokens better, and fewer readings per cell — the impossible
claims went without taking any correct one.

## 9.4 Interaction analysis and the order to apply the rest

Everything below is measured on the whole dictionary, not reasoned about. The
simulator is `scratchpad/sim.py`: it regenerates the index under a configuration
of fixes and compares corpus coverage against the current build.

### The measurement itself had to be fixed first

A form is only **lost** if nothing else supplies it afterwards. Two mistakes made
the first pass useless:

1. *Per-entry counting.* Counting the forms an entry stops generating counts a
   form as lost even when the right entry still produces it. The commonest forms
   are generated by their own entry and by several wrong ones.
2. *Paradigm-only counting.* The treebanks and `lemma_map` supply forms
   independently of every fix here. `sit`, `erit`, `dicere`, `cui`, `iussit` are
   all annotated pairs at 0.99 and cannot be lost by a paradigm change at all.

Correcting both moved the headline number by an order of magnitude: the verb
gating fix went from an apparent **−276,180** tokens to a real **−25,790**.
Baseline coverage is 5,539,770 corpus tokens (80.597%), not the 61.7% the
paradigm alone accounts for.

A third trap caught me while writing this section: listing the entries that
*would also generate* a form is not the same as listing the forms a fix
**newly adds**. `cum`, `si` and `de` appear under a letter entry's adjective
paradigm, but they are already in the index from their own entries, so they are
not a gain — and reading that list as one made a well-attributed +210,808 look
like mass mis-attribution.

**Any future estimate here must use the same method**: whole-index, all sources,
net of what remains, and gains counted only against what was absent before.

### Net effect of each fix, measured alone

| fix | forms | corpus tokens | net lost | net gained |
|---|---|---|---|---|
| **adjective paradigm** (new, needed by B4) | 608,899 | **+210,808** | 0 / 0 | 21,175 / 210,808 |
| B6 strip parens before `HEAD` | 532,602 | **+39,843** | 234 / 2,483 | 2,725 / 42,326 |
| B4 neuter tables | 499,878 | **+6,859** | 263 / 2,212 | 464 / 9,071 |
| B3 three-gender guard | 487,971 | −1,783 | 128 / 1,783 | 0 |
| B9 `-a` only when neuter | 500,577 | −1,580 | 282 / 1,580 | 0 |
| B2+B12 verb paradigm by POS | 297,004 | **−25,790** | 1,763 / 25,790 | 0 |

### B13 (new) — the part-of-speech marker is cut off, and it blocks B2 and B12

`package.py` passes `txt(e)[:200]` and `pos_from_entry` then looks at the first
120 characters. L&S opens many entries with a parenthesis longer than that, so
the marker never reaches the matcher:

```
fero    pos=[]          jubeo  pos=[]          nego   pos=[]
trado   pos=[]          video  pos=[]
```

Five of the commonest verbs in Latin are not recognised as verbs. Gating the verb
paradigm on the part of speech — which is what B2 and B12 both require — would
therefore delete their paradigms. **That is the whole of B2+B12's measured
−25,790 tokens**: not a defect in the gate, a defect in what the gate reads.

*Proposed fix.* Pass the whole entry to `pos_from_entry`; the window is applied
after parentheses are stripped, so it still cannot reach the definition prose.
Measured: **322 entries gain a part of speech, and the form set of not one entry
changes.** B13 is therefore readings-only and can be applied on its own, before
anything that depends on it.

**It does not remove all of B2+B12's loss — only 44% of it.** Measured directly:

| | corpus tokens | net lost |
|---|---|---|
| B2+B12 without B13 | −25,790 | 1,763 forms |
| B2+B12 **with** B13 | **−14,463** | 1,137 forms |
| B13 alone | 0 | 0 |

The residue is irregular and deponent verbs whose forms are currently supplied by
the loose `CONJ` firing on some other entry: `tutum`, `ais` (*aio*), `utitur`
(*utor*), `reuerti` (*revertor*). Step 3 needed its own investigation of that 1,137-form residue: **§9.5**. The
answer is that 73% of it is wrong attribution being correctly deleted, so the
step is mostly a correction and the coverage gate proposed below is invalid for
it.

*Verify after applying:* `fero`, `video`, `jubeo`, `nego`, `trado` all resolve
`verb`, and `test_the_definition_prose_is_not_searched` still passes.

A second, much smaller gap in the same matcher: `abstineo, ui, tentum, 2, v. a
and n.` writes the subtype without a period, which the regex requires. **12
entries**, 9 of them also matching `CONJ`. Worth folding into B13; not worth its
own change.

### Dependency graph

```
B13  pos sees the whole entry          (readings-only; no dependencies)
  |
  +--> B2   verb entries do not decline
  +--> B12  verb paradigm gated on POS, not on a citation number
         |
         +--> B3   three-gender guard   (B2 removes 92% of its set first:
                                         2,238 entries -> 188)
         +--> B6   strip parens before HEAD
                   (B6 makes 2,640 more entries decline, including verbs
                    such as `abligurrio, ivi, itum, 4` -- so B2 must already
                    be in place or B6 adds new wrong declensions)

adjective paradigm                     (independent; purely additive)
  |
  +--> B4   neuter tables               (B4 alone drops `alios`, `bonos`,
                                         `ferre`; the adjective paradigm is
                                         what supplies them)
         |
         +--> B9   `-a` only when neuter  (BLOCKED, see below)

B10  homograph leakage                 (independent; already guards B5)
```

### Recommended order, with the gate for each step

Each step must be measured with `make morphacc` **and** `regress.py`'s
`form_coverage_tokens`. Accuracy must improve or hold; coverage must not fall.

| # | change | expected | gate |
|---|---|---|---|
| 1 | **B13** pos reads the whole entry | +322 entries with a POS; 0 form changes | form set byte-identical |
| 2 | **adjective paradigm**, minimum stem 3 letters | +210,808 tokens, no losses | coverage up, contradicted not up, no 1–2 letter stems |
| 3 | **B2 + B12** verb paradigm and declension gated on POS | −14,463 after B13, of which 73% is wrong attribution deleted (§9.5) | gate on `morphacc` **contradicted**, NOT on coverage; do not proceed if `fero`/`video` lose their paradigm |
| 4 | **B6** strip parens before `HEAD` | +39,843 tokens | verbs must not newly decline — B2 is in place |
| 5 | **B4** neuter tables | +6,859 tokens | `bonos`, `alios` still present (from step 2) |
| 6 | **B3** three-gender guard | −1,783, and −1,032 once step 2 is in | `quae` stops being a dative singular of *qui* |
| 7 | **B10** homograph leakage | removes `adv` from `qui` | `magnum` keeps its neuter (see B5) |
| — | **B9** | **blocked** | see below |

Cumulative through step 6, measured: **+233,472 corpus tokens (+4.2%)**, against
2,050 forms / 24,146 tokens net lost. Most of that loss is step 3's, and B13
removes a little under half of it; the rest is unexplained and gates the step.

#### The adjective paradigm needs a minimum stem length

Deriving the stem by stripping `-us`/`-er`/`-is` from the headword gives a
one-letter stem for L&S's single-letter entries, which then generates `cum`,
`si`, `de`, `te`, `eo` — the commonest words in Latin — attributed to the letter
`c`, `s`, `d`, `t`, `e`. `_noun_stem_and_key` already carries this scar
("`Spāco, cūs` … slicing the printed form gives the stem `c`, which then
generates cum, cui and cibus"); the adjective paradigm must inherit the guard.

Requiring three letters costs **3,476 tokens across 176 forms** and removes the
whole class. The forms that remain are well attributed — `dubium` ← *dubius*,
`necessarium` ← *necessarius*, `relictis` ← *relictus*, `proximum` ← *proximus*,
`armatorum` ← *armatus*.

### B9 was not blocked — that was a downstream symptom (corrected)

§9.4 recorded B9 as blocked because only 450 of 7,436 third-declension entries
resolved a neuter gender, and treated that as an independent prerequisite needing
its own investigation. It was not independent: it was **B13**. Once the part of
speech is read from the whole entry, every common neuter resolves —
`nomen`, `corpus`, `tempus`, `opus`, `genus`, `caput`, `iter`, with correct stems
(`nomin-`, `corpor-`, `tempor-`, `itiner-`) — and second-declension "no gender"
fell from 37.5% to 8.6%. B9 landed in step 08 with no special work.

The dependency graph below was missing that edge. Kept as written, with this
correction, because the lesson is the general one: a prerequisite that looks
independent may be a symptom of a defect earlier in the chain.

### B9 as originally assessed

B9 is net negative alone (−1,580) and still negative at the end of the sequence
(−1,030), because moving `-a` to the neuter table needs the gender, and gender
detection does not resolve it:

| declension | entries | gender detected |
|---|---|---|
| 2nd (`i`) | 9,132 | m 3,006 · n 2,438 · f 260 · **none 3,426** |
| 3rd (`is`) | 7,436 | f 3,706 · m 2,223 · **n 450** · none 1,033 |

Only **450** third-declension entries resolve neuter, when *nomen*, *corpus*,
*tempus*, *opus*, *genus* and their like are far more numerous. Losses are real
neuter plurals: `arida`, `itinera`, `marina`, `tegmina`.

**Do not apply B9 until gender detection is measured and improved.** That is its
own investigation, and B4 depends on the same signal — B4 survives only because
it is additive where the gender *is* known and leaves the rest alone.

### What this changed about the earlier plan

§9.3 recommended "B12 + revised B2 + B1 as one change, then B3, then B4 + B9".
That order is wrong in three ways:

- It puts the largest, safest, purely additive win (the adjective paradigm,
  +214,284 tokens) last instead of first.
- It starts with B2+B12, which is the only step that loses coverage, and which is
  blocked on B13 — a defect not then known.
- It pairs B4 with B9, when B4 is positive and B9 is negative and blocked.

## 9.5 The residue investigated — step 3 is a correction, not a loss

The 1,137 forms / 14,463 tokens that B2+B12 removes even with B13. Decomposed by
asking, for each, whether the **lemma** it currently resolves to is right. The
part of speech cannot be used to decide that — it is the thing that is failing —
so the test is this project's own gloss: a verb is glossed "to …".

| | tokens | share |
|---|---|---|
| **lemma is not a verb — wrong attribution today** | 10,551 | **73.0%** |
| from the declension gate, not the verb gate | 2,159 | 14.9% |
| lemma IS a verb by its own gloss — real loss | 1,753 | 12.1% |

### Three quarters of the "loss" is a wrong answer being deleted

```
oderunt   (71)  -> odor       "smell, scent, odor"
audito   (160)  -> auditor    "hearer"
liberato  (22)  -> liberator  "freer, deliverer"
praesis    (5)  -> praes      "surety"
```

`oderunt` is "they hate"; a reader tapping it is shown *odor*, "smell". These are
verb forms attached to **nouns that merely share a stem**, generated because a
citation number made `CONJ` fire on a noun entry (B12). Deleting them is the
point of the fix.

**This invalidates the gate I proposed for step 3 in §9.4.**
`regress.py`'s `form_coverage_tokens` counts a form as covered whether or not the
lemma is right, so it scores those 10,551 tokens as coverage and will always
report step 3 as a regression. Coverage alone cannot gate this step. The gate has
to be `make morphacc`'s **contradicted** count plus a check that the lemma-level
losses are the 12% below.

### The genuine 12% is recoverable

```
molientis  -> molio     "to build, erect"
largiendum -> largio    "to give bountifully"
uituperandi-> vitupero  "to find fault"
fauit      -> for       "to speak, say"
```

The lemma is right and the entry is a verb; only the marker is unreadable.
`molio, ire, 4 (act. collat. form of molior)` prints no `v.` at all, and
`for, fatus, 1, v. defect.` uses a subtype the list does not carry. Of the 1,753
tokens:

| recoverable by | tokens | share |
|---|---|---|
| headword shape (`-o`/`-or`/`-eo`/`-io`) **plus** a conjugation number | 1,305 | 74% |
| widening the `v.`-subtype list (`defect`, `semidep`, `incoh`, `irreg`) | 427 | 24% |
| neither | 21 | 1% |

The second is safe and obvious — add the abbreviations L&S actually uses.

The first needs care, because "headword ends in `-o` plus a conjugation number"
is exactly the false-positive pattern B12 exists to kill: `abdicatio, onis, f.`
ends in `-o` and has a citation number. It is only safe **in combination** — an
entry with a conjugation number, a verbal headword shape, and *no competing
part-of-speech marker*, since `abdicatio` carries `, f.`. That combination should
be measured on its own before it is trusted.

### Revised verdict on step 3

Not blocked. It removes 10,551 tokens of wrong attribution, keeps 2,159 for the
declension-gate analysis, and costs 1,753 tokens of which 1,732 are recoverable
by widening the marker. Sequence it as:

1. widen the `v.`-subtype list (+427 recovered, no risk)
2. measure the headword-shape-plus-number-plus-no-other-marker rule (+1,305)
3. then apply B2+B12, gated on `morphacc` contradicted, **not** on coverage

### Still open: the 2,159 tokens from the declension gate

14.9% of the residue is lost by B2's other half — verb entries no longer running
the *noun* declension — and has not been analysed. It needs the same treatment:
is the lemma right? `lego, legi` currently declines as a noun and produces `lege`
with a wrong reading but a right lemma, so some of this will be real loss that
the corrected verb tables (B1) must supply instead.

## 9.6 Applying the fixes — checkpoint log

Every step is built, measured and snapshotted before the next one starts
(`scratchpad/checkpoint.sh`, snapshots under `scratchpad/ckpt/`). A step is
accepted only if it does not regress; where it did, it was diagnosed and either
repaired or backed out.

`coverage` is corpus tokens whose form is indexed. `exact` / `contra` / `rate`
are from `make morphacc` on a held-out build.

| ckpt | change | rows | coverage | exact | contra | rate |
|---|---|---|---|---|---|---|
| 00 | baseline (format fix + readings-only) | 2,546,580 | 5,556,505 | 18,777 | 1,346 | 94.22 |
| 01 | B13 pos reads the whole entry | 2,546,580 | 5,556,505 | 20,467 | 1,412 | 94.26 |
| 02 | wider `v.`-subtype list | 2,546,580 | 5,556,505 | 20,471 | 1,412 | 94.27 |
| 03c | adjective paradigm | 3,043,357 | 5,786,815 | 23,008 | 1,371 | 94.99 |
| 04c | B1 verb tables from the principal parts | 4,751,693 | 5,963,707 | 25,588 | 1,379 | 95.39 |
| 05 | third-conjugation `-io`; abbreviation rule | 4,654,251 | 5,972,560 | 25,662 | 1,370 | 95.43 |
| 06 | B2+B12 verb paradigm and declension gated on POS | 2,863,712 | 5,963,095 | 25,615 | 1,348 | 95.47 |
| 07 | B6 parentheses stripped before `HEAD` | 2,942,446 | 6,009,727 | 27,134 | 1,380 | 95.54 |
| 08 | B4+B9 neuter tables; `-a` off the masculine | 2,864,164 | 6,014,801 | 27,453 | 1,383 | 95.58 |
| 09 | B3 three-gender guard | 2,847,147 | 6,007,087 | 27,314 | 1,036 | 96.63 |
| 10 | locative for place names; impersonal verbs | 2,843,174 | 6,008,025 | 27,373 | 983 | 96.81 |
| 11 | fifth declension `-ei`; three-gender guard narrowed | 2,845,920 | 6,011,783 | 27,499 | 968 | 96.87 |
| 12 | breve mark allowed in headwords | 2,859,649 | 6,016,098 | 27,629 | 965 | 96.89 |
| 13b | third-declension adjective paradigm | 2,956,405 | 6,050,813 | 28,240 | **966** | **96.96** |

**Net: coverage +494,308 tokens, exact +9,463, contradicted −380, rate
94.22 → 96.96.** 211 tests and zero off-schema values at every checkpoint; blank
cells 1.36% → 0.65%; two consecutive builds byte-identical.

`regress.py` at the end: `clean`, `enforce`, `suspect`, `xref` and `norm` all
**unchanged** — no gloss moved. `forms` and `stem` changed, which is the point of
the exercise, and **`form_coverage_pct` rose from 61.219**. `make baseline` has
NOT been run; that diff is for review.

### How the steps were run

`scratchpad/checkpoint.sh <name>` builds the package and a held-out build, runs
`morphacc` and the test suite, records `metrics.json`, and snapshots `inflect.py`,
`package.py` and `tests/` under `scratchpad/ckpt/<name>/`. A step is accepted only
if it does not regress; `scratchpad/diffck.py A B` lists the gold tokens that got
worse between two checkpoints, which is how each regression below was diagnosed.

One process failure worth recording: source was edited while checkpoint `04b` was
still building, so its package may mix two revisions. It is excluded from the
table. **Do not edit during a build.**

### B1 took six repairs, each found by investigating rather than accepting

1. **`amare` lost the present passive imperative.** A test caught it. The reading
   is correct Latin, so it was restored — and extended to all four conjugations —
   rather than the test weakened.
2. **Abbreviated parts overlap the stem.** "statuo, ŭi" is statu-I, not
   statu-Ui: the stem already ends in `-u`. The join is on the longest overlap.
3. **`-erit` and `-erint` are two things at once** — future perfect and perfect
   subjunctive (`praestiterit`, `habuerint`). Naming one denied the other. Same
   for `-eris`, `-erimus`, `-eritis`.
4. **Deponents print a participle, not a supine.** "miseror, atus, 1, v. dep."
   gives the stem `miserat-`; the parser only accepted `-um`.
5. **Third-conjugation `-io` verbs had no present tense at all.** `capio, cepi,
   captum, 3` gave the stem `capi` plus third-conjugation endings, so `capit` was
   absent and `capiit` invented. `capio`, `facio`, `fugio`, `iacio` are common
   verbs. They need the mixed paradigm: fourth-conjugation present, third-
   conjugation infinitive and imperative.
6. **The full-vs-abbreviated test misread every vowel-changing perfect.** A
   two-letter prefix match calls `cepi` abbreviated because it does not start
   like `capio`, and glued it on as `capcepi`. A body of three letters or more
   beginning with a consonant is a stem in its own right; L&S's real
   abbreviations (`avi`, `ivi`, `ui`, `atum`, `itum`, `ertum`) are shorter than
   that or start with a vowel. Verified across eight verbs, `operio, ui, ertum ->
   opert-` included.

Points 5 and 6 were found by **spot-checking output**, not by the metric — the
aggregate moved the right way while `capit` and `fecit` were missing entirely.
Metrics gate a change; they do not find what is absent.

### The measurement had to be fixed again at step 1

B13 looked like a regression: contradicted 1,346 → 1,412. Diagnosing it showed
the metric was at fault, not the change. A reading that is nothing but a category
— `adv`, `prep`, `conj` — shares no slot with an inflected gold tag, so
`compatible()` compared an empty intersection and called `adv` **compatible**
with `voc s m`. Plain disagreements were being scored as silence.

`eval/morphacc.py` now treats a categorial and an inflected reading as mutually
exclusive. On the corrected metric B13 is better on both counts: rate
94.22 → 94.26, exact 80.62% → 83.14%. The raw contradicted count still rises,
because B13 fills 1,326 cells that were previously blank — of those newly
answered, about 95% are right.

The remaining disagreements are the B11 class: `quam` is `adv.` in L&S and
tagged `conj` by Perseus; `hic` is `pron.` in L&S and `adv` in the treebank.

### The adjective paradigm needed three repairs before it was accepted

First build regressed the rate, 94.27 → 94.12. Three causes, all in my table:

1. **Missing readings.** `-a` had no feminine vocative (`alma`), `-um` no
   contracted genitive plural (`magnanimum` for *magnanimorum*, constant in
   verse), `-us` no vocative.
2. **The adverb.** A first/second-declension adjective forms its adverb from the
   same stem, and the treebanks lemmatise that adverb to the adjective: `longe`
   to *longus*, `vero` to *verus*, `primum` to *primus*. Without the adverbial
   reading on `-e`, `-o` and `-um` these were the largest single class of wrong
   readings — `uero` alone is 32 tokens.
3. **The stem guard**, applied from the start: `-us` headwords only (8,635 of
   9,050), minimum three letters. Without it a single-letter entry generates
   `cum`, `si`, `de`, `te`, `eo` against the letter `c`, `s`, `d`, `t`, `e`.

After the repairs the step is better than its predecessor on every axis:
coverage +230,310, exact +2,537, contradicted −41, rate +0.72.

## 9.8 Second round of fixes, and what the remaining errors are

After step 09 the remaining contradicted readings were classified rather than
guessed at. That changed what was worth doing next: B10, the last named item in
§9.2, turned out to be nearly empty, and three bugs nobody had recorded were
larger.

### B6 was already complete

B6 landed as checkpoint 07. Checked afterwards whether it was only partly
effective, because `strip_parens` removes **balanced** parentheses inside the
200-character slice the parser is given, and L&S has parentheses longer than
that. Measured: the residue is **16 entries** for the declension and **2** for
the adjective paradigm, and some of those stems are wrong anyway
(`anceps -> ancecipit`). Not worth doing. B6 is finished.

### B10 is not what it was recorded as

§9.2 recorded B10 as homograph leakage — one lemma, several L&S entries, the
part of speech of one bleeding onto the others. The actual entries say otherwise:

```
postremo   ONE entry   "postremo and postremus, a, um, v. posterus"
hic        ONE entry   "hic, haec, hoc, pron. demonstr."
penitus    TWO entries both adj.
```

None of these is a homograph collision. `hic` and `penitus` are adverbs that L&S
does not mark as adverbs anywhere in the entry — that is B11, our source does not
say it. `postremo` is a different bug: the entry heads with the ADVERB and the
"a, um" citation belongs to *postremus*, the word after it, but the adjective
fallback attaches `nom s m` to the headword.

**B10 as written is closed.** What is left under it belongs to B11.

### Rejected: reading an adverb out of the citation shape

The `postremo` case suggested a rule: an adjective-cited entry whose headword
ends in `-o` or `-e` is the adverb, not the masculine nominative. Checked the
candidates before writing it. Of 94, roughly three in twelve were real adverbs
(`assulose`, `benedice`, `citime`); the rest were place names (`Acharnae`,
`Asine`) and verbs (`angulo`, `augusto`). ~16 tokens of gain against a much
larger number of wrong `adv` labels. **Not applied.**

### Found while checking those candidates: the breve mark truncates headwords

Several bad candidates were not adverbs at all but truncations —
`altē^grădĭus` was being read as `altē`. L&S prints a breve mark **inside** the
word (`ăcădēmī^a`, `Ā^drastus`, `Aescŭlāpī^um`) and `^` was missing from `HEAD`'s
character class, so the pattern stopped at the mark, found no comma after it, and
the entry did not decline at all.

**595 entries.** `fold` strips the mark, so the stems are unaffected:
`academia` now gives `academiae`, `academiam`, `academiarum`, `academiis`.

### Fifth declension with an abbreviated genitive

L&S writes `dies, ēi`, and the fifth-declension branch required a genitive longer
than two characters. `dies` was therefore read as a second-declension genitive and
declined with the stem `dies`: `diese`, `dieser`, `diesorum`, `diesos`. The same
for `species`, `facies`, `fides`, `acies`. The Greek names in `-eus` (`Adoneus,
ei`) hit the same branch and produced `adoneusus`.

Both now handled: a headword in `-es` with that genitive is fifth declension
(`dies -> di-`), one in `-eus` is the Greek second (`Adoneus -> adone-`).

### My own three-gender guard was firing by mistake

`species, ēi (gen. sing. specie or specii, Matius ap. Gell. 9, 14, 15` has an
unclosed parenthesis, so splitting on commas made the third token begin with
`Matius`, which looks like a third nominative. The B3 guard blocked the
declension of an ordinary noun. It now requires the **second and third** tokens to
both be bare words, which `qui, quae, quod` and `bonus, a, um` satisfy and a
parenthesis fragment does not.

Introduced at step 09 and invisible to the metrics: the aggregate kept improving
while `species` silently lost its whole paradigm. Found by spot-checking output.

### Impersonal verbs and the locative

- **Impersonals.** "oportet, ui, 2, v. impers." is cited by its third singular,
  and the code treated it as a first singular and appended endings, giving
  `oporteteam`, `oportetebam`, `decetebam` — 39 dead forms for each of 41
  entries. Now 12 correct forms, third person only.
- **Locative.** Removed earlier as release-DB content, but `Romae` really is "at
  Rome". A capitalised headword is the signal L&S gives for a place name, so 3,466
  proper nouns get `loc s` on the right ending; `portae` does not. Adding a
  reading to a form that already exists cannot increase contradictions.

### What the remaining errors are

Classified on checkpoint 10 (983 tokens at that point):

| cause | tokens | share | fixable? |
|---|---|---|---|
| indeclinable: adv vs conj | 430 | 43.7% | **no** — B11 |
| inflection: case | 188 | 19.1% | partly — the fifth-declension fix took some |
| inflection: gender | 154 | 15.7% | mostly annotator variance |
| gold says indeclinable, we inflect | 97 | 9.9% | B11 |
| tense, voice, mood, number | 91 | 9.3% | irregular and defective verbs |
| we say indeclinable, gold inflects | 23 | 2.3% | B11 |

**The largest class cannot be fixed from L&S.** It marks `etiam` as `conj.` only,
`quam` as `adv.` only, `ubi` as `adv.` only, and the words are genuinely both.
There is no second marker in the entry to read.

The shipped package is better than this measurement suggests, because the
treebank supplies the missing category and `make morphacc` holds the treebank out
on purpose:

```
etiam  adv|conj     ubi      adv|conj     quoque  adv|conj
sicut  adv|conj     quoniam  adv|conj
```

The held-out number measures **our generator**. What a reader gets is the
generator plus the treebank.

## 9.9 Expanded comparison: five outcomes, not one number

A single "contradicted" figure hides which errors matter. The build is now scored
into five outcomes, because **blank and underspecified are not failures** — they
are silence, and silence is better than a wrong answer.

| outcome | tokens | share |
|---|---|---|
| exact | 27,629 | 57.6% |
| underspecified (says less than gold, contradicts nothing) | 2,456 | 5.1% |
| blank (a row, no reading) | 1,843 | 3.8% |
| absent (no row at all) | 15,056 | 31.4% |
| **wrong** | **965** | **2.0%** |

By what the gold tag is:

| | exact | undersp | blank | absent | wrong |
|---|---|---|---|---|---|
| nominal | 11,737 | 2,210 | 1,322 | 8,633 | 285 |
| indeclinable | 10,663 | 0 | 389 | 951 | **530** |
| verb | 5,229 | 218 | 124 | 5,466 | 149 |

**Absent is fifteen times larger than wrong.** That is where the quality is, and
closing it costs nothing in accuracy — those are forms not generated at all.

### Should we assert gender at all?

Gender is the slot most likely to be wrong, so it was measured rather than
argued: **where both we and the annotator state a gender, we agree 98.00% of the
time** (13,172 of 13,441). Dropping gender would fix 130 tokens and downgrade
13,172 exact readings to underspecified. Keep it.

Error shape, for the same reason:

| how far off | tokens | share |
|---|---|---|
| category — indeclinable adv/conj | 552 | 57.2% |
| more than one slot | 207 | 21.5% |
| gender only | 130 | 13.5% |
| case only | 68 | 7.0% |
| number, gender+number | 8 | 0.8% |

### A metric-satisfying fix is not the same as a correct one

An analysis of the wrong readings found 338 tokens where the form comes from an
ending we already generate, so **adding the gold reading to that ending would
satisfy the metric** — a cell matches if any of its readings matches, so an
addition can never turn a right answer wrong.

Most of those were rejected anyway, because they would be **false**:

```
NOUN[ae] -a  -> add "prep"        absurd; the lemma is simply wrong
NOUN[ae] -a  -> add "acc p n"     false for every feminine noun
NOUN[is] -is -> add "acc p"       right for an i-stem, wrong for `rex`
```

Adding readings to move a number is the thing "blank is better than wrong" rules
out. The ones applied were the ones that are certainly true of every word the
table touches — see the third-declension adjective below.

### The largest remaining error class cannot be fixed from L&S

430 of the wrong tokens are `adv` against `conj` on indeclinables. L&S marks
`etiam` as `conj.` only, `quam` as `adv.` only, `ubi` as `adv.` only, and the
words are genuinely both. There is no second marker in the entry to read. The
shipped package is better than this, because the treebank supplies the other
category and `make morphacc` holds the treebank out on purpose:

```
etiam  adv|conj     ubi      adv|conj     quoque  adv|conj
sicut  adv|conj     quoniam  adv|conj
```

### Third-declension adjectives: 1,970 entries with no paradigm

Found by reading the `absent` bucket rather than the error list. L&S cites a
two-termination adjective as "omnis, e, adj." and prints no genitive, so
`_noun_stem_and_key` found nothing and **1,970 entries generated their headword
and nothing else** — `omnis`, `fortis`, `gravis`, `brevis`, `mortalis`,
`immanis`, among the commonest words in Latin.

`fortis` needed a second fix: "fortis (archaic form FORCTIS, Fragm. XII. Tab. ap.
Fest. s. v. sanates" hides the ", e," behind an unclosed parenthesis, so the
citation tests now read the whole entry as the part-of-speech matcher already
did.

**The first version regressed the rate** (96.89 → 96.72) while adding 34,424
tokens of coverage — which looks like the coverage/accuracy trade-off, and was
not one. Both causes were readings left out of the table:

- `-is` **is** the accusative plural of an i-stem adjective. It was omitted out of
  caution borrowed from the noun tables, where `regis` must not be called an
  accusative plural of *rex* — but this table only runs on entries cited
  "X, e, adj.", so that risk does not exist here.
- `-e` and `-ius` are also the adverb (`facile`, `facilius`), the same fact
  already applied to `-e` and `-o` in the first/second declension and simply not
  carried over. `-iter` (`fortiter`) was added with them.

With those, the step beats its predecessor on every axis: coverage +34,715,
exact +611, contradicted +1, rate 96.89 → 96.96.

**The trade-off was a gap in the table wearing the costume of a trade-off.**

## 9.7 What the "WORSE" detector metrics mean

`regress.py` reports several gloss-quality detectors as worse:

```
ungrounded       36,990 -> 57,257 tokens   (0.538% -> 0.833% of corpus)
empty            99,578 -> 112,984
etymology-leak    2,630 -> 3,915
```

**No gloss changed.** The `clean`, `enforce`, `suspect` and `xref` probes are
unchanged, so the gloss text is byte-identical to what it was.

What changed is the weighting. These detectors count *corpus tokens that reach a
defective gloss*, and `attributed_tokens` rose from 5,907,727 to 9,091,335
because far more forms now resolve to a lemma. A lemma whose gloss is ungrounded
and which used to match 200 tokens of Perseus may now match 400.

So this is not an artifact to discount. The glosses were always this good or bad;
the difference is that a reader now actually meets them. The honest reading is
that **this work makes the existing gloss defects more visible and raises the
priority of the repair work in `REVIEW.md`** — not that anything here made the
package worse. The two metrics that measure this change both improved.

## 9.10 Delivery check

Run against the built ZIP, following §7a of `DICTIONARY_IMPORT_FORMAT.md`.

| check | result |
|---|---|
| three members, at the archive root | yes |
| every `morphology.csv` lemma resolves in `dictionary.csv` | 48,608 lemmas, **0 unresolved** |
| lemmas are dictionary forms, not stems | `cohibiliter`, `praescientia`, `asylum`, `versicolor` |
| homographs kept distinct | 2,176 numbered lemmas retained |
| required fields non-empty | 0 bad rows in either file |
| `confidence` within 0–1 | 0 out of range |
| three-candidate cap | 0 forms exceed it |
| duplicate (form, lemma) pairs | 0 |
| `morph_info` on schema | 716 values, 0 off-schema, **0 provenance strings** |
| values needing CSV quoting | 0 |
| blank `morph_info` | 0.43% |
| gloss length | peaks at 3–4 words |
| test suite | 211 pass |
| two consecutive builds | byte-identical |
| glosses (`clean`, `enforce`, `suspect`, `xref`, `norm`) | unchanged |
| `form_coverage_pct` | 61.219 → **73.604** |

### Not verified

**That the app imports it.** Everything above is static checking of the CSVs
against the written spec. Nobody has loaded the package into the application.

### Open before shipping

1. **`regress.py`'s baseline is stale.** `forms`, `stem` and `lemmafreq` changed
   on purpose. `make baseline` has NOT been run; that diff needs review.
2. **`morphology.csv` is 206 MB raw** (14.8 MB zipped) against the 131 MB the
   format doc cites for a complete Latin package. The doc says the file is
   streamed in batches, so size is not a memory problem, but it is 57% larger
   than their reference.
3. **966 readings are known wrong**, 2.0% of answered tokens; 430 of those are
   the `adv`/`conj` case L&S cannot settle (§9.9).
4. **This is no longer a format-only change.** The package went from 1,543,203
   rows to 2,956,405. That was the instruction from "continue with the remaining
   fixes" onward, but it means the deliverable should be reviewed as a content
   change, not as a relabel of one column.

## 10. Log

| # | Action | Outcome |
|---|---|---|
| 1 | Audited `.orig` | `morph_info` = 6 provenance values, 0 morphology |
| 2 | Labelled ending tables; `forms_with_morph` added | All columns but `morph_info` byte-identical to `.orig` — verified |
| 3 | Ad-hoc vocabulary | **Rejected** (C3). Rewrote onto one schema |
| 4 | Adopted app's schema from release DB | Format kept; content taken with it |
| 5 | Content from release DB | **Rejected** (C4). Removed, re-derived |
| 6 | Built `eval/morphacc.py`, measured accuracy | 74.3% exact / 11.5% contradicted |
| 7 | Fixed generator defects | 84.3% / 4.6% — but changed 1.6M rows |
| 8 | Row-set change | **Rejected** (C1). Reverted generator to `.orig` behaviour |
| 9 | Verify AC1–AC5 | 7,092 rows missing — headword no longer unconditionally indexed |
| 10 | Always index the headword | Row set matches `.orig` exactly |
| 11 | Verify AC1–AC5, tests, regress | **all pass; regress unchanged on 8/8 probes** |
| 12 | Document defects + proposed fixes (§9). No code changed | §9.1 enclitic pre-split required; §9.2 eleven content bugs recorded |
| 13 | Implement AC0 — enclitic pre-split | `virumque` → *vir* + *que*. Non-enclitic rows identical to `.orig`; 211 tests pass; regress 8/8 unchanged; builds reproducible |
| 14 | Regression-check every §9.2 fix against the corpus (§9.3) | B2 and B3 **unsafe as written** — would delete 276,180 and 47,397 corpus tokens. Both revised. New defect B12 found: `CONJ` matches citation numbers, so ~8,700 non-verb entries generate a verb paradigm. Sequencing rule recorded |
| 15 | Apply the readings-only fixes B5, B7, B8 | Readings-only confirmed: row set and every other column unchanged. B5 measured worse on first writing and needed a homograph guard; final: 0 regressions, 1,187 contradicted (best measured), 211 tests, regress 8/8 unchanged, builds reproducible |
| 16 | Interaction analysis of the remaining fixes (§9.4) | Measurement method corrected — per-entry, paradigm-only counting overstated loss ~10x. New blocker **B13**: `pos_from_entry` is cut off by truncation, so `fero`, `video`, `jubeo`, `nego`, `trado` are not seen as verbs; B2 and B12 cannot land before it. Order revised — adjective paradigm goes first, B9 blocked on gender detection |
| 17 | Review of §9.4 — two of its own claims were wrong | B13 removes **44%** of B2+B12's loss, not all of it (−25,790 → −14,463), so step 3 stays blocked on a 1,137-form residue. Adjective paradigm needs a **minimum 3-letter stem** or it attributes `cum`, `si`, `de` to letter entries; with the guard, +210,808 tokens and the gains are well attributed |
| 18 | Investigate the 1,137-form residue (§9.5) | **73% is wrong attribution being deleted** — `oderunt`→*odor*, `audito`→*auditor*. Only 12% is real loss and 99% of that is recoverable. Coverage is an invalid gate for step 3, because it scores wrong attributions as coverage |
| 19 | Close the declension-gate item by simulating B1 | B2+B12+B13 alone is −14,463; **with B1 it is +157,817**. The item closes: B1 supplies what the declension gate removes |
| 20 | Apply the fixes with checkpoints (§9.6) | B13, wider `v.` markers, adjective paradigm, B1, 3rd-`io`, B2+B12, B6, B4+B9, B3 — all accepted. **rate 94.22 → 96.63, coverage +450,582, exact +8,537.** Nine regressions caught and repaired rather than accepted, three of them in my own measuring tools |
| 21 | Second round: locative, impersonals, fifth declension, breve mark, third-declension adjectives (§9.8, §9.9) | rate 96.63 → **96.96**, blank 0.65% → 0.43%. B10 closed as miswritten; the `-o`/`-e` adverb rule rejected after measuring its error rate |
| 22 | Delivery check against the format's own checklist (§9.10) | all static checks pass; app import not verified |
