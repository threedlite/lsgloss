"""Grounding check: does a gloss reuse the entry's own vocabulary?

Glosses are meant to condense the dictionary's wording, so a gloss whose content
words appear nowhere in its entry is usually invented. This is a signal, not a
verdict: entries defined only in Latin produce correct glosses that score zero,
so ungrounded rows are flagged for review rather than discarded.
"""
import re, unicodedata

STOP = {'a','an','the','of','to','in','or','and','for','with','on','at','from','by',
        'one','who','that','is','be','as','it','who','which','something','someone'}

def _words(s):
    s = unicodedata.normalize('NFKD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return [w for w in re.sub(r'[^a-z ]', ' ', s).split() if w not in STOP and len(w) > 2]

def _stem(w):
    return w[:max(4, len(w) - 2)]

def score(gloss, entry_text):
    """Fraction of the gloss's content words that appear in the entry. 1.0 = fully grounded."""
    gw = [_stem(w) for w in _words(gloss)]
    if not gw:
        return 1.0
    body = {_stem(w) for w in _words(entry_text)}
    return sum(1 for w in gw if w in body) / len(gw)
