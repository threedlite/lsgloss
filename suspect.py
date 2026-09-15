"""Mechanical detectors for glosses that are probably wrong.

Cheap signals only -- no model calls -- so the whole output can be screened and
only the suspects sent for expensive re-glossing.
"""
import re
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parent))
from common import letters as _norm, focus as _focus
from ground import score as ground_score

POSDESC = re.compile(r'^\s*(a |an |the )?'
                     r'(enclitic |demonstrative |interrogative |relative |personal |copulative |negative |indefinite |'
                     r'inseparable |strengthening |intensive |emphatic |disjunctive |causal |temporal |conditional )*'
                     r'(preposition|particle|conjunction|pronoun|adverb|interjection|prefix|suffix|numeral)\b', re.I)
LATIN   = re.compile(r'[āēīōūăĕĭŏŭȳǣœæ]|[Ͱ-Ͽ]')       # macrons/breves/Greek left in the gloss
DECL    = re.compile(r'^(ae|i|is|us|um|a|onis|ei|n|m|f|entis|atis|inis)$', re.I)
ADVERBY = re.compile(r'(e|iter|ter)$')
# words that are never a gloss on their own (unlike "and", "from", "to", "not")
NEVER_ALONE = {'of','in','on','at','one','that','this','is','be','it','as','so','who','which','the','a','an'}
FUNC = {'of','to','in','on','at','by','for','with','from','and','or','the','a','an','that','this',
        'is','be','it','as','not','so','if','one','who','which','into','out','up','down','off','over',
        # "he who has been a decurion" cut at the relative clause is "he"
        'he','she','they','those','these',
        # a participle waiting for its complement: "of or belonging" says nothing
        'belonging','pertaining','relating'}
PRONOUN = {'he','she','they','it','those','these','this','that','one'}
# a gloss can never END on these
CUT_OFF = {'belonging', 'pertaining', 'relating', 'the', 'a', 'an'}

# L&S's editorial apparatus used as a definition. "abathon, false reading in
# Vitruvius" records that the word does not exist; it is not a gloss, and the
# grounding check passes it because "false" and "reading" are in the entry.
EDITORIAL = re.compile(r'^(?:a |an )?(?:false|corrupt|doubtful|erroneous|wrong|spurious|'
                       r'various|variant|conjectural|manuscript|old|another|ancient)\s+'
                       r'(?:reading|lection|conjecture)\b'
                       r'|^(?:reading|lection|conjecture) for\b'
                       r'|^(?:false|corrupt|spurious) (?:form|word)\b', re.I)


# Entries L&S marks as function words legitimately gloss to function words:
# "ex" -> "out of, from" is correct and must not be read as a truncation
# fragment, and a pronoun's English gloss ("I, myself") will not appear in the
# Latin entry text, so grounding cannot apply either.
# L&S uses Latin abbreviations: praep. for preposition, pron. for pronoun
FUNCTION_ENTRY = re.compile(r'\b(praep|prep|conj|adv|pron|interj|particle|num|indecl)\b\.?', re.I)
# "Tert. adv. Marc." is a citation of Tertullian *adversus Marcionem*, and it
# put "adv." inside the window on 1,616 noun and adjective entries, exempting
# every one of them from the grounding and fragment checks. A marker that
# follows an author abbreviation and precedes a capitalised title is a citation.
CITED_ADV = re.compile(r'\b[A-Z][A-Za-z]{1,6}\.\s*(?:[Aa]dv|ad|c|contra)\.?\s+[A-Z][A-Za-z]*\.?')
# "—Adv.: actualiter" introduces the entry's derived adverb, a different word;
# "by conj." is a conjecture, not a conjunction
DERIVED_ADV = re.compile(r'[—-]\s*Adv\.|\bby conj\.', re.I)
# How far into the focused text the entry's own marker can sit. The headword
# line is short once `focus` has dropped the parentheses; 300 characters reached
# into the definition and the citations on ~1,600 noun and adjective entries.
FUNCTION_WINDOW = 80

def function_entry(focused):
    """Does the entry's headword line mark it as a function word?"""
    head = DERIVED_ADV.sub(' ', CITED_ADV.sub(' ', focused[:300]))
    return bool(FUNCTION_ENTRY.search(head[:FUNCTION_WINDOW]))

