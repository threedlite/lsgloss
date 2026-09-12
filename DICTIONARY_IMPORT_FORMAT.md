# Classics Viewer — importable dictionary package format

A user-importable dictionary is a **ZIP file** containing up to three CSVs at
the archive root. The app reads it on-device; nothing is uploaded and no network
call is made.

This document describes what the importer actually accepts. It is written from
`app/src/main/java/com/classicsviewer/app/utils/DictionaryZipParser.kt`, which is
the authority — if this document and that file disagree, the file wins.

---

## 1. Archive layout

```
my-dictionary.zip
├── dictionary.csv           optional — the definitions
├── morphology.csv           REQUIRED — inflected form → lemma
└── normalization_rules.csv  optional — accent/diacritic folding rules
```

Files must sit at the **root** of the archive, not inside a folder. Names are
matched exactly and are case-sensitive.

`morphology.csv` is the only required member. A package with morphology but no
`dictionary.csv` is valid and useful — it teaches the app that `est` is a form of
`sum` without supplying a definition. A package with definitions but no
morphology cannot be imported.

**Inflected forms must be enumerated, not derived.** There is no paradigm or
expansion mechanism anywhere in the format — `normalization_rules.csv` folds
characters for matching, it does not generate forms (§4). So every inflected
form needs its own row. For Latin that is roughly 1.9 million rows, because the
forms are produced by applying ~1,600 paradigm patterns to ~39,000 headwords;
the package carries the output of that expansion, not the patterns.

This is the expensive half of producing a package, and it is a different problem
from writing good glosses. A package supplying `dictionary.csv` only, and
leaving morphology to the existing build, is a perfectly reasonable division of
labour.

---

## 2. `morphology.csv` — required

Maps an inflected form as it appears in a text to its dictionary headword.

| column | required | notes |
|---|---|---|
| `word_form` | **yes** | the inflected form as it appears in running text |
| `lemma` | **yes** | the dictionary headword it belongs to |
| `language` | **yes** | lower-cased; `latin`, `greek`, … (see §5). Required even in a single-language package — it is what keeps one language's forms out of another's lookups |
| `morph_info` | no | free text, e.g. `3 s pres active ind` |
| `confidence` | no | 0.0–1.0, default **1.0**; higher sorts first |
| `source_name` | no | attribution label; displayed as `User: <source_name>` |

```csv
word_form,lemma,language,morph_info,confidence,source_name
est,sum,latin,3 s pres active ind,1.0,Lewis & Short
sunt,sum,latin,3 p pres active ind,1.0,Lewis & Short
esse,sum,latin,pres active inf,1.0,Lewis & Short
```

Column order does not matter; the header is read by name and lower-cased before
matching. The morphology column is accepted under **either** name —
`morph_info` or `morphology_info` — but prefer `morph_info`, which is the
documented one.

Rows whose `word_form`, `lemma` or `language` is empty are skipped and counted;
they do not abort the import.

---

## 3. `dictionary.csv` — optional

| column | required | notes |
|---|---|---|
| `lemma` | **yes** | must match `morphology.csv`'s `lemma` exactly |
| `language` | **yes** | lower-cased |
| `definition` | **yes** | plain text; this is what the reader sees |
| `html_definition` | no | rich version, used in the dictionary panel if present |
| `source_name` | no | attribution label; defaults to `User Import`. Displayed as `User: <source_name>` |

```csv
lemma,language,definition,source_name
sum,latin,"to be, exist",Lewis & Short
```

**The join is on the exact `lemma` string.** A form whose lemma has no matching
`dictionary.csv` row still imports and still resolves — the app records it as a
morphology-only mapping and shows the lemma without a definition.

---

## 4. `normalization_rules.csv` — optional

Regex rules for folding accents and diacritics so a user's typed query matches
stored forms. **Positional, not by name** — the header row is skipped and
columns are read by index:

```
0: language      required
1: pattern       required, Java regex
2: replacement   required (may be empty, to delete)
3: description   optional, free text
4: priority      optional integer, lower runs first; defaults to 999 if
                 missing or unparseable
```

Columns 0–2 are read unconditionally, so every row needs at least three fields.
Columns 3–4 are read with a bounds check and may be absent.

```csv
language,pattern,replacement,description,priority
latin,[āăá],a,fold long/short a,10
latin,[ēĕé],e,fold long/short e,10
```

Patterns are compiled with Java regex. An invalid pattern is skipped with a
warning rather than failing the import. `\uXXXX` escapes are unescaped before
compilation, so both literal characters and escapes work.

Greek does not need this — the app normalises Greek internally. For any other
language, without these rules an accented lemma has no normalised form and will
only match on an exact string.

---

## 5. Field rules

- **Encoding: UTF-8.** No BOM.
- **Quoting: standard CSV** (RFC 4180). Fields containing commas, quotes or
  newlines must be double-quoted; embedded quotes are doubled.
- **`language` is lower-cased** on read. Use `latin`, `greek`, `sanskrit`,
  `hebrew`, `arabic`, `persian`, `coptic`, `syriac`, `pali`, `norse`,
  `old_english`, `chinese`, `italian`, `akkadian`, `sumerian`.
- **Maximum field length is 50,000 characters.** Longer fields are silently
  truncated, not rejected.
- Header row is required in all three files.
- **The three files and the columns listed above are the entire format.** It is
  fixed by the released app and will not be extended for a package. Do not rely
  on additional columns, additional files, or renamed columns.
- A malformed individual row is logged and skipped; the import continues. Only a
  missing required *column*, a missing `morphology.csv`, or a corrupt archive
  aborts it.

