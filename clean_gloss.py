import re
NOTE=re.compile(r'\s*\((?:note|the user|instruction)\b.*$', re.I|re.S)
# a bare part-of-speech annotation is never part of a gloss: "box (verb)"
#
# The function-word classes were missing from this list, which is why the
# commonest word in Latin shipped as "and (conjunction)". An optional qualifier
# covers "(reflexive pronoun)" and "(negative particle)"; it is deliberately a
# single word so that a register label like "(post-Aug.)" -- which is not a part
# of speech at all -- is still kept.
POS = (r'verb|adj|adjective|adverb|noun|n|v|pl|sing|'
       r'conjunction|conj|preposition|prep|pronoun|pron|particle|'
       r'interjection|interj|numeral|num')
QUALIFIER = (r'enclitic|demonstrative|interrogative|relative|personal|reflexive|'
             r'possessive|copulative|negative|indefinite|disjunctive|inseparable')
POSNOTE=re.compile(rf'\s*\((?:(?:{QUALIFIER})\s+)?(?:{POS})\.?\)', re.I)
ABBR=re.compile(r'^[A-Za-z][A-Za-zà-ÿ]{0,6}\.$')       # Plin. Liv. Fest. Varr. ep. id. ib.
# ABBR reads any short word with a trailing period as a citation, so a model that
# ignores "no trailing period" and answers "wild wolf." lost its last word, and
# "wolf." became an empty gloss that fell through to no-gloss. Author
# abbreviations are capitalised (Plin., Liv., Cic.); the lower-case ones L&S uses
# are a short closed set. A lower-case final token outside that set is a word.
LOWER_ABBR = {'id', 'ib', 'ibid', 'ep', 'al', 'sq', 'sqq', 'cf', 'ap', 'fin', 'init',
              'l', 'c', 'v', 'p', 'n', 'ad', 'loc', 'cit', 'pr', 'fr', 'frag', 'praef',
              'prooem', 'dub', 'inscr', 'lex', 'll', 'no'}
def _is_citation(w, nxt):
    """Is this token the start of a citation? `nxt` is the token after it."""
    if ABBR.match(w):
        core = w[:-1]
        # a lower-case word ending the gloss with a period is prose, not a citation
        if len(core) > 1 and core.islower() and core not in LOWER_ABBR and nxt is None:
            return False
        return True
    if EXAMPLE.match(w) or '§' in w or w.lower().startswith('q.'):
        return True
    if re.search(r'\d', w):
        # "one of 12 lictors": a plain count followed by a word is prose. A
        # citation number is followed by another number, a comma, or nothing.
        if re.fullmatch(r'\d{1,3}', w) and nxt and re.fullmatch(r'[a-z]{3,}', nxt):
            return False
        return True
    return False
# "Roman nomen, e.g" -- an example marker introduces a citation, and the gloss
# ends there. ABBR misses these because the dot is internal, not trailing.
#
# Deliberately NOT "i.e.": that introduces a restatement, which is usually real
# gloss content -- cutting there turned "abjuring, i.e. resigning, abdication"
# into the poorer "abjuring".
EXAMPLE=re.compile(r'^(?:e\.?\s*g|cf)\.?,?$', re.I)
DANGLE={'of','by','in','for','to','with','and','or','the','a','an','from','on','at','as'}
def _collapse(g):
    """Greedy decoding sometimes loops. Cut at the first repeated n-gram."""
    w = g.split()
    for n in range(1, 9):
        for i in range(len(w) - 2*n + 1):
            if w[i:i+n] == w[i+n:i+2*n]:
                return ' '.join(w[:i+n])
    return g

# Trailing words no gloss may end on. The three participles are what "of or
# belonging TO A DEITY" is cut down to when the cap falls on "to": 555 rows
# shipped as the bare "of or belonging" and "of or pertaining", and no detector
# saw them because "belonging" is not a preposition.
DANGLE_EXTRA={'a','an','the','belonging','pertaining','relating'}
BREAK={'of','from','in','on','to','with','by','for','at','into','among','between',
       'over','under','through','about','against','before','after','upon','and','or'}

CONTENTLESS = {'of','to','in','on','at','by','for','with','from','and','or','the','a','an',
               'that','this','is','be','it','as','not','so','if','one','who','which','was','were',
               'into','out','up','down','off','over','been','are','him','her','them',
               'belonging','pertaining','relating'}

def _contentless(s):
    w = [x.lower().strip(',;.:') for x in s.split()]
    return bool(w) and all(x in CONTENTLESS for x in w)