# In this revision of L&S the etymon is often printed UNBRACKETED, straight after
# the gender marker or the conjugation number: "pĭĕtas, ātis, f. pius, dutiful
# conduct towards the gods". `focus` strips (...) and [...] but cannot see this,
# so the model reads the etymon as the definition and glosses *pietas* as "pius".
# A bare Latin word is not caught by anything else here: `latin-chars` only fires
# on macrons and Greek, and plain ASCII `pius` is grounded, English-shaped and the
# right length.
# A gloss that describes the word's ROLE instead of translating it. POSDESC above
# only matches when the gloss STARTS with a bare part-of-speech noun, so "and
# (conjunction)", "example introducer" and "to introduce an explanation" all
# passed -- and those are the highest-token defects in the corpus.
#
# Both patterns are gated on OWNPOS below, because on their own they are mostly
# false positives: "glittering particle, polish" and "to mark out" are ordinary
# glosses of a noun and a verb. It is only when the ENTRY is itself a function
# word that naming a word class is evidence of a metalinguistic gloss.
POSWORD = re.compile(r'\b(?:preposition|particle|conjunction|pronoun|interjection|'
                     r'prefix|suffix|numeral|introducer)\b', re.I)
FRAME   = re.compile(r'^(?:denot\w*|indicat\w*|introduc\w*|ask\w*|stands? for|'
                     r'equivalent to|used\b)'
                     r'|^to\s+(?:introduce|express|denote|indicate|emphasi[sz]e)\b'
                     # "departure from a fixed point" (ab), "of place, down" (de),
                     # "use of utor" (uti): the grammarian's frame, not the word
                     r'|^(?:departure|motion|movement|separation|direction|position|relation)\b'
                     r'|^of (?:place|time|space|manner|degree|cause|number|source)\b'
                     r'|^(?:use|sense|meaning|signification) of\b', re.I)
# "Graeco-Italic form of wind" (animus), "old form of agito": a note on where
# the word comes from, not what it means. "form of a bow" (arcuatim) is a gloss.
# "first letter of Latin alphabet" (a), "eighth letter" (mi): a letter, not a word
LETTER = re.compile(r'^(?:the )?(?:(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|'
                    r'eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|'
                    r'nineteenth|twentieth|twenty-\w+|\d+(?:st|nd|rd|th)) letter\b'
                    r'|(?:\w+ )?letter of (?:the )?(?:latin |roman |greek )?alphabet\b)', re.I)
FORM_NOTE = re.compile(r'^(?:an? |the )?(?:old|older|archaic|ancient|earlier|later|former|collateral|shortened|'
                       r'lengthened|contracted|childish|vulgar|access|primitive|original|secondary|obsolete|'
                       r'poetic|fuller|dialectic|Graeco-Italic|Oscan|Umbrian|Greek|Doric|Aeolic|Latin|'
                       r'rare|another|second|weakened|strengthened|softened|abbreviated|variant|by-)\s*form of\b', re.I)
# the entry's OWN part-of-speech marker, in the headword line only. FUNCTION_ENTRY
# scans 300 characters and matches an "adv." anywhere, which is far too loose here.
OWNPOS  = re.compile(r'^[^,]{0,40}(?:,[^,]{0,30}){0,3}?,\s*(?:[a-z]\.\s*)?'
                     r'(?:praep|prep|conj|adv|pron|interj|indecl|particle)\b\.?', re.I)

ETYMON = re.compile(r'\b(?:f|m|n|comm|adj|adv|dep|freq)\.\s*(?:\d\.?\s*)?([A-Za-zÀ-ɏ]{3,})\s*[,;]'
                    r'|,\s*\d\s+([A-Za-zÀ-ɏ]{3,})\s*,')

def is_bare_echo(headword, gloss):
    """The gloss is the headword itself, or the headword plus a declension
    ending: "Melos" -> "Melos, i". Carries no information."""
    h = _norm(headword)
    parts = [p.strip() for p in re.split(r'[;,]', gloss) if p.strip()]
    return bool(parts) and bool(h) and all(_norm(p) == h or DECL.match(p) for p in parts)


def gloss_vocabulary(rows):
    """{word: number of OTHER entries that use it in their gloss}.

    Used to tell a Latin headword echoed into its own gloss ("tamen,
    nevertheless, however") from a genuine Latin-English cognate ("orator ->
    speaker, orator"). Both repeat the headword; only the cognate is also a word
    the rest of the dictionary reaches for when glossing something else.

    Counting uses by OTHER entries is what makes it a test of Englishness rather
    than of repetition -- an entry echoing its own headword is not evidence.
    """
    import collections
    out = collections.Counter()
    for r in rows:
        if len(r) < 3:
            continue
        # a cross-reference copies another entry's gloss: `attamen` reading
        # "tamen, nevertheless" is not a second entry reaching for "tamen"
        if len(r) > 3 and r[3].startswith('xref'):
            continue
        h = _norm(r[1])
        for w in {_norm(x) for x in re.split(r'[\s,;]+', r[2]) if x.strip()}:
            if w and w != h:
                out[w] += 1
    return out