---

## 6. What makes a good package

**Size — measured.** A complete Latin package exported from the shipped build:

| | rows | raw | 
|---|---|---|
| `dictionary.csv` | 135,792 | 182 MB |
| `morphology.csv` | 1,899,457 | 131 MB |
| **zipped package** | | **31.8 MB** |

`morphology.csv` is streamed in batches rather than read whole, so size is not
a memory problem however large it gets. Note the split: the definitions are the *small*
half by row count. A package supplying glosses only is roughly 5% of the work.

**Lemma consistency is the thing that matters most.** The `lemma` column in
`morphology.csv` and the `lemma` column in `dictionary.csv` are joined as exact
strings. If morphology says `sum` and the dictionary says `sŭm`, nothing joins.
Pick one spelling convention and use it in both files.

**Prefer dictionary headwords over stems.** A lemma should be the form a reader
would look up — `sumo`, `multus`, `qui` — not a truncated stem like `sum`,
`mult`, `qu`. Stems collide across unrelated words and produce wrong matches.

**Short definitions read best.** The interlinear display shows the definition
under each word, so 1–5 words is ideal. Long scholarly prose is better placed in
`html_definition`, which is shown only in the full dictionary panel.

**`confidence` breaks ties.** When several lemmas claim the same form, higher
confidence sorts first. Use it to express real uncertainty; leave it out if
every row is equally certain.

---

## 7. The format is lossless — verified

The whole Latin dictionary layer of the shipped build was exported to this
format and loaded back through a parser matching the app's semantics:

| | source | round-tripped | |
|---|---|---|---|
| `dictionary_entries` | 135,792 | 135,792 | identical (sha256) |
| `lemma_map` | 1,899,457 | 1,899,457 | identical (sha256) |
| glosses, top 1,000 surfaces | 2,162,716 tokens | | **0 differences** |

Every token produced an identical gloss through the real lookup code. So a
package is a complete substitute for the built-in dictionary ingest, not an
approximation of it — anything the interlinear can do from the built-in sources,
it can do from a package.

A reference package built this way can be supplied on request as a worked
example.

---

## 7a. Checking a package before sending it

These are the checks that catch the failures we have actually seen. All are
runnable against the CSVs alone.

**1. Every morphology lemma resolves.** For each distinct `lemma` in
`morphology.csv`, is there a `dictionary.csv` row with that exact string? A
mismatch here is silent — the import succeeds and the words simply have no
definitions. This is the single most common way a package looks fine and is not.

```
comm -23 <(cut -d, -f2 morphology.csv | sort -u) \
         <(cut -d, -f1 dictionary.csv  | sort -u)
```

**2. Lemmas are dictionary forms, not stems.** Spot-check that the lemma column
holds words a reader would look up (`sumo`, `multus`, `qui`) rather than
truncated stems (`sum`, `mult`, `qu`). Stems collide across unrelated words: a
single stem `mult` covering *multus*, *multa* and *multo* produced the gloss
"much, fine, punish" in our own build for years.

**3. Homographs stay distinct.** 1,493 Lewis & Short headwords collide once
accents are stripped — `sero` alone is four unrelated entries ("to sow",
"linked", "to fasten with a bolt", "ripe years"). If the package keys on the
bare headword, three of those four are silently lost.

The format has no field for a disambiguator, so whatever distinguishes them has
to live in the `lemma` string itself, and `morphology.csv` must point each form
at the right one. Whether that is worth doing depends on how the package will be
used; the important thing is to *count* the collisions before deciding, rather
than discover them afterwards.

**4. Gloss length.** The interlinear renders the definition under each word, so
1–5 words is the target. Plot the distribution; a long tail means entries that
will be truncated on screen.

**5. Weight quality checks by corpus frequency, not by entry count.** This is
the one that matters most and is easiest to miss. Common words have the longest
articles, so any heuristic that picks the wrong part of an entry fails hardest
exactly where it is seen most. In the current `ls_glosses.tsv`, the `tr` source
is 14% of entries but lands on **44% of running-text tokens** — `sum1` as "nor
is she ashamed", `an1` as "Simonides or some other person", `pars` as "west
side", `deus` as "gods forbid". Sampling entries uniformly would have shown 86%
correct and hidden this completely.

A frequency list for weighting can be supplied on request.

**6. Round-trip it.** Load the package into SQLite with the same column
semantics the app uses (§2–§4) and re-read it. We did exactly this with a
package exported from our own build; see §7.

---

## 8. Minimal working example

```
latin-example.zip
├── dictionary.csv
└── morphology.csv
```

`dictionary.csv`
```csv
lemma,language,definition,source_name
sum,latin,"to be, exist",Example Lexicon
multus,latin,"much, many",Example Lexicon
```

`morphology.csv`
```csv
word_form,lemma,language,morph_info,confidence,source_name
est,sum,latin,3 s pres active ind,1.0,Example Lexicon
sunt,sum,latin,3 p pres active ind,1.0,Example Lexicon
multum,multus,latin,acc s n,1.0,Example Lexicon
```

That is a complete, valid package.

---

## 9. How it is used once imported

Imported entries are stored in the user database, separately from the shipped
dictionaries, and survive app upgrades. Each is labelled `User: <source_name>`
in the dictionary panel, so the origin of every gloss stays visible. They are consulted alongside the built-in
sources during word lookup, and imported entries are ranked **above** built-in
ones so a user's own dictionary wins where it has an answer.

An import can be removed later without touching the shipped data.
