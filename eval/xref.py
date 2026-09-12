"""Detect entries that are pure cross-references, so they never reach the model.

L&S cross-reference entries take a few shapes:
    inspargo, insparsus, v. inspergo.
    abditē, adv., v. abdo, P. a. fin.        <- trailing section pointer
    grātīs, adv., v. gratia, B. fin.
    condĭtĭo (condition, etc.), v. condicio, etc.
    sēcrētus, a, um, Part. and P. a., from secerno.
    ăbactus, a, um, Part. of abigo, q. v.

Anything with a definition of its own must NOT match -- notably "v." also
abbreviates *verbum*, as in "ab-brĕvĭo, āre, v. freq. a. ... to shorten".
"""
import re

PARENS = re.compile(r'\([^()]*\)')
# "v." used as a part-of-speech marker (verbum), not "see"
POS    = re.compile(r'\bv\.\s+(freq|dep|a|n|impers|inch|intens|defect)\b', re.I)
# trailing navigational pointers, stripped one at a time from the end
# a lone letter counts as a section pointer only when it carries its period
# ('fin. b.'); without that guard this strips real words letter by letter
TAIL   = re.compile(r'[\s,;]*(?:q\.\s*v|P\.\s*a|Part|init|fin|ad\s+fin|etc|no|under\s+\w+|adv|adj|subst|abl|acc|dat|gen|voc|nom|sing|plur|masc|fem|neutr|[IVXLC]+(?=\.)|[A-Za-z](?=\.)|\d+)\s*\.?\s*$')
# a bare "see X" reference: "v. abdo" / "vide abdo" / "v. 1. congero"
SEE    = re.compile(r'[,;]\s*(?:v\.?|vide)\s+(?:\d+\.?\s*)?[A-Za-zÀ-ɏ\'-]+\s*\.?\s*$', re.I)
# "Part. of X" / "Part. and P. a., from X"
GRAM   = re.compile(r'\b(?:Part\.|P\.\s*a\.|Sup\.|Comp\.)[^.]{0,30},?\s*(?:from|of)\s+[A-Za-zÀ-ɏ\'-]+\s*\.?\s*$', re.I)

def _strip_tail(s, limit=6):
    """Remove trailing pointers like ', P. a. fin.' one component at a time."""
    for _ in range(limit):
        t = TAIL.sub('', s, count=1)
        if t == s:
            break
        s = t
    return s.strip()

def is_xref(text):
    if len(text) > 160:
        return False
    core = re.sub(r'\s+', ' ', PARENS.sub(' ', text)).strip()
    if POS.search(core):
        return False
    if GRAM.search(core) or GRAM.search(_strip_tail(core)):
        return True
    return bool(SEE.search(core) or SEE.search(_strip_tail(core)))
