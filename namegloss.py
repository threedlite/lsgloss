"""The dictionary's own definition for a proper-name entry.

For a name -- a person, a place, a people -- the model's gloss was the weakest
part of the output: "Athenian" by default, "courtesan" copied from the prompt's
example, "tenth part" on *Hercules*. Lewis & Short already states what a name
is, in a short italic phrase at the head of the first sense ("a sculptor", "a
hill of Jerusalem", "son of Jupiter and Alcmena"), and the XML keeps that
markup. So a capitalised headword takes that phrase verbatim, and the model's
gloss is only the fallback where the entry has none.

Names are not held to the five-word cap: "a daughter of the Athenian king
Erechtheus" is what the reader needs, and cutting it to five words is what made
"Athenian courtesan" plausible. They get NAME_MAXWORDS instead, which keeps 94%
of the italic definitions whole; the rest are cut at a phrase boundary like any
other gloss.

What is NOT taken: an italic that is a grammar note ("conj.", "nom. sing.",
"subst."), a bare repeat of the headword ("Abbassus" -- the next run, "a town
in Phrygia", is taken instead), a cross-reference, or a Greek equation.
"""
import re, html, unicodedata
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parent))
from common import txt, letters
from clean_gloss import _undangle, NAME_RENDER, RELATIVE
from suspect import is_bare_echo

NAME_MAXWORDS = 10
SOURCE = 'ls'                        # the source column value: the entry's own words

SENSE = re.compile(r'<sense\b.*?</sense>', re.S)
ITALIC = re.compile(r'<hi rend="ital">(.*?)</hi>', re.S)
# "conj.", "nom. sing.", "init.", "subst.", "acc" -- a note, not a definition
ABBREV = {'nom', 'gen', 'dat', 'acc', 'abl', 'voc', 'sing', 'plur', 'pl', 'sg', 'neutr', 'masc',
          'fem', 'adj', 'adv', 'subst', 'init', 'fin', 'sup', 'comp', 'dim', 'conj', 'praep',
          'prep', 'prop', 'id', 'ib', 'al', 'sc', 'orig', 'gr', 'lat', 'poet', 'v', 'cf', 'p',
          'q', 'i', 'e', 'esp', 'meton', 'trop', 'transf', 'lit', 'abs', 'absol', 'part', 'perf'}
NOTE = re.compile(r'^(?:[a-z]{1,7}\.\s*)+$')
# where the definition phrase ends: a citation, a quotation, a Greek equation
CUT_TAG = re.compile(r'<(?:bibl|cit|quote|usg|foreign)\b')
# ...or, in the text: a semicolon, a sentence end, a parenthesis, or a comma that
# opens an aside ("a hill of Jerusalem, and, by meton., Jerusalem")
# A sentence ends at a period unless it closes an initial or a short
# abbreviation: "captured by L. Scipio", "born A.D. 272", "St. Paul"
CUT_TEXT = re.compile(r'[;:(=]|(?<![A-Z])(?<!\b[A-Z][a-z])\.\s+(?=[A-Z]|$)|(?<![A-Z])\.$|[\u0370-\u03ff\u1f00-\u1fff]'
                      r'|,\s*(?:and|or|also|hence|i\. ?e|e\. ?g|esp|' + '|'.join(sorted(ABBREV)) + r')\b')
# a phrase may not end on these either: "town in Picenum, now"
TRAIL = {'now', 'called', 'near', 'formerly', 'afterwards', 'later'}
LIG = str.maketrans({'æ': 'ae', 'œ': 'oe', 'Æ': 'Ae', 'Œ': 'Oe'})


def is_name_entry(headword):
    """A capitalised headword is a proper name in L&S; a single letter is the
    entry for the letter itself ("L", "the twelfth letter")."""
    h = headword.strip('-^')
    return h[:1].isupper() and len(letters(h)) > 1


def _text(xml):
    """Tags stripped, ligatures expanded, macrons and breves dropped: the entry
    prints Penēus and Œdipus, a reader types Peneus and Oedipus."""
    s = unicodedata.normalize('NFKD', html.unescape(txt(xml)).translate(LIG))
    return ''.join(c for c in s if not unicodedata.combining(c))


def _same_name(word, headword):
    """`word` is the headword in English dress, singular or plural."""
    return letters(word).rstrip('s') == letters(headword).rstrip('s')


def _is_echo(headword, g):
    """The gloss is the headword, or its plural: "an Amazon", "Amazons"."""
    bare = re.sub(r'^(?:a|an|the)\s+', '', g, flags=re.I)
    return is_bare_echo(headword, bare) or _same_name(bare, headword)


def _is_note(run):
    words = [w.strip('.,;:').lower() for w in run.split()]
    return not words or NOTE.match(run.strip()) is not None or all(w in ABBREV for w in words)


def italic_runs(entry_xml):
    """The italic phrases of the first sense, in order, tags stripped and
    ligatures expanded (L&S prints Œdipus; a reader types Oedipus)."""
    m = SENSE.search(entry_xml)
    body = m.group(0) if m else entry_xml
    return [_text(h) for h in ITALIC.findall(body)]


