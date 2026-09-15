#!/usr/bin/env python3
"""Helpers shared by every stage of the pipeline.

These were copy-pasted into eight scripts before being collected here. That was
not merely untidy: `fold` and `plain` had drifted into six near-identical
variants, and a form normalised one way in one stage will silently fail to match
the same form normalised another way in the next. Keeping one definition of each
is what makes the stages composable.
"""
import json, re, unicodedata, urllib.request

# ---------------------------------------------------------------- entry text

def txt(s):
    """Strip XML tags and collapse whitespace."""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip()


def focus(t):
    """Put the definition first.

    L&S opens a long entry with morphological variants in parentheses and the
    etymology in brackets; for the commonest words that apparatus runs for
    thousands of characters, so a truncated entry contains no definition at all
    ('ago' is 40k characters and does not define itself until char 368).
    Stripping those two constructs makes the definition lead."""
    head = t.split(',')[0]
    body = t
    for _ in range(8):
        n = re.sub(r'\([^()]*\)', ' ', body)
        n = re.sub(r'\[[^\[\]]*\]', ' ', n)
        if n == body:
            break
        body = n
    return re.sub(r'\s+', ' ', head + ': ' + body).strip()


# ------------------------------------------------------------ normalisation

# NFKD leaves the ae/oe ligatures alone, so they must be spelled out before the
# non-letter strip below deletes them outright -- otherwise `quaeso` written
# `quæso` folds to `quso` and matches nothing.
# The Perseus text writes y-with-breve as the CYRILLIC short u (U+045E), which
# NFKD decomposes to a Cyrillic letter that the a-z strip then deletes: `Cărўae`
# folded to `carae` and `Bacchўlĭdēs` to `bacchlides`, so every y-breve word
# was indexed under a misspelling and its own name never echoed as its gloss.
LIGATURES = {'æ': 'ae', 'Æ': 'ae', 'œ': 'oe', 'Œ': 'oe', 'ð': 'd', 'þ': 'th',
             'ў': 'y', 'Ў': 'Y'}


def _strip_accents(s):
    for lig, plainform in LIGATURES.items():
        if lig in s:
            s = s.replace(lig, plainform)
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c))


def fold(s):
    """Match key for an inflected FORM: accents dropped, i/j and u/v merged.

    Classical texts spell the same word `virum` or `uirum` and `iam` or `jam`;
    folding both onto one convention is what lets a form in a text find a form
    in the dictionary. Used for `word_form`, never for `lemma`."""
    return re.sub(r'[^a-z]', '', _strip_accents(s.lower())).replace('j', 'i').replace('v', 'u')


def letters(s):
    """Lower-case letters only, accents dropped, i/j and u/v left alone.

    The comparison key for prose -- gloss text against entry text -- where the
    orthographic folding `fold` applies would be wrong: an English gloss is not
    Latin and must not have its v's turned into u's."""
    return re.sub(r'[^a-z]', '', _strip_accents(s.lower()))


def plain(s):
    """Match key for a LEMMA: accents dropped, spelling otherwise preserved.

    Deliberately does NOT fold i/j or u/v. A lemma is the join key between
    morphology.csv and dictionary.csv and has to stay the headword a reader
    would look up -- `juvo`, not `iuuo`."""
    return re.sub(r'[^A-Za-z\-]', '', _strip_accents(s)).lower()


# ------------------------------------------------------------------ the model

def chat(url, system, user, *, temperature=0, max_tokens=64, effort=None,
         timeout=300):
    """One turn against a llama.cpp OpenAI-compatible endpoint.

    Returns the assistant's text, or '' if the model produced none. Note that
    an empty string is a real answer here rather than an error: with
    `--reasoning-budget 0` some models return content-free replies, and the
    callers screen for that themselves."""
    body = {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature, "max_tokens": max_tokens}
    if effort:
        body["chat_template_kwargs"] = {"reasoning_effort": effort}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    return (r["choices"][0]["message"].get("content") or "").strip()


# ------------------------------------------------------------------- loading

def load_entries(path):
    """The <entryFree> elements of the Lewis & Short XML, in document order.

    Order is the contract between files: out/ls_glosses.tsv is positional, so
    row i describes entry i. Every stage must read the entries the same way."""
    with open(path, encoding='utf-8') as fh:
        return re.findall(r'<entryFree\b.*?</entryFree>', fh.read(), re.S)


