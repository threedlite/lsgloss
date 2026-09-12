"""Corpus frequency of a LEMMA, not of its headword spelling.

Counting only the headword form badly misjudges usage. A reader meets *fatum* as
`fato`, `fata`, `fatis`; the bare nominative is comparatively rare, so ranking by
it hides one of the commonest words in Latin. Worse, a rare word whose headword
happens to be spelled like a common word's inflection inherits that frequency:
`alto` is a rare verb "to make high", but the form `alto` in running text is
almost always the ablative of *altum*, so the verb looks common and wins
collisions it should lose.

Summing the corpus counts of every form a lemma generates fixes both.
"""
import re
from inflect import forms_for, fold


def load_form_counts(path):
    counts = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            w, _, n = line.rstrip("\n").partition("\t")
            if n.isdigit():
                counts[fold(w)] = counts.get(fold(w), 0) + int(n)
    return counts


def lemma_frequencies(rows, entry_texts, form_counts, paradigms=None):
    """{entry_key: summed corpus count over the forms that entry generates}.

    Keyed per ENTRY, not per digit-stripped lemma. L&S numbers homographs off a
    shared stem, but they are usually unrelated words: `in1` is the preposition
    while `in3`..`in16` are in-actuosus, in-aequabilis, in-exstinctus and so on.
    Collapsing them onto the key `in` and taking the max handed every one of them
    the preposition's 137,440 tokens, so a rare adjective outranked most of the
    real vocabulary and freqfix spent 16 of its screening slots on one stem.

    For the same reason the digit-stripped key is no longer added to the form set:
    for `in3` that injected the form `in`, which is a different word. A caller that
    wants a per-lemma figure should take the max itself over the entries it groups.

    `paradigms`, if given, maps entry key -> the forms already generated for it,
    so a caller that has built every paradigm (package.py) does not build them
    all a second time.
    """
    out = {}
    for r, body in zip(rows, entry_texts):
        total = 0
        fs = paradigms.get(r[0]) if paradigms is not None else None
        if fs is None:
            fs = forms_for(r[1], body[:200])
        for f in set(fs) | {fold(r[1])}:
            total += form_counts.get(f, 0)
        if total:
            out[r[0] or fold(r[1])] = total
    return out