def name_gloss(entry_xml, headword):
    """The entry's own definition of a name, or '' when it has none usable.

    The phrase runs from the first italic to the first citation or sentence
    end, because L&S sets a Latin name inside the definition in roman type:
    "<i>a cognomen of several celebrated Romans in the</i> gens Porcia, Cic."
    is one phrase, and the italic alone stops at "in the"."""
    m = SENSE.search(entry_xml)
    body = m.group(0) if m else entry_xml
    # a quotation's translation is not the definition ("the Cyclopes, a
    # fabulous race" sits inside <cit> under *Cyclops*)
    body = re.sub(r'<(cit|quote)\b.*?</\1>', ' ', body, flags=re.S)
    h = letters(headword)
    for n, im in enumerate(ITALIC.finditer(body)):
        if n >= 3:
            break
        run = _text(im.group(1))
        if _is_note(run):
            continue                                   # grammar note: try the next run
        tail = CUT_TAG.split(body[im.start():], 1)[0]
        g = CUT_TEXT.split(_text(tail), 1)[0].strip(' .,;:')
        # "Abellinum, a city of the Hirpini", "the Hyades, a group of seven
        # stars": the English name leads the phrase
        m2 = re.match(r'^(?:(?:a|an|the)\s+)?([A-Z][^\s,:]*)\s*[,:]\s*(.+)$', g)
        if m2 and _same_name(m2.group(1), headword):
            g = m2.group(2).strip(' .,;:')
        words = g.split()
        while words and (words[-1].strip('.,;:').lower() in ABBREV | TRAIL
                         or _undangle(words) != words):
            words = _undangle(words)[:-1] if _undangle(words) == words else _undangle(words)
        g = ' '.join(words).strip(' .,;:')
        if not g or _is_echo(headword, g):
            continue                                   # "an Amazon" on Amazon: try the next run
        if g.startswith(('v. ', 'cf. ')) or len(letters(g)) < 3 or not re.search(r'[a-z]', g):
            return ''                                  # not a definition at all
        return g
    return ''


# ---------------------------------------------------------------- cleaning
# The general cleaner is built for model output and reads "Q." in "of Q.
# Lutatius Catulus" as a citation, cutting the phrase to "of". The entry's own
# text has had its citations removed by tag already; what is left to tidy is a
# leading grammar note ("adj., "), an aside ("orig.", "esp."), a parenthesis,
# the article, and a relative clause, which is a sentence about the name and
# not a gloss of it ("a daughter of Aeolus, who, from love to her husband...").
LEAD_NOTE = re.compile(r'^(?:[a-z]{1,7}\.,?\s*)+')
# a comma part that is an aside about the name, not part of what it is:
# "abbreviated T.", "usually represented by L.", "about 460 B.C."
ASIDE_PART = {'usually', 'usu', 'abbreviated', 'abbrev', 'written', 'represented', 'about',
              'born', 'died', 'flourished', 'killed', 'slain', 'reigned', 'b.c', 'a.d', 'bc', 'ad'}
# "of the fifth century A. D.", "reigned between 69 and 79 A.D."
ERA = re.compile(r'\s*(?:B\. ?C|A\. ?D)\.?(?:\s*\d[\d\-–]*)?$')
ASIDE = re.compile(r'\b(?:orig|esp|sc|viz|etc|i\. ?e|e\. ?g)\.\s*', re.I)


def name_clean(g, maxwords=NAME_MAXWORDS, headword=None):
    """Tidy an entry's own definition; the caller applies the cap with enforce()."""
    g = LEAD_NOTE.sub('', g)
    g = re.sub(r'\([^()]*\)', ' ', g)
    g = ASIDE.sub('', g)
    dated = ERA.sub('', g)
    if dated != g:                        # "who reigned A.D. 270": the clause went with its date
        g = re.sub(r'\s+(?:who|which|that)\s+\S+$', '', dated)
    g = re.sub(r'\s+', ' ', g).strip(' ,;:')
    g = re.sub(r'^(?:a|an|the)\s+', '', g, flags=re.I)
    keep, n = [], 0
    for p in [p.strip() for p in g.split(',') if p.strip()]:
        w = p.split()
        if not keep and headword and _same_name(p, headword):
            continue                              # "Hyades, a group of seven stars": the name itself
        first = w[0].lower().strip('.;:')
        if keep and (first in RELATIVE or first in ASIDE_PART or n + len(w) > maxwords - 1):
            break
        keep.append(re.sub(r'^(?:a|an|the)\s+', '', p, flags=re.I) if not keep else p); n += len(w)
    g = ', '.join(keep)
    for rx, english in NAME_RENDER:
        g = rx.sub(english, g)
    g = ' '.join(_undangle(g.split()))
    return re.sub(r'(?<![A-Z])\.$', '', g.strip(' ,;:'))
