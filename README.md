# lsgloss

Generate a short English gloss (1–5 words) for every entry in **Lewis & Short,
*A Latin Dictionary*** (Clarendon Press, 1879) using a local, open-weight LLM.
No API keys, no network calls at inference time.

Output is a TSV of `key / headword / gloss / source`:

```
abjectus	abjectus	to cast away	xref-resolved
oppugnator	oppugnātor	assaulter, attacker, assailant (class.)	model
stellula	stellŭla	little star, asterisk	model
tunica	tŭnĭca	tunic	model
```

## Revision 2026-09-12

Built from the same model replies as the 2026-09-11 package; every change is a
rule applied uniformly and reproduced by `make rebuild` + `make package`.

- **Glosses.** The word cap no longer cuts "of or belonging to a deity" down to
  "of or belonging" (555 rows). A cross-reference is no longer resolved through
  the `v.` inside `adv.` or through `v. a.` (which glossed 19 entries "first
  letter of the Latin alphabet"). "false reading ..." notes are detected and
  dropped. L&S's six name-category phrasings render as two English ones.
- **Package.** Flagged and detector-rejected rows are not shipped (see *Rows
  that do not reach the bar*). Every `-que`/`-ve` particle row reads `conj
  enclitic`, and the particle is joined to hosts from every source, not only
  the paradigms (`eiusque`, `quibusque`).
- **Paradigms.** Abbreviated genitives are joined properly (`filius, ii` ->
  *filii*, not *filiusi*; `homo, inis` -> *hominis*, not *hoinis*; `pater, tris`
  -> *patris*, not *pattris*); the third-declension dative singular exists;
  parisyllabic nouns cited "civis, is" decline; i-stem endings go to i-stems
  only; second-declension nominatives are made only where the headword has
  them (no *populer*, *agrer*, *librus*); deponents build on the right stem
  (`vereor` -> *veretur*, not *vereoreo*) and take only their passive-form
  endings. Held out from the treebanks: exact readings 58.9% -> 61.5% of gold
  tokens, contradicted 2.0% -> 2.0%, corpus form coverage 73.6% -> 77.4%.
- **Pipeline.** A failed model call is retried on the next run instead of
  being checkpointed as its own error; judge scores are read from the start of
  the reply; the scores TSV can no longer carry a newline inside a field. The
  regression baseline is accepted and `make check` is green (254 tests).

## How it works

Each entry is resolved by the cheapest method that works. Measured on the shipped
`out/ls_glosses.tsv`, all 51,643 rows, with each stage's flag suffixes folded in:

| source | what it means | rows | share |
|---|---|---|---|
| `model` | sent to the LLM | 39,120 | 75.8% |
| `xref-resolved` | entry is a pure cross-reference (`v. condicio`); the target entry's gloss is inherited | 7,266 | 14.1% |
| `repaired` | model declined; re-asked with a prompt that forbids declining | 2,560 | 5.0% |
| `no-gloss` | genuinely nothing to gloss (unresolvable pointer, or an editorial note) | 865 | 1.7% |
| `hard` / `hard2` | gloss a mechanical detector objected to, sent back through the re-gloss passes | 887 | 1.7% |
| `named` | proper-name prompt | 405 | 0.8% |
| `freqfix` | re-glossed in corpus-frequency order (*Fixing the words readers actually meet*) | 339 | 0.7% |
| `xrefix` | cross-reference re-glossed across a part-of-speech boundary | 138 | 0.3% |
| `refilled` | row was empty; `xrefix.py` filled it | 63 | 0.1% |

Two suffixes ride on top of the stage name: `~` means `enforce` condensed the
gloss to fit the 5-word cap (3,778 rows) and `?` means it failed the grounding
check and is flagged rather than deleted (536 rows). The TSV keeps every row;
the package does not ship the flagged ones (*Rows that do not reach the bar*).

There are **no `tr` rows**: reusing the dictionary's own `<tr>` tag needs
`--use-tr`, which is off by default, because on a long entry the first `<tr>` can
belong to any sense — *sum* comes back "nor is she ashamed".

Cross-references are **resolved, never emitted as placeholders** — `abjectus`
(“v. abicio”) inherits *abicio*’s gloss rather than printing `XREF`.
Citations are stripped from every gloss (`raven-black color, Vitr. 8, 3` →
`raven-black color`) while register labels are kept (`lameness, limping (post-Aug.)`).

## Requirements

- Apple Silicon Mac or any machine with ≥16 GB of GPU/unified memory
- ~14 GB disk for the model
- Python 3.10+

Developed on a MacBook Air M4 (10 GPU cores, 32 GB) — see *Performance* below.

## Setup

### 1. Get the dictionary

```bash
git clone https://github.com/PerseusDL/lexica data-sources/lexica
# the file used is:
# data-sources/lexica/CTS_XML_TEI/perseus/pdllex/lat/ls/lat.ls.perseus-eng2.xml
```

`eng2` is the newer revision (2023 retagging pass); `eng1` is also A–Z but older.

### 1b. Get the treebanks and the corpus

Both are needed to *build* the package, not just to evaluate it: the treebanks
supply gold form→lemma pairs and decide which lemma an ambiguous form is ranked
under, and the corpus supplies the frequency list that every quality number in
this project is weighted by.

```bash
git clone https://github.com/PerseusDL/treebank_data   data-sources/treebank_data
git clone https://github.com/PerseusDL/canonical-latinLit data-sources/canonical-latinLit
```

`canonical-latinLit` is large (~1.5 GB); `--depth 1` is enough.

### 2. Build llama.cpp

```bash
git clone https://github.com/ggml-org/llama.cpp
cmake -B llama.cpp/build -S llama.cpp -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
cmake --build llama.cpp/build --config Release -j
```

### 3. Get the model and convert it

`openai/gpt-oss-20b` ships MXFP4 safetensors; OpenAI publish no GGUF, so convert
locally. The MoE weights are *repacked*, not requantised — the GGUF carries
OpenAI's exact MXFP4 values.

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt huggingface_hub[cli]
./venv/bin/hf download openai/gpt-oss-20b --local-dir gpt-oss-20b \
    --exclude "original/*" "metal/*"     # the full repo is 41 GB; you need 13.8 GB
./venv/bin/python llama.cpp/convert_hf_to_gguf.py gpt-oss-20b \
    --outfile models/gpt-oss-20b-mxfp4.gguf --outtype auto
```

### 4. Start the server

```bash
./llama.cpp/build/bin/llama-server -m models/gpt-oss-20b-mxfp4.gguf \
    --jinja -c 8192 --port 8080 --reasoning-budget 0
```

`--reasoning-budget 0` is important: this is a mechanical task, and the model's
chain-of-thought otherwise costs ~2.5x the wall-clock for no accuracy gain.

### 5. Run

```bash
make run          # or: python3 lsgloss.py --xml <path-to-xml> -j 4
```

Resumable — results are checkpointed per entry to `out/ckpt.jsonl`. Re-running
after a crash, reboot, or Ctrl-C continues from where it stopped.

### 6. Reproduce the published package

`make run` produces glosses; it does not produce the importable ZIP. The full
path from a fresh checkout to `out/lewis-short-glosses.zip` is below, in order.
Each step is resumable and each writes a file the next one reads, so the chain
can be stopped and restarted at any point.

```bash
make freq         # corpus frequency list      -> out/latin_freq.tsv   (no model; ~10 s)
make run          # gloss all 51,643 entries   -> out/ls_glosses.tsv   (gpt-oss; ~12 h)
make score        # judge every gloss          -> out/scores_full.tsv  (gpt-oss; ~12 h)
make lemmas       # model lemmas for irregulars-> out/lemma_map.tsv    (gpt-oss; ~2 h)
make freqfix      # repair frequent entries    -> out/ls_glosses.tsv   (gpt-oss; ~4 h/band)
make package      # build the importable ZIP   -> out/lewis-short-glosses.zip (no model)
```

Two stages that produced rows in the shipped TSV have no `make` target and are run
directly. Both rewrite `out/ls_glosses.tsv` in place, so they belong before
`make package`:

```bash
python3 xrefix.py --xml <ls.xml> --tsv out/ls_glosses.tsv   # gpt-oss; 138 xrefix + 63 refilled rows
python3 refinalise.py --tsv out/ls_glosses.tsv              # re-apply clean+enforce, no model
```

Steps needing a model expect `llama-server` on port 8080 (§4). `make freq` and
`make package` run without it, so a checkout that only wants to rebuild the ZIP
from the published TSVs needs no model at all.

Three more targets need no model either, because they rebuild a data product
from its checkpoint with the current rules. A fix to `clean_gloss.py`,
`suspect.py` or the cross-reference resolver reaches the shipped data this way
rather than through a day of model time:

```bash
make rebuild        # out/ls_glosses.tsv from the raw replies in ckpt.jsonl (--offline);
                    # rows from the model-verified stages (xrefix, freqfix) are carried over
make lemmas-offline # out/lemma_map.tsv from lemma_ckpt.jsonl
python3 score.py --xml <ls.xml> --ckpt out/score_full.jsonl --out out/scores_full.tsv -n 0 --offline
```

The checkpoints live beside the TSV that `make run` wrote. For the shipped data
that is the working tree above this repository (`../out/`), which the Makefile
finds on its own; they are not committed.

Wall-clock totals are for a MacBook Air M4; see *Performance*.

The adapt stage (`--adapt`) is off by default; the shipped data was built without
it (*The adaptation stage should be turned off*).

## Performance

Measured on a MacBook Air M4 (10 GPU cores, 32 GB, fanless):

| | |
|---|---|
| prefill | 384 tok/s |
| generation | 25.4 tok/s |
| end-to-end | 0.79 entries/s at `-j 4` |
| full dictionary | ~13 h (37,942 model calls of 51,643 entries) |

Concurrency past `-j 4` does not help — decode is memory-bandwidth-bound and
`-j 8` measured *slower*. Expect the model to hold ~13 GB resident.

## Scoring

`score.py` has the model grade the glosses against their entries, 0-5:

```bash
python3 score.py --xml <xml> --tsv out/ls_glosses.tsv -n 2000
```

The judge is the same model that wrote the glosses, but this is not a
preference judgement: it scores one gloss against the dictionary entry, which it
is shown, with no indication of where the gloss came from. Grading a candidate
against source text is verification, not taste, so the self-preference effect
reported for comparative LLM judging does not apply here. In practice the judge
runs *harsh* on its own output — it scored the pipeline's headword-echo glosses
0, and an earlier rubric had to be loosened because it was marking correct noun
glosses as "not a gloss".

The real limitation is **correlated error**: one model, so a construction it
misreads when glossing it may misread the same way when judging, and a wrong
gloss passes unflagged. That is a shared blind spot rather than inflation. It
argues for the mechanical cross-check below, and for a second model if one is
ever available — not for discounting the score.

The sample seed is fixed so runs are comparable.

Every score is cross-checked against `ground.py`, which is model-independent. If
the judge stops separating grounded from ungrounded glosses, it has stopped
measuring anything:

```
                                        n     mean judge score
ungrounded (grounding score 0.0)     7,475            4.19
grounded (anything above 0.0)       43,331            4.67
```

Over the whole committed `out/scores_full.tsv`: mean **4.60 / 5**, 95.9% at 4 or
better. By source, `model` 4.71 (n=39,393), `xref-resolved` 4.22 (n=6,464),
`repaired` 4.17 (n=2,597).

### The judge must be shown the entry the gloss actually came from

A cross-reference entry ("asperiter, adv., v. asper") contains no definition of
its own. Judged against that stub, correct glosses look unsupported: `asperiter`
-> "roughly" and `ad-amussim` -> "exactly" both scored **0**, "no English sense
given". The judge now follows the reference and is shown the target entry.

The correction moved `xref-resolved` from 3.19 to 4.13 and the overall mean from
4.52 to 4.60 -- and it invalidated a conclusion. On the broken metric,
cross-references looked like the dominant defect (60% of all low-scoring rows),
and a whole adaptation stage was built to fix them. Measured properly, an A/B
against a `--no-adapt` build showed adaptation was a wash: 3.95 unadapted vs
3.93 adapted.

The lesson generalises: a metric that scores one component far below the rest is
as likely to be measuring that component wrongly as to be finding a real defect.
Check what the judge is actually shown before optimising against it. The
`ground.py` cross-check did not catch this, because for cross-reference rows
both measures were reading the wrong entry.

### Adaptation is limited to adverbs

`--no-adapt` disables it. Adapting an adverb to its own part of speech is right:
`impure` glossed "impurely" beats "unclean, filthy, foul", which is the
adjective's meaning. Adapting participles is not: `bibitus` is a perfect PASSIVE
participle ("drunk"), and adaptation produced the present active "drinking".
Over all cross-references the two effects cancelled, so only adverbs are
adapted. Measured effect on the corpus mean is within noise (4.59 vs 4.60); it
is kept for correctness on the rows it touches, not for the aggregate.

`out/scores.tsv` carries a score and a short reason per gloss; sort ascending to
review the worst.

### Cross-reference inheritance is the weakest path

`xref-resolved` scores lowest because inheriting a target's gloss assumes the
two words mean the same thing. That fails across parts of speech: `acutum` (the
adverb, "sharply") inherits `acuo` ("to sharpen, whet"); `aequaliter`
("equally") inherits "equal, like, same age". The gloss is about the right
concept but the wrong word class. Resolving these properly would mean deriving
an adverbial gloss from the target rather than copying it.

### The judge's rubric matters more than you would expect

An earlier rubric scored short noun phrases ("waterbucket", "field of onions")
as "not a gloss", which depressed the mean by roughly 0.2 and made
`xref-resolved` look far worse than it is. If you change `prompts/judge-*.txt`,
re-check the grounding cross-check before trusting the new numbers.

## Multiple models

Three open-weight models are used, from three different labs so their errors are
uncorrelated. The gpt-oss GGUF is the local conversion from §3, since OpenAI
publish none:

| model | lab | arch | role | cost/call |
|---|---|---|---|---|
| `gpt-oss-20b` | OpenAI | MoE, 3.6B active | glossing | 0.8 s |
| `gemma-4-31B-it-qat` | Google | dense, QAT q4_0 | independent judge | 2.4 s |
| `Muse-Glimmer-30B` | Meta | dense | hard-case adjudication | ~60 s |

Only one fits in 32 GB at a time, so they are used as sequential passes over the
same TSV, never as a live ensemble. Swap by restarting `llama-server`; nothing
else changes.

### Reasoning settings differ per model, and it matters enormously

All three emit a reasoning channel that llama.cpp reports separately from
`content`. If the token budget runs out during reasoning, `content` comes back
EMPTY -- which looks like the model failing when it is only being cut off.

| model | setting | result |
|---|---|---|
| gpt-oss | `--reasoning-budget 0` | works, 2.5x faster than reasoning on |
| Gemma 4 | `--reasoning-budget 0` | works, **25x faster** (2.4 s vs 60 s) |
| Glimmer | `--reasoning-budget 0` | returns nothing at all -- needs reasoning on, `max_tokens>=512` |

Glimmer is the exception: with reasoning suppressed it emits no content under any
prompt (four different framings tested, all empty). It has to keep its reasoning
channel and be budgeted for it.

Judge accuracy on a fixed 7-case set covering every known failure type
(fabrication, word-class description, bare echo, semantic error, and three
correct glosses):

| model | correct | note |
|---|---|---|
| Glimmer (reasoning on, 512 tok) | 6/7 | caught `sabucus` -> "sambuca player" with the reason "elder-tree not musician" |
| Gemma 4 (reasoning off) | 6/7 | same catch, at 1/25th the cost |
| gpt-oss | -- | passes `sambuca player`; this is the blind spot the others cover |

Both independent judges catch the semantically-wrong-but-well-formed errors that
mechanical detectors and gpt-oss's own judging miss. That is the whole reason for
using more than one model.

### Prompt sensitivity

gpt-oss is a mixture-of-experts model, so the prompt is partly a routing
decision -- which experts fire depends on how the task is framed, not only on
what is asked. Rewording had outsized and uneven effects during tuning (the
prompt revisions gained 40, then 12, then 8 points), which is not the smooth
response a dense model gives. Treat prompt changes for gpt-oss as experiments to
be measured against `eval/gold.tsv`, not as edits.

The dense models (Gemma, Glimmer) respond more predictably, which is part of why
they make better judges: a judge whose behaviour swings with phrasing is not a
stable instrument.

## Two-judge consensus

The same 600 glosses were scored independently by gpt-oss (which wrote them) and
by Gemma 4 (which did not):

| judge | mean | >=4 |
|---|---|---|
| gpt-oss, self | 4.59 | 93.8% |
| Gemma 4, independent | **4.76** | 95.7% |

They agree within one point on **574 of 600 rows (96%)**. The independent judge
scores *higher* than the model that produced the glosses, which is the opposite
of the inflation one might expect -- gpt-oss is harsher on its own output.

Practical throughput on real entries (~800 characters, not the short prompts of a
microbenchmark): gpt-oss 0.8 s/row, Gemma **7.7 s/row**. Judging the whole corpus
with Gemma would take ~13 h, so it is used on targeted subsets.

### Use agreement, not a single score, to choose repair targets

Where both judges score a row <=2, the gloss is almost always genuinely wrong
(`October` -> "month of the eighth year"; `ferricrepinus` -> "ferrum + crepo",
which is the etymology rather than a meaning). That intersection is a far more
precise repair list than either judge alone.

Where they disagree by >=3 points, one of them has a blind spot -- and it is not
always the same one:

| headword | gloss | gpt-oss | Gemma | correct |
|---|---|---|---|---|
| `Juverna` | "Ireland" | 0 | 5 | Gemma |
| `Dardanus` | "preceding article" | 5 | 0 | Gemma |
| `benefactum` | "well" | 0 | 5 | gpt-oss (it means "good deed") |
| `Phryxeus` | "phrixus, a, m" | 0 | 5 | gpt-oss (bare echo) |

Neither model is uniformly the better judge. This is why a single judge, however
carefully prompted, cannot certify a dataset: it certifies only the part of the
problem it can see.

```bash
python3 score.py --xml <xml>                                   # gpt-oss rubric judge
python3 score.py --xml <xml> --judge judge-terse --maxtok 16   # Gemma/Glimmer, reasoning off
python3 consensus.py --xml <xml> --scores out/scores.tsv --below 3   # second judge on flagged rows
python3 refine.py  --xml <xml> --scores out/both_bad.tsv            # repair the intersection
python3 verify.py  --xml <xml> --before out/both_bad.tsv --score-col 6   # other model verifies
```

### The repair loop, and why each step uses a different model

```
gpt-oss scores everything          cheap, finds candidates
Gemma re-scores what it flagged    independent confirmation
gpt-oss repairs the intersection   only rows BOTH judges call bad
Gemma verifies the replacements    keeps only those it scores >=4
```

No step is checked by the model that performed it. This matters: on a 355-row
trial, **59% of the rows gpt-oss flagged were rated fine by the independent
judge**, so repairing on one judge's word would have rewritten ~210 good glosses.
Of the 144 both judges condemned, 51 were successfully rewritten and **46 (90%)
were independently confirmed at 4 or better**.

`verify.py` uses an absolute bar (`--keep-min 4`), not "better than before".
Rows that were already scored 2 are beaten by almost anything, so the relative
test let `bocas` "sea-fish" -> "box" through. Rows where neither version reaches
the bar are marked `!` in the source column rather than quietly accepted.

### Throughput, measured

| pass | rate | full corpus |
|---|---|---|
| gpt-oss judging | 0.81 rows/s | ~17 h |
| Gemma judging | 0.13-0.26 rows/s | ~13 h (used on subsets) |
| gpt-oss glossing | 0.5-0.8 rows/s | ~13 h |

Concurrency past `-j 4` does not help judging either: `-j 8` measured *slower*
(0.71 vs 0.81 rows/s). The machine is saturated at four.

## Corpus-scale results

Every gloss in the corpus was scored, then the failures were confirmed by a
second model, repaired, and re-verified by that second model.

| stage | rows | outcome |
|---|---|---|
| gpt-oss scored every gloss | 50,806 | mean **4.60/5**, 95.9% at >=4 |
| flagged <=2 | 2,031 | 4.0% of the corpus |
| Gemma re-judged those | 2,031 | **1,000 both-bad**, 964 disputed, 67 cleared |
| gpt-oss repaired the both-bad set | 1,000 | 435 rewritten |
| Gemma verified the rewrites | 435 | **399 kept** (>=4), 3 reverted, 33 unresolved |

Corpus-wide score distribution before the repair cycle:

| score | rows | share |
|---|---|---|
| 5 | 37,128 | 73.1% |
| 4 | 11,598 | 22.8% |
| 3 | 49 | 0.1% |
| 2 | 471 | 0.9% |
| 1 | 569 | 1.1% |
| 0 | 991 | 2.0% |

Counted from the committed `out/scores_full.tsv`. Note that 1,629 of those rows
(3.2%) record a gloss that has since changed, so the scores are a snapshot of the
run, not of the shipped TSV.

By source, with real sample sizes:

| source | mean | n |
|---|---|---|
| model | 4.71 | 39,393 |
| named | 4.55 | 412 |
| hard | 4.49 | 700 |
| xref-resolved | 4.22 | 6,464 |
| repaired | 4.17 | 2,597 |
| xref-adapted | **3.91** | 981 |

### The adaptation stage should be turned off

`xref-adapted` is the worst source in the corpus, scoring below the
`xref-resolved` rows it was meant to improve. It was built against the judge
that could not see cross-referenced entries, narrowed to adverbs when an A/B was
ambiguous, and now measures worse than doing nothing on n=981. Run with
`--no-adapt`. This is recorded rather than quietly deleted because the reasoning
that produced it looked sound at each step.

### Rows that do not reach the bar are marked, not dropped -- and not shipped

Where neither the original nor the repaired gloss reaches the quality bar,
`verify.py` appends `!` to the source column. The grounding check appends `?`
(536 rows) and `enforce` appends `~` (3,778 rows). The TSV keeps all of them,
marked, so they can be reviewed and repaired.

The package is what a reader sees, and since 2026-09-12 `package.py` leaves out
the `!` and `?` rows and every row a mechanical detector calls not-a-gloss: the
bare etymon (`pietas` -> "pius", 334 rows), the headword echoed back (52), an
editorial note used as a definition ("false reading in Vitruvius", 8), a
truncation fragment (23) and a part-of-speech description (16). Where the
excluded gloss was a lemma's primary sense the whole lemma is left out -- 924 of
them -- rather than let a minor homograph move up (`pietas` would otherwise have
read "Roman surname, a ship"); the app's own Whitaker data supplies those words.
`--keep-flagged` restores the old behaviour. Detectors that flag a gloss as
merely imperfect (a diacritic left in, the headword in front of a real gloss, an
adverb given its verb's sense) do not exclude it.

## No hand-edited data

Every gloss in the output comes from a model call under a published prompt, or
from a rule applied uniformly to the whole corpus. Nothing is typed in by hand.

An earlier version of this repo carried an `overrides.tsv` of seven hand-written
glosses for function words that the model was describing by word class
("preposition with ablative" for *ab*). It has been removed. Hand fixes do not
scale: they correct only the rows someone happened to inspect, they cannot be
reproduced by re-running the pipeline, and they let the released data drift away
from the code that supposedly produced it. Worse, they hide the fact that the
underlying class is still broken everywhere else.

The replacement is a rule in the prompt -- state the meaning, never the word
class -- plus a `word-class` detector in `suspect.py` that routes any survivor to
the re-gloss pass. That fixes the whole class rather than the seven instances
somebody noticed, and a fresh clone reproduces it.

The same principle applies to prompts: an example inside a prompt must not hand
the model the answer for a specific headword. `gloss-hard.txt` originally read
`"from, away from", not "preposition with ablative"`, which is the answer for
*ab* written into the instructions. It now states the rule in general terms.

## The output: an importable dictionary package

`package.py` builds a Classics Viewer importable ZIP (see
DICTIONARY_IMPORT_FORMAT.md):

```
lewis-short-glosses.zip
├── dictionary.csv           49,711 lemmas
├── morphology.csv        2,864,259 inflected forms
└── normalization_rules.csv       8 folding rules
```

```bash
python3 package.py --xml <ls-xml> --tsv out/ls_glosses.tsv \
    --scores out/scores_full.tsv --lemma-map out/lemma_map.tsv \
    --treebank data-sources/treebank_data/v2.0/Latin --freq <freq.tsv>
```

### `morph_info` describes the word, in the schema the app already uses

The format documents `morph_info` as the parse -- its own example row is
`est,sum,latin,3 s pres active ind,1.0,Lewis & Short` -- and it is what the app
shows a reader who taps a word. Every one of the 1,543,203 rows used to fill it
with the pipeline stage that produced the row instead: `generated paradigm`,
`paradigm + -que`, `treebank`, `headword`, `model lemma`. That is provenance,
and the format already has a column for it (`source_name`).

**An enclitic row says so.** A token like `ductoresque` gets two rows, one for
the host and one for the particle, and the format has no field that tells them
apart -- a consumer had to guess from the lemma's spelling. The particle's row
now reads `conj enclitic`; the host's row is the host's own parse, unchanged.
`enclitic` is the one value in the schema that Whitaker's rows never carry.

**The schema is Whitaker's**, because the shipped database already holds
1,955,715 Whitaker Latin rows in the same `lemma_map` table ours import into. A
reader tapping `regis` gets both in one candidate list, so two renderings of one
fact would be the same defect this column already had, one level up. Their 32
tokens are what a reader of this app has learned to read:

```
nominal      case number gender             acc s f
verbal    person number tense voice mood    3 p perf active ind
participle   case number gender tense voice mood
                                            gen p pres active part
```

`inflect.render_morph` is the only thing that builds a value and it rejects
anything outside a slot's vocabulary, so a typo in a paradigm table fails the
build instead of shipping as plausible morphology on a million rows.

Matching it is not deference to the incumbent -- their ambiguity model is better
than the one this first shipped with. A form is often several things at once,
and the schema enumerates them in full, joined by `|`:

| form | first attempt | now | Whitaker |
|---|---|---|---|
| `portae` | `noun s/p f gen/dat/nom/voc` | `dat s f\|gen s f\|nom p f\|voc p f` | `dat s c\|gen s c\|…` |
| `amare` | `verb pres active inf` | `0 pres active inf\|2 s pres passive imp\|2 s pres passive ind` | identical |
| `est` | `verb 3 s pres act ind` | `3 s pres active ind` | identical |

The collapsed form was not merely differently worded, it was wrong: `s/p
gen/dat/nom/voc` also admits `nom s` and `gen p`, which `-ae` never is. Ours
carries a real gender where Whitaker has `c`, which is the only difference a
reader should ever see.

There are no `gerund` or `supine` tokens because the schema has none: the
gerundive is a future passive participle (`amandi` -> `gen s m fut passive
part|…`) and the supine a perfect passive one (`amatum` -> `acc s m perf passive
part|…`). Both match Whitaker's rows exactly.

**Three sources fill the slots**, and they merge rather than compete:

- **Treebank postags.** Perseus annotates every token positionally --
  `<word form="fatur" lemma="for1" postag="v3spip---"/>` is third singular
  present indicative passive. `package.py` read `form` and `lemma` off that
  element and dropped `postag`.
- **Generated paradigms.** `inflect.py`'s ending tables were always the
  morphology, but `forms_for()` returned a bare `set()`, so which ending
  produced which form was discarded at the end of the function.
- **The L&S headword line.** `porta, ae, f.` is a feminine noun, `pertinenter,
  adv.` an adverb. This is what fills the forms the paradigm tables cannot
  build: third-declension nominatives like `rex`, which the table never
  generates because it builds from the oblique stem, and the indeclinables.

Confidence ranks the *lemma*; it does not choose between readings. A treebank tag
records what `portis` was in the passages Perseus annotated (ablative), and
because it outranks the generated paradigm it used to replace the full
`abl p f|dat p f` -- telling a reader whose sentence has the dative that the form
is ablative. The readings now union.

**The part of speech appears only where Whitaker has nothing.** A noun row says
`acc s f`, never `noun`. But Whitaker indexes no indeclinables at all -- `ab`,
`et`, `non`, `sed`, `cum`, `in`, `ad` have no row in the shipped database, and
they are among the commonest words in Latin. Those are ours alone, so `prep`,
`conj`, `adv` and `interj` extend the vocabulary exactly where nothing can
disagree, in the trailing position Whitaker puts `pron`. Our token vocabulary is
theirs plus those four.

Reading the part of speech out of L&S has three traps. `v.` opens a verb entry
(`v. a.`, `v. dep. n.`) and is also the abbreviation for *see* (`concitus, a, um,
v. concieo`), which points at a verb without being one; only a following subtype
abbreviation counts. L&S interrupts the headword line with parentheses long
enough to push the marker out of any fixed window (`operio, ui, ertum, 4 (archaic
fut. operibo: … ), v. a.`), so parentheticals are dropped before the search. And
an adjective is often cited by its three nominatives rather than an abbreviation
(`phreniticus, a, um`), which is consulted only after the explicit markers, since
`interdictus, a, um, Part.` is a participle whose `a, um` comes first.

**Enclitics carry the host's reading unchanged.** `-que` is a separate word that
happens to be written joined, so `portisque` carries `abl p f|dat p f` for *porta*
exactly as `portis` does, plus a second row putting `que` itself at `conj`. There
is no slot for "has an enclitic".

### Measured against held-out treebank tags

`make morphacc` builds the package **without** `--treebank`, so every reading in
it came from the paradigm tables or the L&S headword line, then scores it against
the Perseus annotations that were left out. 47,949 annotated tokens:

| | share of the 31,820 tokens we answer |
|---|---|
| exact -- we state the gold reading | 88.8% (28,240) |
| compatible -- nothing we state contradicts it, but we say less | 8.2% (2,614) |
| **contradicted** -- every reading we offer disagrees | **3.0% (966)** |

Of the 47,949 annotated tokens, the rest are ones we do not answer: 9,132 forms
not indexed, 5,525 lemmas not offered for a form we do index, 1,472 rows with no
reading.

Only the last is an error. "nom s" against a gold "nom s m" is not wrong, it is
silence about gender, and the schema omits a slot it cannot fill.

The first run of this scored **74.3% exact and 11.5% contradicted**, and the
column had been shipping that quality all along -- invisibly, because every cell
read `generated paradigm`. Attaching a claim to each form is what made the
paradigm tables checkable, and they turned out to be wrong in five ways:

- **One verb table for four conjugations.** `moneo` produced `monees`, `moneet`,
  `monei`; the third conjugation's present `-it` was labelled a perfect, so
  `dicit` was "3 s perf active ind". Endings are now grouped by the stem they
  attach to, and the stems are read off the principal parts L&S prints. `moneo`
  and `dicit` are both correct now (`dicit` is `3 s pres active ind`), and a
  perfect stem the entry does not print generates no perfect forms rather than
  inventing them from the present. What it does **not** yet do is expand the
  principal parts L&S abbreviates: the entry reads `dīco, xi, ctum`, and the
  fragment is appended to the present stem, which gives the right `dictum` and the
  wrong `dicxi` for *dixi*. See finding 13 in REVIEW.md.
- **Verb entries were also declined.** "moneo, ui" and "dico, dixi" look like a
  headword and a genitive, which produced `moneous`, `moneoorum`, `dixorum`.
- **Gendered citations were read as genitives.** "qui, quae, quod" was declined
  as a first-declension noun with the stem `qu-`, making `quae` a dative
  singular of the relative pronoun. A gender abbreviation ends in a period and a
  third nominative does not, which separates "rex, regis, m." from "bonus, a,
  um".
- **Neuters used the masculine paradigm.** `bellum` got `belle` and `beller`,
  and its `belli` claimed to be a nominative plural. Neuter nominative,
  accusative and vocative are one form and the plural is `-a`; the second and
  third declensions now have neuter tables, selected by the entry's own gender.
- **One part of speech per entry.** "inter, adv., and prep. with acc." is both,
  and keeping the first marker denied the rest -- ~800 tokens of `inter`, `pro`,
  `ne`, `ubi`, `etiam`. Every marker in the headword line is kept.

One claim was dropped for being a guess. Where L&S prints no genitive to decline
by, the headword line does not say what case or number the form is, only what
gender the word is -- asserting the nominative singular there was 240 tokens
wrong, mostly plurals and ablatives, so those rows now state the gender alone.

The locative went the other way. It is generated **only where L&S capitalises
the headword**, which is what the source gives us to recognise a place name:
`Roma, ae, f.` yields `romae -> dat s f|gen s f|loc s f|nom p f|voc p f`, while
`porta` gets none. It is added as one more reading of a form the paradigm already
generates, so it cannot invent a word. 9,178 rows across 3,065 lemmas carry one.

12,645 rows (0.43%) ship with an empty `morph_info` -- entries that name no part
of speech and build no paradigm, nearly all cross-reference stubs like
`Naevianus, v. 2. Naevius, B.` whose own text says nothing about the word. Empty
is what the format expects for unknown, and it is the honest answer: the first
version of this column filled those rows with `lemma form`, which is not
morphology and hid the gap rather than reporting it.

Match the format, not the data. Whitaker's has `iam -> e, 1 s fut active ind`
(the adverb *iam* parsed as a form of *eo*), `est -> ed` ranked beside *sum*, and
three near-duplicate `oris -> or` rows; its lemmas are stems (`port`, `reg`,
`qu`), which DICTIONARY_IMPORT_FORMAT.md explicitly warns against. Ours are
headwords that join to `dictionary.csv`.

`forms_for()` still returns a set and every form-only caller is unchanged, and
provenance is now printed to stderr at the end of `make package`, where a fact
about the build belongs.

While the change was format-only, every column of `morphology.csv` except
`morph_info` stayed byte-identical to the previous package and all eight
regression probes were unchanged. That is no longer the state: the paradigm fixes
that followed (see REVIEW.md) changed which rows exist — 1,543,203 forms became
2,956,405 — and three probes (`stem`, `forms`, `lemmafreq`) now differ from the
committed baseline on purpose, and stayed so until 2026-09-12, when the diff was
reviewed and accepted (`baseline/changelog/15-*.txt`). `make check` is green.

### Coverage is the reader's real problem, not gloss quality

Matching surface forms against headwords covers less than half a Latin text,
because the language is inflected: `amavit` is not `amo`. Measured over the
6,873,450 corpus tokens in `out/latin_freq.tsv`, headword spelling alone matches
**44.8%**; the shipped package matches **89.1%** (2026-09-12 build; 88.0% before
the paradigm fixes). Gloss defects, by comparison,
affect about 1% of tokens. Four mechanisms close the gap:

| mechanism | source |
|---|---|
| paradigms generated from each entry's own morphology | `inflect.py` |
| gold form/lemma pairs | Perseus treebanks |
| model-supplied lemmas for irregular forms the paradigms miss | `lemmatize.py` |
| enclitic splitting (`-que`, `-ve`) and i/j, u/v folding | `inflect.py` |

The lemmatiser accepts a model answer only when it is a headword and either
shares its stem with the form or is cited on the entry's own headword line; that
is 78 forms in the shipped map. The suppletives -- `est`, `sunt`, `mihi`, `haec`,
`id`, `quae` -- are NOT among them: for those the model answered with another
form (`esse`) or echoed the form back, and no rule safely turns that into a
lemma. In the full build the Perseus treebanks supply them at confidence 0.99.

### Accuracy against gold data

**This table and the next one predate the morphology rebuild and have not been
re-measured.** What has been measured on the two ZIPs directly: whole-corpus
coverage went from **80.944% to 88.032%** of the 6,873,450 tokens in
`out/latin_freq.tsv` (and to **89.1%** with the 2026-09-12 paradigm fixes, whose
held-out figures are in *Revision 2026-09-12*), and the rebuild also changed which lemma many forms rank
under, which is the quantity both `coverage` and `exact` below depend on. Treat
the numbers as the earlier build's.

Leave-one-out cross-validation over the Perseus Latin treebanks: each work is
held out in turn and the package rebuilt without it, so no work is ever scored
against its own annotations. 53,143 tokens.

| held-out work | tokens | coverage | exact | reader-useful |
|---|---|---|---|---|
| Catullus | 1,488 | 77.7% | 85.4% | 90.6% |
| Cicero | 6,229 | 75.1% | 83.9% | 89.1% |
| Propertius | 4,857 | 73.7% | 82.8% | 87.8% |
| Ovid | 12,311 | 72.8% | 84.9% | 90.6% |
| Vergil | 2,613 | 72.5% | 85.2% | 91.3% |
| Sallust | 4,789 | 74.2% | 85.4% | 91.4% |
| Petronius | 12,474 | 72.8% | 83.4% | 88.5% |
| Jerome | 8,382 | 87.7% | 90.3% | 94.4% |
| **pooled** | **53,143** | **75.8%** | **85.3%** | **90.5%** |

"reader-useful" counts an exact lemma match or a morphologically related one --
a participle pointing at its own L&S entry rather than the verb the treebank
lemmatises to. It is a floor, not a ceiling: rows counted outright wrong often
still convey the right sense (`di` glossed "god, a deity" where the gold lemma
is *deus*).

### Coverage on the works this is actually for

The treebanked works are a test set, not the target. Measured over the 387
Perseus Latin works with **no** treebank, 7.27M tokens — a count that predates the
current frequency build, which excludes `<note>` and `<bibl>` text and totals
6,873,450 tokens across 428 Latin editions:

| | |
|---|---|
| pooled coverage | **78.7%** |
| median per-work | 80.8% |
| range | 62.3% (Pliny, technical vocabulary) to 92.3% |

### Collisions are resolved by corpus frequency

When two lemmas claim one form, the rarer loses: `cui` belongs to *qui*, not to
*Spaco* (a nurse of Cyrus) whose paradigm also generates it. Confidence is scaled
by how often each lemma's headword occurs in real Latin. Without this, obscure
words capture forms belonging to the commonest words in the language.

Confidence, before the frequency scaling that every value is multiplied by:
headword 1.0 > treebank 0.90–0.99 (ranked by how often the treebanks chose that
lemma for the form) > generated paradigm 0.85, or 0.35 for a form shorter than
five characters, which is only trusted when it *is* the headword > paradigm +
enclitic 0.75 > model-guessed lemma 0.5 > the enclitic's own lemma (`que`, `ve`)
0.30.

## Fixing the words readers actually meet

`freqfix.py` repairs entries in corpus-frequency order rather than entry order.

```bash
python3 freqfix.py --xml <ls.xml> --freq <corpus-freq.tsv> \
    --screen --min-score 3 --top 1200 [--dry-run]
```

Four stages, each answering a failure the previous design had:

1. **Rank by corpus frequency.** A defect on *sum* costs 86,000 reader
   encounters; one on *ferricrepinus* costs none.
2. **Screen the current gloss live** with the judge. Reading scores from a file
   goes stale the moment a gloss changes -- a stale file reported *ab* as fine
   while its gloss had already been replaced by a wrong one.
3. **Re-gloss with a sliding window.** The commonest words have the longest
   articles, and L&S opens them with pages of philology: *ab* runs 30,005
   characters and does not reach "from, away from" until offset 3,379 of its
   focused text. A fixed window from the start shows the model nothing but
   Indo-European cognates.
4. **Verify against the same window the candidate came from.** This one is easy
   to get wrong and silently disables the whole stage: judging every candidate
   against the first 800 characters means a long entry has no definition in
   view, so no candidate can ever beat an incumbent however wrong it is.

A replacement is kept only if it clears the mechanical detectors *and* outscores
the gloss it replaces. On a run over the 1,200 most frequent entries: 25
repaired, 32 rejected as no better, 161 left alone. The shipped TSV carries 339
`freqfix` rows in total.

REVIEW.md leaves the stage **off** for now, and *ab* is why: its gloss reads
"departure from a fixed point", which `freqfix` itself put there. The accept test
compared both candidates against the window the challenger came from, and fixing
that exposed a second bias, toward whichever sense sits deepest in the article.
("around, near, beside, among" is a different row — `a2`, inherited through a
cross-reference — not *ab*.)

### Ambiguous forms keep every candidate

`oris` is a real form of *os* ("mouth") and of *ora* ("shore"), and which one is
meant depends on the sentence. A static package cannot know, and picking one
silently is the wrong response: in *ab oris* the answer is *ora*, in another line
it is *os*.

The format is built for this -- several rows may share a `word_form`, and
`confidence` ranks them -- so all candidates are emitted, best first, capped at
three:

```
oris,ora,latin,abl p f|dat p f,0.95,...
oris,os,latin,gen s n,0.92,...
oris,aurum,latin,abl p n,0.92,...
```

1,174,080 of the 1,726,493 indexed forms (68.0%) carry more than one candidate.
Most of that is enclitics: a form written with `-que` or `-ve` is two words, so
1,147,925 of those rows are a host plus `que`/`ve`. Excluding them, 26,155 of
578,025 plain forms (4.5%) are genuinely ambiguous between lemmas. Keeping only
the winner threw away information the app is designed to use, and made a genuine
ambiguity look like a wrong answer.

### Choosing which homograph a reader sees

L&S has four `sero` entries and three `litus`. The package can expose one as the
bare lemma, so the choice decides what appears under the word in the interlinear.
Two plausible signals fail:

- **Homograph number.** `litus1` is a participle ("Part., from lino"); `litus3`
  is "sea-shore", the word in every line of epic. The numbering does not track
  usage.
- **Gloss score.** It measures whether the gloss fits its entry, not whether
  that entry is the sense anyone reads.

What works is **article length**: L&S gives its most-used senses the longest
treatment. Ordering by (not-a-cross-reference, longest article, gloss score) puts
"sea-shore" first, as the bare lemma `litus`, and renumbers the other two behind
it — `litus2` "lino, a smearing, besmearing" and `litus3` "to daub, besmear,
anoint", both still present for the dictionary panel.

## Code layout

`common.py` holds what every stage needs: entry text extraction (`txt`,
`focus`), the three normalisers, one HTTP call to the model (`chat`), the
loaders, the judge-reply parser (`parse_score`), the cross-reference resolver
(`XrefIndex`, `xref_target_word`), the headword-line part-of-speech marker
(`pos_marker`) and the checkpoint runner (`checkpointed`, `load_ckpt`).
Everything else is a stage that imports it. `eval/treebank.py` holds the
treebank reader and the one definition of a reading being *compatible* with a
gold tag, shared by `eval/morphacc.py`, `tools/quality.py` and `tools/diffck.py`.

`checkpointed` writes a record only for a call that succeeded. Every stage used
to write its failures too -- an `ERROR: ...` gloss, an empty string, a `null`
score -- and then skip them on resume as if they were answered, so a server
restart mid-run left permanent holes. A failed call is now retried on the next
run. The judge and shorten/adapt checkpoints also record the gloss they were
given, so a row repaired since is judged again rather than served its
predecessor's verdict.

The three normalisers are deliberately distinct, and confusing them is the
easiest way to break this project quietly:

| | folds accents | folds i/j, u/v | used for |
|---|---|---|---|
| `fold` | yes | **yes** | `word_form` — matching a form in a text |
| `plain` | yes | no | `lemma` — the join key between the two CSVs |
| `letters` | yes | no | comparing English gloss text to entry text |

`fold` is for Latin forms, where `virum` and `uirum` are the same word. `plain`
must *not* fold, because a lemma has to stay the headword a reader looks up
(`juvo`, not `iuuo`) and is matched as an exact string across the two files.

### What consolidating them turned up

These helpers had been copy-pasted into eight scripts, drifting into six
near-identical variants. Collecting them found four real bugs:

- **`diānœa` folded to `diana`.** NFKD does not decompose the `æ`/`œ`
  ligatures, so the letters-only strip deleted them outright — turning an
  obscure medical term into the goddess **Diana**, and ranking it *above* her
  (0.81 vs 0.72) for the form `diana`. A reader meeting Diana in a text got the
  wrong word. `common` spells the ligatures out before stripping.
- **Coverage was understated.** `freqqa.py` matched corpus forms to headwords
  with a non-folding key, so every `v`- and `j`- word failed to match once the
  frequency list itself was folded.
- **A crash on empty model output.** `refine.py` and `score.py` read
  `message["content"]` directly, which raises `KeyError` in exactly the case
  this project hits — a model returning no content under
  `--reasoning-budget 0`. `chat` treats empty output as a value, which is what
  the callers already screened for.
- **A quadratic regex** in the frequency builder (see below).
- **Y-breve folded to nothing** (found 2026-09-12). Perseus writes `ў` with the
  Cyrillic short u (U+045E), which NFKD decomposes to a Cyrillic letter that
  the a-z strip then deletes: `Cărўae` was indexed as `carae` and
  `Bacchўlĭdēs` as `bacchlides`, on 1,180 lines of the dictionary. `common`
  maps it to `y` with the ligatures.

The nine hand-rolled `urllib` calls in the pipeline are now one function, so a
timeout or retry change happens in one place instead of nine. `eval/run_eval.py`
still builds its own request.

## Reproducibility

Anyone cloning this repo can rebuild the published package without running a
model at all, because the four files `make package` reads are committed:
`out/ls_glosses.tsv`, `out/scores_full.tsv`, `out/lemma_map.tsv` and
`out/latin_freq.tsv`. Everything else under `out/` is ignored. The model passes
that *produce* those files are still fully documented (§6) for anyone who wants
to regenerate them from scratch — but reproducing the ZIP is a 30-second job,
not a two-day one.

This was verified rather than assumed. The repo's committed file list was
extracted to an empty directory, given nothing but the two Perseus checkouts,
and built:

```
$ make package
dictionary.csv          49,711 lemmas
morphology.csv        2,864,259 forms
-> out/lewis-short-glosses.zip
```

`dictionary.csv` and `morphology.csv` came out **byte-identical (sha256) to the
development build**. Re-checked after the morphology rebuild: two fresh builds in
the same tree match each other *and* match the published ZIP, member by member by
sha256. Ties in candidate ranking are broken stably, so two people building the
same checkout get the same package. One build takes about 30 seconds.

**Nothing committed is near GitHub's file-size limits.** The whole committable
tree is 16 MB across 96 files; the large things this project touches — the 13.8 GB
converted model, the ~1.5 GB corpus checkout, `llama.cpp`, the venv — are ignored
by directory *and* by extension, so they stay out even if unpacked somewhere
unexpected. `make check-size` fails on anything over 50 MB (GitHub warns at 50
and hard-rejects at 100), and it is tested to actually fail rather than merely
report.

### The frequency list is rebuilt, not shipped from a scratch file

For most of this project's life the frequency list was a file in `/tmp` with no
generator in the repo — the single worst reproducibility hole here, since it
decides which sense a reader sees. `corpusfreq.py` now builds it from the Perseus
corpus in about 9 seconds (428 Latin editions, 6,873,450 tokens, 277,295 distinct
forms), and the result is byte-identical to the committed `out/latin_freq.tsv`.

Rebuilding it does not reproduce the old `/tmp` file exactly, and the new one is
better on both counts that differ:

- The old list never folded `v`→`u`, so `vel`, `vero` and `vis` were counted
  separately from their folded forms. That is the same class of bug that made
  `vir` score a frequency of 0 before `lemmafreq.py` (see *Collisions*).
- The old list counted `<note>` and `<bibl>` contents, which is why editorial
  abbreviations like `diosc` and `rv` ranked among the top 300 Latin words.

Top-50 overlap between old and new is 48/50 and the median rank shift across the
top 200 is 1.5, so published figures computed against the old list stand.

One known wart: praenomen initials and numerals (`m`, `p`, `c`, `l`, `q`) survive
as single-letter "words", 1.1% of tokens. They are not filtered, because `a`,
`e` and `o` are genuine Latin words and a length rule would take those too.

A note on why `corpusfreq.py` uses one regex per element rather than the obvious
`<(note|bibl|...)\b.*?</\1>`: the backreference stops Python anchoring the
search, making it quadratic. That single pattern took over two minutes on the
corpus's largest file — the 13 MB Pliny, *Naturalis Historia* — and had not
finished the corpus after 17 minutes; per-tag patterns do the same file in 0.07s.

## Known limitations

**Sense selection on long articles is the model's.** `moneo` ships as "punish,
chastise", a late and rare sense; the primary one is *remind, advise, warn*. The
row came from an early `freqfix` run whose judge rated each candidate at
whichever window of the article supported it best, which rewards whatever sense
sits deepest (REVIEW.md, finding 7). The stage is off, its 339 rows are kept
because most are judge-verified improvements, and no rule can tell this one
apart without a model. A re-run that judges every candidate against the
article's opening is the fix, and needs model time.

**A name's gloss says what kind of name, not whose.** `Marcellus` reads "Roman
family name" because that is what the prompt asks for and what L&S itself often
says. The six phrasings L&S produced (`Roman nomen`, `Roman gens name`, `name of
a Roman gens`, `Roman cognomen`, ...) are now rendered as two English ones
(`Roman family name`, `Roman surname`), but saying *which* family needs a
different prompt and a model run.

**Rows a detector rejects leave their lemma to the app.** 924 lemmas whose only
gloss was a bare etymon, an echo or a fragment are not in `dictionary.csv`, and
their generated forms are not in `morphology.csv` either, since a form must
join to a lemma the package defines. Whitaker's data covers the common ones;
`--keep-flagged` ships them all.

**OCR artefacts are not corrected.** The Perseus text is a digitisation of the
1879 print and its scan errors stand in the entries we gloss from: `ăbactor`'s
entry reads "a cuttle-stealer" where the print has *cattle*. The pipeline does not
attempt to repair source text — guessing at what a garbled word "should" say is
precisely the fabrication this project works to avoid, and a corrected gloss would
score *worse* on the grounding check than the faithful one. Whether an error
reaches the output depends on whether the gloss draws on the damaged phrase;
`ăbactor` itself came out "driver off", from the entry's primary sense. Report
such errors upstream to PerseusDL/lexica.

**Grounding catches invention, not misreading.** A gloss that faithfully copies
the *wrong* sense from an entry scores 1.0 and passes unflagged. The check only
detects words that appear nowhere in the entry.

**The `<tr>` shortcut trusts the source**, which is why it is off. With
`--use-tr`, a `<tr>` tag of 1–5 words is used verbatim and unexamined, so a tag
belonging to some buried sense propagates. No shipped row uses it.

**Compound and abbreviated verb paradigms are wrong in a known way.** L&S prints a
compound's principal parts without the prefix (`ex-cēdo, cessi, cessum`) and a
simple verb's with the stem elided (`scrībo, psi, ptum`), and neither is expanded:
407 entries generate the simple verb's forms instead of their own, and forms like
`scribpsi` ship while `scripsi` is offered only under *discribo*. The perfect and
supine of every affected verb are missing. Finding 13 in REVIEW.md has the
measurements.

**966 readings contradict the treebank** (3.0% of the held-out tokens we answer).
400 of those are `adv` against `conj` on indeclinables, which L&S cannot settle: it
marks `etiam` as `conj.` only and `quam` as `adv.` only, and both words are
genuinely both.

## Evaluation

```bash
make eval                                     # 25 hand-checked entries
python3 eval/run_eval.py --xml <xml> -n 30 --offset 37   # held-out sample
```

The gold set lives in `eval/gold.tsv`. Current prompt scores **96%**; it was
validated on held-out entries the prompt was never tuned against, since the
gold set is small enough to overfit.

```bash
make qa           # coverage, length histogram, flagged issues, random sample
```

## Prompts

`prompts/gloss-system.txt` is the main instruction; `prompts/gloss-repair.txt`
is used only for entries the model declines. Every run records the full prompt
text and a `prompt_id` hash in `out/manifest.json`, and `lsgloss.py` stamps that
id into the TSV header.

The stamp does **not** survive to the shipped file: `freqfix.py` and `xrefix.py`
rewrite the TSV with only a `# columns` line, so `out/ls_glosses.tsv` carries no
`prompt_id`. The manifest is the only record — `3c1df5124d7a` for the published
run.

Notes from tuning, in case you change them:

- Fixed word counts ("exactly two words") cause **silent empty outputs** on
  entries whose gloss is one word, and force spurious commas that turn
  `stamping of money` into `stamping, money`.
- L&S puts the etymology immediately after the part of speech; without an
  explicit instruction to ignore it the model glosses *that* instead
  (`Nĕpōtīnus` → "nephew", not "Roman surname").
- An example naming a nationality biases every name toward it. `Thāis` came
  back "Roman name" until the example was made neutral.

## Licence

Code in this repository: **MIT** (see [LICENSE](LICENSE)).

The generated glosses are a different matter. They are derived from the Perseus
text of Lewis & Short, which is **CC BY-SA 4.0** — a copyleft licence. If you
distribute the output TSV you must credit Lewis, Short and the Perseus Digital
Library, state that changes were made, and release it under CC BY-SA 4.0.
See [LICENSE](LICENSE) for the full attribution text. MIT covers the code only.

Model weights (`gpt-oss-20b`) are Apache 2.0; llama.cpp is MIT. Neither is
redistributed here — both are fetched by the setup steps above.