# Leading phrases that can be dropped to bring a gloss under the cap, least
# destructive first. "of the colour of myrtle-berries" truncates to the useless
# "of the colour"; dropping the leading preposition keeps the informative tail.
# "of or belonging to a deity" loses "of or" before it loses "belonging to".
LEAD_STRIPS = [
    re.compile(r'^of or (?=(?:belonging|pertaining|relating) to\b)', re.I),
    re.compile(r'^(of|to|in|for|belonging to|relating to|pertaining to)\s+(the|a|an)\s+', re.I),
    re.compile(r'^(?:of or )?(?:belonging|pertaining|relating) to\s+(?:(?:the|a|an)\s+)?', re.I),
]
LEAD = LEAD_STRIPS[1]     # kept under its old name for callers and tests

def enforce(g, maxwords=5):
    """Guarantee the word cap by cutting at the longest phrase boundary that fits.

    Cutting mid-phrase ('city on the borders of' -> 'city on the borders of') reads
    as broken, so prefer the last preposition/conjunction at or under the cap.
    """
    if len(g.split()) > maxwords:
        for rx in LEAD_STRIPS:
            if rx.match(g):
                stripped = rx.sub('', g).strip()
                if stripped and len(stripped.split()) <= maxwords:
                    g = stripped
                    break
    w = g.split()
    if len(w) <= maxwords:
        return g
    cuts = [i for i, x in enumerate(w) if x.lower().strip(',;') in BREAK and 0 < i <= maxwords]
    cut = max(cuts) if cuts else maxwords
    out = _undangle(w[:cut])
    if not out:
        out = _undangle(w[:maxwords]) or w[:maxwords]
    res = ' '.join(out).strip(' .,;:')
    # A cut that leaves only function words ("one who is") is worse than a longer
    # phrase; keep more of the original rather than emit a fragment. The longer
    # slice has to be undangled too -- without that, this fallback swapped one bad
    # output for another and "one who is of the household" came out as the
    # dangling "one who is of the".
    if _contentless(res) and not _contentless(g):
        alt = _undangle(w[:maxwords]) or w[:maxwords]
        res = ' '.join(alt).strip(' .,;:')
    return res

def _undangle(words):
    """Drop trailing function words: no gloss may end on 'of', 'to' or 'the'."""
    out = list(words)
    while out and out[-1].lower().strip(',;:') in BREAK | DANGLE_EXTRA:
        out.pop()
    return out


TAILPAREN=re.compile(r'\s*\([^)]*\)\s*$')
# L&S calls a family name a "nomen" and a "gens name", and the model copied
# both; "nomen" is Latin, and six phrasings of one category read as six
# things. One English rendering each: nomen and gens name are the family name,
# cognomen the surname. The prompt's own example is "Roman surname".
NAME_RENDER = [(re.compile(r'\bname of (?:a|the) Roman gens\b', re.I), 'Roman family name'),
               (re.compile(r'\bRoman (?:nomen|gens name)\b', re.I), 'Roman family name'),
               (re.compile(r'\bRoman cognomen\b', re.I), 'Roman surname')]

def clean(g, maxwords=5):
    g=g.split('\n')[0].strip()
    g=NOTE.sub('', g)
    g=POSNOTE.sub('', g).strip()
    g=_collapse(g)
    # cut at the first citation-looking token: abbreviation, digit, section sign, q.v.
    out=[]
    ws = g.split()
    for k, w in enumerate(ws):
        if _is_citation(w, ws[k+1] if k+1 < len(ws) else None):
            break
        out.append(w)
    truncated = len(out) < len(ws)
    g=' '.join(out)
    # Tidy a dangling preposition only when the phrase was actually cut, and never
    # strip a gloss to nothing: "and" and "out of, from" are complete glosses.
    while truncated and len(out) > 1 and out[-1].strip(',;:').lower() in DANGLE:
        out.pop(); g=' '.join(out)
    g=re.sub(r'^(a|an|the)\s+','',g,flags=re.I)
    parts=[p.strip() for p in re.split(r'[;,]', g) if p.strip()]
    if len(parts)>1:
        keep=[]; n=0
        for p in parts:
            if keep and n+len(p.split())>maxwords-1: break
            keep.append(p); n+=len(p.split())
        g=', '.join(keep)
    g=re.sub(r'\s*\([^)]*$','',g)
    for rx, english in NAME_RENDER:
        g=rx.sub(english, g)
    g=g.strip(' .,;:')
    if len(g.split())>maxwords:               # a trailing "(rare)" often puts us over
        t=TAILPAREN.sub('',g).strip(' .,;:')
        if t and len(t.split())<=maxwords: g=t
    return g