def reasons(headword, gloss, source, entry_text, gloss_vocab=None):
    """Why this gloss looks wrong. Empty list = no mechanical objection."""
    g = gloss.strip()
    if not g: return []
    src = source.rstrip('~?')
    out = []
    # Grounding is only meaningful when the gloss was written from THIS entry;
    # a cross-reference legitimately takes its wording from the target's entry.
    # Read the part-of-speech marker from the FOCUSED text, not the raw opening.
    # L&S prefaces its commonest words with a long parenthesis on orthography and
    # prosody -- `ex` and `ego` both run past 300 characters before reaching
    # "praep." / "pron." -- so a raw window misses the marker on exactly the
    # entries this exemption exists for, and their correct glosses ("out of, from",
    # "I, myself") were being flagged as fragments and as ungrounded.
    focused = _focus(entry_text)
    is_function = function_entry(focused)
    if (src in ('model', 'repaired', 'named') and not is_function
            and ground_score(g, entry_text) == 0.0):
        out.append('ungrounded')
    if POSDESC.match(g) or LETTER.match(g): out.append('word-class')
    if FORM_NOTE.match(g.replace('‑', '-')): out.append('form-note')
    elif OWNPOS.match(focused[:120]) and (POSWORD.search(g) or FRAME.match(g)):
        out.append('word-class')
    if LATIN.search(g):  out.append('latin-chars')
    if EDITORIAL.match(g): out.append('editorial-apparatus')
    h = _norm(headword)
    parts = [p.strip() for p in re.split(r'[;,]', g) if p.strip()]
    if is_bare_echo(headword, g):
        out.append('bare-echo')
    words = [w.lower().strip(',;.:') for w in g.split()]
    if words and all(w in FUNC for w in words) and not is_function:
        # "one who is", "that which is" -- a truncation fragment, not a gloss;
        # "he, she, it" is the whole gloss of a pronoun form (*sos*, *ibus*)
        if len(words) > 1 and not all(w in PRONOUN for w in words): out.append('fragment')
        elif words[0] in NEVER_ALONE: out.append('fragment')
        # "not" on its own glosses *non* and nothing else. An entry whose
        # headword line carries no function-word marker, glossed as one bare
        # function word, was cut off: "not adapted for relation" -> "not",
        # `Iliberi` -> "to". A cross-reference may legitimately inherit one
        # from a function word (`noenum` -> "not", from *non*), and a bare
        # pronoun is the whole gloss of a pronoun form ("them" on *sos*).
        elif src != 'xref-resolved' and words[0] not in PRONOUN: out.append('fragment')
    elif len(words) == 3 and words[:2] == ['of', 'or']:
        # "of or made", "of or suited": the cut that made "of or belonging",
        # whatever the third word is
        out.append('fragment')
    elif len(words) > 1 and words[-1] in CUT_OFF:
        # "of or belonging" is cut off before its complement whatever the
        # entry is; a numeral adjective ("trecenarius, adj. num.") is exempt
        # from the test above and shipped exactly that
        out.append('fragment')
    # a Latin headword echoed at the head of its own gloss, where the rest of the
    # gloss carries the sense: "tamen, nevertheless, however, still". Needs the
    # corpus vocabulary to avoid firing on cognates, so it is skipped when the
    # caller has none. Deliberately conservative -- a word used by even one other
    # entry is treated as English, because a false positive here is re-glossed
    # with no score gate and can come back worse.
    if gloss_vocab is not None and len(parts) > 1 and h and not headword.lstrip('-^')[:1].isupper():
        if _norm(parts[0]) == h and gloss_vocab.get(h, 0) < 1:
            out.append('head-echo')
    # a one-word gloss that is just the entry's etymon
    if len(g.split()) == 1:
        m = ETYMON.search(entry_text[:160])
        if m:
            ety = _norm(m.group(1) or m.group(2) or '')
            if ety and ety == _norm(g) and ety != h:
                out.append('etymology-leak')
    # an adverb that inherited its target verb's infinitive gloss
    if src == 'xref-resolved' and ADVERBY.search(headword.rstrip('.')) and re.match(r'^to\s', g):
        out.append('adv-inherits-verb')
    return out


def strip_head_echo(headword, gloss, gloss_vocab):
    """"tamen, nevertheless, however" -> "nevertheless, however": the Latin
    headword echoed in front of its own gloss, judged as `head-echo` is
    (a word no other entry uses in English is Latin), is removed. A rule, not
    a hand edit; the rest of the gloss must be there to keep."""
    parts = [p.strip() for p in re.split(r'[;,]', gloss) if p.strip()]
    h = _norm(headword)
    if (len(parts) > 1 and h and not headword.lstrip('-^')[:1].isupper()
            and _norm(parts[0]) == h and gloss_vocab.get(h, 0) < 1):
        return ', '.join(parts[1:])
    return gloss