def load_rows(path, min_fields=4):
    """The gloss TSV as a list of field lists, comments skipped."""
    with open(path, encoding='utf-8') as fh:
        rows = [l.rstrip('\n').split('\t') for l in fh if not l.startswith('#')]
    return [r for r in rows if len(r) >= min_fields]


# ---------------------------------------------------------------- judging

def parse_score(text):
    """The 0-5 score in a judge's reply, or None.

    The judge prompts ask for the digit first, so it is read from the start of
    the reply. `\\b([0-5])\\b` over the whole reply took the first small number in
    any prose the judge added -- "The gloss has 3 words ..." scored 3."""
    if not text:
        return None
    m = re.match(r'\s*[*("\']*([0-5])(?![\d.])', text)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(?:score|rating|grade)\b\s*(?:is|of|:|=)?\s*\(?([0-5])(?![\d.])', text, re.I)
    if m:
        return int(m.group(1))
    lone = re.findall(r'(?<![\d.])([0-5])(?![\d.])', text)
    return int(lone[0]) if len(lone) == 1 else None


def pos_marker(entry_text):
    """The entry's own part-of-speech abbreviation, or None.

    Read from the headword line only: L&S cites other words' parts of speech
    throughout a long article, so a whole-entry search finds the wrong one."""
    m = POS_MARK.search(entry_text[:150])
    if not m:
        return None
    v = m.group(1).lower().replace(' ', '')
    return {'prep': 'praep'}.get(v, v)


POS_MARK = re.compile(r'\b(adv|adj|praep|prep|conj|pron|interj|'
                      r'v\.\s*(?:a|n|dep|freq|impers)|subst|num)\b\.?', re.I)


# ------------------------------------------------------- cross-references
# "v. condicio" / "vide abdo" / "cf. clipeus" / "q. v." point at another entry.
# The look-behind keeps `v.` from matching inside "adv." and "vide" inside
# "provide": without it "Adv. comp., abditius" resolved to the entry `comp`.
TARGET = re.compile(r'(?<![A-Za-z])(?:v\.|vide|cf\.|q\.\s*v\.)\s*'
                    r'(?:(?P<num>\d+)[,.]?\s*)?(?P<word>[A-Za-zÀ-ɏ\'-]+)', re.I)
# "v. a.", "v. dep." are the verb marker, not a reference
VERB_SUBTYPE = {'a', 'n', 'act', 'pass', 'dep', 'semidep', 'freq', 'inch', 'incoh',
                'impers', 'intens', 'desid', 'defect', 'irreg'}
# "abditus, a, um, Part. of abdo."  /  "secretus, Part. and P. a., from secerno."
DERIV = re.compile(r'\b(?:Part\.|P\.\s*a\.|Sup\.|Comp\.|[Ii]nf\.)[^.]{0,30}?,?\s*(?:from|of)\s+'
                   r'(?P<word>[A-Za-zÀ-ɏ\'-]+)', re.I)
# "v. the foll. art." points at the next entry; "preced." at the previous one
FOLL = re.compile(r'\b(foll|preced)\w*\.?\s+art', re.I)
# "cf. Fronto Ter. Als. 4." cites the author Fronto, not the entry `fronto`
# ("broad-forehead person", which is what `illatenus` shipped as). A
# capitalised target followed by another abbreviation, by a number, or by
# ". p." is a citation. "v. Illiberi." and "v. Hispani, II. A. fin." are not.
CITATION_TAIL = re.compile(r'\s+(?:[A-Z][A-Za-z]{0,7}\.|\d)|\.\s+(?:p\.|\d)')


def xref_target_word(body):
    """(homograph number or None, target word) named by a cross-reference, or None."""
    text = re.sub(r'\([^()]*\)', ' ', body)
    for m in TARGET.finditer(text):
        w = m.group('word')
        if w[:1].isupper() and CITATION_TAIL.match(text, m.end()):
            continue
        # "v. h. v." is *vide hoc verbum*; a one-letter target is never an entry
        # a reader wants ("patalis, false reading of patulus, v. h. v." resolved
        # to the letter h, "eighth letter of the alphabet")
        if w.lower() not in VERB_SUBTYPE and len(w) > 1:
            return m.group('num'), w
    m = DERIV.search(text)
    return (None, m.group('word')) if m else None


class XrefIndex:
    """Resolve cross-references between rows of the gloss TSV.

    One definition for every stage. lsgloss.py, xrefix.py and score.py each
    carried their own copy of the target regex and they had drifted: one saw
    "Part. of", one saw "q. v.", and one resolved "v. a." to the entry `a2`."""

    def __init__(self, rows, bodies):
        self.bodies = bodies
        self.index, self.keyed = {}, {}
        for i, r in enumerate(rows):
            key, orth = r[0], r[1]
            self.index.setdefault(letters(orth), i)
            if key:
                self.index.setdefault(letters(re.sub(r'\d+$', '', key)), i)
                mk = re.match(r'(.*?)(\d+)$', key)
                if mk:
                    self.keyed.setdefault(letters(mk.group(1)) + mk.group(2), i)

    def target_of(self, i):
        """Index of the entry this one cross-references, or None."""
        body = self.bodies[i]
        m = FOLL.search(re.sub(r'\([^()]*\)', ' ', body))
        if m:
            j = i + (1 if m.group(1).lower().startswith('foll') else -1)
            return j if 0 <= j < len(self.bodies) else None
        t = xref_target_word(body)
        if not t:
            return None
        num, word = t
        # "v. 2. repens" means the SECOND repens: repens(1) is "creeping" (from
        # repo), repens(2) is "sudden". Ignoring the number picks the wrong one.
        if num:
            j = self.keyed.get(letters(word) + num)
            if j is not None:
                return j
        j = self.index.get(letters(word))
        return None if j == i else j

    def resolve(self, i, glosses, hops=4):
        """Follow references from row i to a row with a real gloss.

        Returns (j, gloss) or None. `glosses` is indexable by row."""
        seen, cur = {i}, i
        for _ in range(hops):
            j = self.target_of(cur)
            if j is None or j in seen:
                return None
            seen.add(j); cur = j
            g = (glosses[j] or '').strip()
            if g and g.upper() not in ('XREF', 'NONE'):
                return j, g
        return None


# ---------------------------------------------------------- checkpoints

def load_ckpt(path, prefix=None, key='i'):
    """{record[key]: record} from a JSON-lines checkpoint.

    With `prefix`, only the records of that pass (`p` field; a record with no
    `p` belongs to the main pass). Later lines win, so a re-run that corrects a
    row simply appends."""
    import os
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if prefix is not None and d.get('p', 'main') != prefix:
                continue
            if key in d:
                out[d[key]] = d
    return out


def checkpointed(path, items, work, *, jobs=4, tag='', extra=None, every=200, log=None):
    """Run `work(item)` over `items` in parallel, appending each result to `path`.

    `work` returns a dict (the record to keep) or None for a failure. A failure
    is NOT written: the next run sees the item as still to do and retries it.
    Every stage used to checkpoint its failures -- as "ERROR: ..." glosses, as
    empty strings, as `null` scores -- and then skip them on resume as if they
    were answered, so a server restart mid-run left permanent holes.

    Returns the list of records written. Ctrl-C cancels the queued work and
    re-raises; records already written stay."""
    import sys, time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    log = log or (lambda s: print(s, file=sys.stderr, flush=True))
    done, t0, n, failed = [], time.time(), 0, 0
    if not items:
        return done
    with open(path, 'a', encoding='utf-8') as ck:
        ex = ThreadPoolExecutor(max_workers=jobs)
        try:
            futs = [ex.submit(work, it) for it in items]
            for fut in as_completed(futs):
                rec = fut.result()
                n += 1
                if rec is None:
                    failed += 1
                else:
                    if extra:
                        rec = {**rec, **extra}
                    ck.write(json.dumps(rec, ensure_ascii=False) + '\n')
                    done.append(rec)
                if n % every == 0:
                    rate = n / max(1e-9, time.time() - t0)
                    log(f"  [{tag}] {n:,}/{len(items):,}  {rate:.2f}/s  "
                        f"eta {(len(items) - n) / rate / 60:.0f}m")
                    ck.flush()
        except KeyboardInterrupt:
            ex.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            ex.shutdown(wait=True)
    if failed:
        log(f"  [{tag}] {failed:,} of {len(items):,} failed and were not checkpointed; "
            f"re-run to retry them")
    return done
