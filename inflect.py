"""Map inflected Latin forms back to dictionary headwords.

Half the tokens in a Latin text never match a headword directly, because Latin is
heavily inflected: `amavit` is not `amo`, `portarum` is not `porta`. For a reader
working through an untranslated text that is the dominant failure -- far larger
than any gloss-quality issue.

Two mechanisms, both general rules over the whole corpus, neither hand-authored:

1. Orthographic folding. Latin i/j and u/v are the same letters; editions differ
   in which glyph they print, so `iam`/`jam` and `uel`/`vel` must compare equal.

2. Paradigm generation. L&S prints the morphology needed to inflect each word in
   the headword line itself -- `porta, ae, f.` is first declension, `rex, regis`
   gives the oblique stem `reg-`, `amo, avi, atum, are` is first conjugation.
   Parsing that and generating the paradigm indexes the forms a reader will
   actually meet.
"""
import re
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent))
from common import fold

# -que and -ve are true enclitics and can be split off safely. -ne is NOT: it
# collides with the ablative of every -io/-ionis noun (ratione, oratione,
# regione), so stripping it invents matches that are simply wrong.
#
# The stored spellings to look for, and the enclitic each one names. A word_form
# is folded (v -> u), so `-ve` is written `-ue` in the index and the list above
# on its own can never match one: `split_enclitic('uirumue')` returned no split
# at all. `-que` has to be tested BEFORE `-ue`, because `que` itself ends in
# `ue` and `uirumque` would otherwise split as `uirumq` + `ue`.
ENCLITIC_SPELLINGS = (('que', 'que'), ('ve', 've'), ('ve', 'ue'))

def split_enclitic(f):
    """(stem, enclitic) if the form ends in a separable enclitic, else (f, '').

    The length guard is what keeps a word that merely ends in these letters from
    being torn apart: `usque`, `namque`, `itaque` and `quoque` are words in their
    own right, not a host plus an enclitic."""
    for name, spelling in ENCLITIC_SPELLINGS:
        if not f.endswith(spelling): continue
        # The first spelling that matches decides, whether or not it splits.
        # Falling through on a failed length guard let `namque` -- which is too
        # short to be split at `-que` -- be torn apart at `-ue` instead, giving
        # `namq` + `ve`.
        if len(f) > len(spelling) + 3:
            return f[:-len(spelling)], name
        break
    return f, ''


# ---------------------------------------------------------------- the schema
# morph_info is not free text. Every value is filled slots in one fixed order
# from one closed vocabulary per slot, and the schema is the one already in the
# shipped database: Whitaker's 1,955,715 Latin rows in `lemma_map`.
#
#   nominal      case number gender             acc s f
#   verbal    person number tense voice mood    3 p perf active ind
#   participle   case number gender tense voice mood
#                                               gen p pres active part
#
# Matching it is not deference to the incumbent. Our rows land in that same
# table and a reader tapping `regis` gets ours and theirs in one candidate list,
# so two renderings of one fact is the inconsistency this column already had,
# one level up. Their 32 tokens are what a reader of this app has learned to
# read.
#
# Whitaker has no token for a part of speech (bar `pron`), because everything it
# indexes inflects. It indexes no indeclinables at all -- ab, et, non, sed, cum,
# in, ad and the rest of the commonest words in Latin have no row. Those are
# ours alone, so `prep`, `conj`, `adv` and `interj` extend the vocabulary where
# nothing can collide, in the trailing position Whitaker puts `pron`.
#
# `enclitic` is the one slot Whitaker's rows never fill. A token like
# `ductoresque` gets two rows, one for the host and one for `que`, and nothing
# in the format told a consumer which was which -- their code had to guess from
# the lemma's spelling. The enclitic row now says so: "conj enclitic".
SLOT_ORDER = ('person', 'case', 'number', 'gender', 'tense', 'voice', 'mood',
              'category', 'clitic')
SLOT_VALUES = {
    # person and case share the leading position; no reading has both
    'person':   ('0', '1', '2', '3'),        # 0 = a form with no person (inf)
    'case':     ('nom', 'gen', 'dat', 'acc', 'abl', 'voc', 'loc'),
    'number':   ('s', 'p'),
    'gender':   ('m', 'f', 'n', 'c'),        # c = common, gender not determined
    'tense':    ('pres', 'impf', 'fut', 'perf', 'plup', 'futp'),
    'voice':    ('active', 'passive'),
    'mood':     ('ind', 'sub', 'inf', 'imp', 'part'),
    'category': ('pron', 'prep', 'conj', 'adv', 'interj'),
    'clitic':   ('enclitic',),
}
ENCLITIC_MORPH = 'conj enclitic'            # what every -que / -ve row reads

def render_morph(slots):
    """One reading -> its string. The only place a value is ever built.

    Rejects a value outside its slot's vocabulary rather than passing it
    through: a typo in a paradigm table would otherwise ship as morphology to
    1.5M rows and read as plausible."""
    parts = []
    for slot in SLOT_ORDER:
        v = slots.get(slot)
        if not v: continue
        if v not in SLOT_VALUES[slot]:
            raise ValueError(f"{v!r} is not a {slot}: {SLOT_VALUES[slot]}")
        parts.append(v)
    return ' '.join(parts)

def parse_reading(text):
    """A rendered reading back into its slots, by position.

    The schema is positional and every slot vocabulary is disjoint, so a value
    can be read back without ambiguity. Used to compare two readings."""
    out, i = {}, 0
    for token in text.split():
        while i < len(SLOT_ORDER):
            slot = SLOT_ORDER[i]; i += 1
            if token in SLOT_VALUES[slot]:
                out[slot] = token; break
    return out

def merge_morph(*values):
    """Combine rendered cells, dropping any reading another one already covers.

    A reading that states strictly less than another in the same cell is noise:
    `arma` read "acc p n|n", where the bare `n` is the fallback for "we know only
    the gender" sitting next to a reading that names the case and number too. The
    alternatives in a cell are meant to be genuine alternatives."""
    seen = {}
    for v in values:
        for r in (v or '').split('|'):
            if r: seen.setdefault(r, parse_reading(r))
    keep = [r for r, d in seen.items()
            if not any(o != r and d.items() < seen[o].items() for o in seen)]
    return '|'.join(sorted(keep))

def render_readings(readings):
    """Several readings of one form -> the morph_info cell.

    A form is often several things at once and the schema enumerates them in
    full rather than blurring the slot: `portae` is dative singular, genitive
    singular, locative singular, nominative plural or vocative plural, and
    Whitaker writes all five. Collapsing that into one underspecified reading
    ("s/p gen/dat/nom/voc") would also admit `nom s` and `gen p`, which -ae
    never is.

    Sorted, so a rebuild is byte-identical and the cell reads the way the
    existing 1.9M rows do."""
    return merge_morph(*(render_morph(r) for r in readings if r))


# ---------------------------------------------------------------- readings
def _f(person, number, tense, voice='active', mood='ind'):
    """A finite verb reading."""
    return {'person': person, 'number': number, 'tense': tense,
            'voice': voice, 'mood': mood}

def _nom(*cases):
    """Nominal readings from (case, number[, gender]) triples."""
    out = []
    for c in cases:
        r = {'case': c[0], 'number': c[1]}
        if len(c) > 2: r['gender'] = c[2]
        out.append(r)
    return out

def _part(tense, voice, *cases):
    """Participle readings: nominal, plus tense, voice and mood."""
    out = []
    for r in _nom(*cases):
        r.update(tense=tense, voice=voice, mood='part')
        out.append(r)
    return out


# ---------------------------------------------------------------- noun paradigms
# genitive ending -> (declension, [(ending, [every reading of that ending])]).
#
# The endings are exactly the set this has always generated: labelling a form is
# a change to what `morph_info` says about it, not to which forms exist. Where an
# ending is several things at once every reading is kept, because collapsing them
# into one underspecified blur ("s/p gen/dat/nom") asserts combinations the
# ending never has.
#
# No locative: it survives only for place names and a handful of nouns (Romae,
# domi), so generating one for every noun names a case the word does not have.
NOUN = {
    'ae':   [('a',    _nom(('abl','s'), ('nom','s'), ('voc','s'))),       # 1st: porta, ae
             ('ae',   _nom(('dat','s'), ('gen','s'), ('nom','p'), ('voc','p'))),
             ('am',   _nom(('acc','s'))),
             ('as',   _nom(('acc','p'))),
             ('arum', _nom(('gen','p'))),
             ('is',   _nom(('abl','p'), ('dat','p')))],
    # The nominative is the headword and is indexed as such; -us, -er and the
    # vocative -e are emitted only for the headword that actually ends that
    # way (see NOM_ONLY_IF), because a table that gave every stem all three
    # made `populer`, `agrer`, `librus` and `puere` -- 2,610 bogus rows -- and
    # `uirus` as a form of *vir* competing with *virus*.
    'i':    [('us',   _nom(('nom','s'))),                                 # 2nd: servus, i
             ('i',    _nom(('gen','s'), ('nom','p'), ('voc','p'))),
             ('o',    _nom(('abl','s'), ('dat','s'))),
             # the table carried 'um' twice, once for the masculine accusative
             # and once for the neuter; as a set the repeat was invisible, as
             # readings they are separate entries on the one ending
             ('um',   _nom(('acc','s'), ('nom','s','n'), ('voc','s','n'))),
             ('e',    _nom(('voc','s'))),
             ('os',   _nom(('acc','p'))),
             ('orum', _nom(('gen','p'))),
             ('is',   _nom(('abl','p'), ('dat','p'))),
             ('er',   _nom(('nom','s'), ('voc','s')))],
    # A neuter declines differently in both the second and the third: its
    # nominative, accusative and vocative are one form and its plural is -a. The
    # masculine tables gave `bellum` the forms `belle`, `beller` and `bellos`,
    # and a `belli` claiming to be a nominative plural.
    'i-n':  [('um',   _nom(('nom','s','n'), ('acc','s','n'), ('voc','s','n'))),  # 2nd n: bellum, i
             ('i',    _nom(('gen','s'))),
             ('o',    _nom(('dat','s'), ('abl','s'))),
             ('a',    _nom(('nom','p','n'), ('acc','p','n'), ('voc','p','n'))),
             ('orum', _nom(('gen','p'))),
             ('is',   _nom(('dat','p'), ('abl','p')))],
    # -ium is the i-stem genitive plural (urbium, montium, civium, marium) and
    # a consonant stem never has it; giving `rex` a `regium` put a bogus form
    # of *rex* beside the real *regius*. The i-stem endings live in
    # I_STEM_EXTRA and are added only where `is_i_stem` says so.
    'is-n': [('is',   _nom(('gen','s'))),                                 # 3rd n: nomen, inis
             ('i',    _nom(('dat','s'))),
             ('e',    _nom(('abl','s'))),
             ('a',    _nom(('nom','p','n'), ('acc','p','n'), ('voc','p','n'))),
             ('um',   _nom(('gen','p'))),
             ('ibus', _nom(('dat','p'), ('abl','p')))],
    # The dative singular was missing outright: `regi`, `patri`, `urbi`,
    # `homini` were never generated for any consonant-stem noun.
    'is':   [('is',   _nom(('gen','s'))),                                 # 3rd: rex, regis
             ('i',    _nom(('dat','s'))),
             ('em',   _nom(('acc','s'))),
             ('e',    _nom(('abl','s'))),
             ('es',   _nom(('acc','p'), ('nom','p'), ('voc','p'))),
             ('um',   _nom(('gen','p'))),
             # no neuter -a here: a neuter third-declension noun uses 'is-n'
             # above, and `rex` is not one, so this ending only made `rega`
             ('ibus', _nom(('abl','p'), ('dat','p')))],
    'us':   [('us',   _nom(('gen','s'), ('nom','s'),                      # 4th: manus, us
                           ('acc','p'), ('nom','p'), ('voc','p'))),
             ('ui',   _nom(('dat','s'))),
             ('um',   _nom(('acc','s'))),
             ('uum',  _nom(('gen','p'))),
             ('ibus', _nom(('abl','p'), ('dat','p'))),
             ('u',    _nom(('abl','s')))],
    'ei':   [('es',   _nom(('nom','s'), ('voc','s'),                      # 5th: res, ei
                           ('acc','p'), ('nom','p'), ('voc','p'))),
             ('ei',   _nom(('dat','s'), ('gen','s'))),
             ('em',   _nom(('acc','s'))),
             ('e',    _nom(('abl','s'))),
             ('erum', _nom(('gen','p'))),
             ('ebus', _nom(('abl','p'), ('dat','p')))],
}
# Endings that only exist where the headword itself shows them: the stem plus
# `us` IS the headword `servus`, and `ager` is never `agrus` or `agrer`.
# 'same': stem + ending must BE the headword; otherwise the headword must end
# in the named letters (the vocative -e belongs to -us nouns only).
NOM_ONLY_IF = {('i', 'us'): 'same', ('i', 'er'): 'same', ('i', 'e'): 'us'}
# Endings that belong to i-stems alone: the genitive plural in -ium, the
# accusative plural in -is (civis, hostis), the ablative in -i (igni, mari,
# and every third-declension adjective: felici), the neuter plural in -ia.
I_STEM_EXTRA = {
    'is':   [('ium', _nom(('gen','p'))), ('is', _nom(('acc','p'))), ('i', _nom(('abl','s')))],
    'is-n': [('ium', _nom(('gen','p'))), ('i', _nom(('abl','s'))),
             ('ia', _nom(('nom','p','n'), ('acc','p','n'), ('voc','p','n')))],
}
VOWELS = 'aeiouy'

def is_i_stem(head, stem, key):
    """Third-declension i-stem: parisyllabic in -is/-es, a monosyllable whose stem
    ends in two consonants (urbs, mons, ars, nox), or a neuter in -e, -al, -ar."""
    h = fold(head)
    if key == 'is-n':
        return h.endswith(('e', 'al', 'ar'))
    if h.endswith(('is', 'es')) and stem == h[:-2]:
        return True
    if len(stem) >= 2 and stem[-1] not in VOWELS and stem[-2] not in VOWELS \
            and sum(c in VOWELS for c in h) <= 1:
        return True
    return False

# ------------------------------------------------------------ adjective paradigm
# L&S cites a first/second-declension adjective by its three nominatives --
# "nemorosus, a, um" -- and prints no genitive, so `_noun_stem_and_key` finds
# nothing and the entry declines not at all. 9,050 entries are in that state, and
# an adjective inflects for three genders, so this is the largest block of
# missing forms in the package.
#
# Fired only on a headword ending in `-us`: that is 8,635 of the 9,050, and the
# remainder are odd shapes whose stem cannot be read off the citation. The stem
# must be at least three letters, because a one-letter stem from a single-letter
# entry generates `cum`, `si`, `de`, `te` and `eo` and hangs the commonest words
# in Latin on the letter `c` -- the same trap `_noun_stem_and_key` guards with
# "Spāco, cūs".
ADJ_MIN_STEM = 3
ADJ_PARADIGM = [
    ('us',   [{'case':'nom','number':'s','gender':'m'},
              {'case':'voc','number':'s','gender':'m'}]),
    ('i',    [{'case':'gen','number':'s','gender':'m'}, {'case':'gen','number':'s','gender':'n'},
              {'case':'nom','number':'p','gender':'m'}, {'case':'voc','number':'p','gender':'m'}]),
    # A first/second-declension adjective forms its adverb from the same stem,
    # and the treebanks lemmatise that adverb to the adjective: `longe` to
    # *longus*, `vero` to *verus*, `primum` to *primus*. The form really is both,
    # so both readings are given -- without the adverb these were the largest
    # remaining class of wrong readings in the package.
    ('o',    [{'case':'dat','number':'s','gender':'m'}, {'case':'dat','number':'s','gender':'n'},
              {'case':'abl','number':'s','gender':'m'}, {'case':'abl','number':'s','gender':'n'},
              {'category':'adv'}]),
    # -um is also the contracted genitive plural, which verse uses constantly:
    # `magnanimum` for magnanimorum.
    ('um',   [{'case':'acc','number':'s','gender':'m'}, {'case':'nom','number':'s','gender':'n'},
              {'case':'acc','number':'s','gender':'n'}, {'case':'voc','number':'s','gender':'n'},
              {'case':'gen','number':'p','gender':'m'}, {'case':'gen','number':'p','gender':'n'},
              {'category':'adv'}]),
    ('e',    [{'case':'voc','number':'s','gender':'m'}, {'category':'adv'}]),
    ('os',   [{'case':'acc','number':'p','gender':'m'}]),
    ('orum', [{'case':'gen','number':'p','gender':'m'}, {'case':'gen','number':'p','gender':'n'}]),
    ('is',   [{'case':'dat','number':'p'}, {'case':'abl','number':'p'}]),
    ('a',    [{'case':'nom','number':'s','gender':'f'}, {'case':'abl','number':'s','gender':'f'},
              {'case':'voc','number':'s','gender':'f'},
              {'case':'nom','number':'p','gender':'n'}, {'case':'acc','number':'p','gender':'n'},
              {'case':'voc','number':'p','gender':'n'}]),
    ('ae',   [{'case':'gen','number':'s','gender':'f'}, {'case':'dat','number':'s','gender':'f'},
              {'case':'nom','number':'p','gender':'f'}, {'case':'voc','number':'p','gender':'f'}]),
    ('am',   [{'case':'acc','number':'s','gender':'f'}]),
    ('as',   [{'case':'acc','number':'p','gender':'f'}]),
    ('arum', [{'case':'gen','number':'p','gender':'f'}]),
]

# A two-termination third-declension adjective, cited "omnis, e, adj." L&S
# prints no genitive, so `_noun_stem_and_key` finds nothing and 1,970 of these
# declined not at all -- `omnis`, `fortis`, `gravis`, `brevis`, `mortalis`,
# `immanis` each produced their headword and nothing else.
#
# The accusative plural in -is is safe HERE, though not in the noun tables: for
# an i-stem adjective it is a real form, and this table only ever runs on an
# entry cited "X, e, adj.", so it cannot call `regis` an accusative plural of
# *rex*.
#
# The neuter singular and the comparative neuter double as the adverb -- `facile`
# "easily", `facilius` "more easily" -- exactly as -e and -o do for the
# first/second declension.
ADJ3_PARADIGM = [
    ('is',   [{'case':'nom','number':'s','gender':'m'}, {'case':'nom','number':'s','gender':'f'},
              {'case':'gen','number':'s'},
              {'case':'acc','number':'p','gender':'m'}, {'case':'acc','number':'p','gender':'f'}]),
    ('e',    [{'case':'nom','number':'s','gender':'n'}, {'case':'acc','number':'s','gender':'n'},
              {'case':'voc','number':'s','gender':'n'}, {'case':'abl','number':'s'},
              {'category':'adv'}]),
    ('iter', [{'category':'adv'}]),
    ('em',   [{'case':'acc','number':'s','gender':'m'}, {'case':'acc','number':'s','gender':'f'}]),
    ('i',    [{'case':'dat','number':'s'}, {'case':'abl','number':'s'}]),
    ('es',   [{'case':'nom','number':'p','gender':'m'}, {'case':'nom','number':'p','gender':'f'},
              {'case':'acc','number':'p','gender':'m'}, {'case':'acc','number':'p','gender':'f'},
              {'case':'voc','number':'p','gender':'m'}, {'case':'voc','number':'p','gender':'f'}]),
    ('ia',   [{'case':'nom','number':'p','gender':'n'}, {'case':'acc','number':'p','gender':'n'},
              {'case':'voc','number':'p','gender':'n'}]),
    ('ium',  [{'case':'gen','number':'p'}]),
    ('ibus', [{'case':'dat','number':'p'}, {'case':'abl','number':'p'}]),
    # the comparative: Whitaker has no degree token, so it reads as the case
    # and gender it is, exactly as `fortior` does in the 1.96M rows beside it
    ('ior',  [{'case':'nom','number':'s','gender':'m'},
              {'case':'nom','number':'s','gender':'f'}]),
    ('ius',  [{'case':'nom','number':'s','gender':'n'},
              {'case':'acc','number':'s','gender':'n'},
              {'category':'adv'}]),
]
# "omnis, e" -- the second citation token is the neuter nominative
ADJ3_CITATION = re.compile(r'^[^,]+,\s*e\s*,')

# ---------------------------------------------------------------- verb paradigms
# L&S prints a verb's principal parts in the headword line -- "amo, avi, atum,
# 1" -- and they are what the paradigm needs, because outside the first
# conjugation the perfect is not predictable from the present: dico makes dixi,
# moneo monui, rego rexi. Endings are grouped by the STEM they attach to, and a
# stem the entry does not print generates nothing rather than being invented.
#
# This replaces one table applied to the present stem for every conjugation,
# which produced `monees`, `moneet` and `monei` for moneo, and read the third
# conjugation's present -it as a perfect, so `dicit` was "3 s perf active ind".
def _fin(person, number, tense, voice='active', mood='ind'):
    return [{'person': person, 'number': number, 'tense': tense,
             'voice': voice, 'mood': mood}]

def _present(pres, thematic, fut, subj, imp2s, imp2p, passive):
    """Endings on the present stem for one conjugation."""
    P = (('1','s'), ('2','s'), ('3','s'), ('1','p'), ('2','p'), ('3','p'))
    out = []
    for e, r in zip(pres, P): out.append((e, _fin(r[0], r[1], 'pres')))
    for e, r in zip((thematic+'bam', thematic+'bas', thematic+'bat',
                     thematic+'bamus', thematic+'batis', thematic+'bant'), P):
        out.append((e, _fin(r[0], r[1], 'impf')))
    for e, r in zip(fut, P): out.append((e, _fin(r[0], r[1], 'fut')))
    for e, r in zip(subj, P): out.append((e, _fin(r[0], r[1], 'pres', mood='sub')))
    for e, r in zip(passive, P): out.append((e, _fin(r[0], r[1], 'pres', voice='passive')))
    out += [(imp2s, _fin('2', 's', 'pres', mood='imp')),
            (imp2p, _fin('2', 'p', 'pres', mood='imp')),
            (thematic + 'ns', _part('pres', 'active', ('nom','s'), ('voc','s'), ('acc','s','n'))),
            (thematic + 'ntis', _part('pres', 'active', ('gen','s'))),
            (thematic + 'ndi', _part('fut', 'passive', ('gen','s','m'), ('gen','s','n'),
                                     ('nom','p','m'), ('voc','p','m'))),
            (thematic + 'ndum', _part('fut', 'passive', ('acc','s','m'), ('acc','s','n'),
                                      ('nom','s','n'), ('voc','s','n')))]
    return out

PRESENT = {
    '1': _present(('o','as','at','amus','atis','ant'), 'a',
                  ('abo','abis','abit','abimus','abitis','abunt'),
                  ('em','es','et','emus','etis','ent'), 'a', 'ate',
                  ('or','aris','atur','amur','amini','antur'))
         + [('are', [{'person':'0','tense':'pres','voice':'active','mood':'inf'},
                     {'person':'2','number':'s','tense':'pres','voice':'passive','mood':'ind'},
                     {'person':'2','number':'s','tense':'pres','voice':'passive','mood':'imp'}]),
            ('ari', [{'person':'0','tense':'pres','voice':'passive','mood':'inf'}])],
    '2': _present(('eo','es','et','emus','etis','ent'), 'e',
                  ('ebo','ebis','ebit','ebimus','ebitis','ebunt'),
                  ('eam','eas','eat','eamus','eatis','eant'), 'e', 'ete',
                  ('eor','eris','etur','emur','emini','entur'))
         + [('ere', [{'person':'0','tense':'pres','voice':'active','mood':'inf'},
                     {'person':'2','number':'s','tense':'pres','voice':'passive','mood':'ind'},
                     {'person':'2','number':'s','tense':'pres','voice':'passive','mood':'imp'}]),
            ('eri', [{'person':'0','tense':'pres','voice':'passive','mood':'inf'}])],
    # The third conjugation is why the table had to be split: its present is
    # -is/-it where the second's is -es/-et, and its FUTURE is -es/-et, so one
    # shared table read every third-conjugation present as something else.
    '3': _present(('o','is','it','imus','itis','unt'), 'e',
                  ('am','es','et','emus','etis','ent'),
                  ('am','as','at','amus','atis','ant'), 'e', 'ite',
                  ('or','eris','itur','imur','imini','untur'))
         + [('ere', [{'person':'0','tense':'pres','voice':'active','mood':'inf'},
                     {'person':'2','number':'s','tense':'pres','voice':'passive','mood':'imp'}]),
            ('i',   [{'person':'0','tense':'pres','voice':'passive','mood':'inf'}])],
    # capio, capis, capit, capimus, capitis, capiunt -- the present of a
    # third-conjugation -io verb follows the fourth, but its infinitive is -ere
    # and its imperative -e. Without it the stem came out `capi` and every
    # present was doubled: `capiit` for capit, and `capit` itself was absent.
    '3io': _present(('io','is','it','imus','itis','iunt'), 'ie',
                    ('iam','ies','iet','iemus','ietis','ient'),
                    ('iam','ias','iat','iamus','iatis','iant'), 'e', 'ite',
                    ('ior','eris','itur','imur','imini','iuntur'))
         + [('ere', [{'person':'0','tense':'pres','voice':'active','mood':'inf'},
                     {'person':'2','number':'s','tense':'pres','voice':'passive','mood':'imp'}]),
            ('i',   [{'person':'0','tense':'pres','voice':'passive','mood':'inf'}])],
    '4': _present(('io','is','it','imus','itis','iunt'), 'ie',
                  ('iam','ies','iet','iemus','ietis','ient'),
                  ('iam','ias','iat','iamus','iatis','iant'), 'i', 'ite',
                  ('ior','iris','itur','imur','imini','iuntur'))
         + [('ire', [{'person':'0','tense':'pres','voice':'active','mood':'inf'},
                     {'person':'2','number':'s','tense':'pres','voice':'passive','mood':'imp'}]),
            ('iri', [{'person':'0','tense':'pres','voice':'passive','mood':'inf'}])],
}

# On the perfect stem, which is the same for every conjugation once the stem is
# known: amav-, monu-, dix-, audiv-.
PERFECT = ([(e, _fin(r[0], r[1], 'perf'))
            for e, r in zip(('i','isti','it','imus','istis','erunt'),
                            (('1','s'),('2','s'),('3','s'),('1','p'),('2','p'),('3','p')))]
         + [(e, _fin(r[0], r[1], 'plup'))
            for e, r in zip(('eram','eras','erat','eramus','eratis','erant'),
                            (('1','s'),('2','s'),('3','s'),('1','p'),('2','p'),('3','p')))]
         + [('ero', _fin('1','s','futp')),
            # these five are the future perfect and the perfect subjunctive at
            # once -- `praestiterit`, `habuerint` -- and naming only the first
            # denied the other
            ('erit', _fin('3','s','futp') + _fin('3','s','perf', mood='sub')),
            ('erint', _fin('3','p','futp') + _fin('3','p','perf', mood='sub')),
            ('erimus', _fin('1','p','futp') + _fin('1','p','perf', mood='sub')),
            ('eritis', _fin('2','p','futp') + _fin('2','p','perf', mood='sub')),
            ('erim', _fin('1','s','perf', mood='sub')),
            ('eris', _fin('2','s','futp') + _fin('2','s','perf', mood='sub')),
            ('issem', _fin('1','s','plup', mood='sub')),
            ('isset', _fin('3','s','plup', mood='sub')),
            ('issent', _fin('3','p','plup', mood='sub')),
            ('isse', [{'person':'0','tense':'perf','voice':'active','mood':'inf'}]),
            ('ere', _fin('3','p','perf'))])

# On the supine stem: amat-, monit-, dict-, audit-. The perfect passive
# participle, declining like a first/second-declension adjective.
SUPINE = [(e, _part('perf', 'passive', *cases)) for e, cases in (
    ('us',   (('nom','s','m'),)),
    ('um',   (('acc','s','m'), ('acc','s','n'), ('nom','s','n'), ('voc','s','n'))),
    ('a',    (('nom','s','f'), ('abl','s','f'), ('nom','p','n'), ('acc','p','n'))),
    ('i',    (('gen','s','m'), ('gen','s','n'), ('nom','p','m'), ('voc','p','m'))),
    ('ae',   (('gen','s','f'), ('dat','s','f'), ('nom','p','f'), ('voc','p','f'))),
    ('o',    (('dat','s','m'), ('dat','s','n'), ('abl','s','m'), ('abl','s','n'))),
    ('orum', (('gen','p','m'), ('gen','p','n'))),
    ('arum', (('gen','p','f'),)),
    ('os',   (('acc','p','m'),)),
    ('as',   (('acc','p','f'),)),
    ('is',   (('dat','p'), ('abl','p'))),
)] + [(e, _part('fut', 'active', *cases)) for e, cases in (
    ('urus', (('nom','s','m'),)),
    ('urum', (('acc','s','m'), ('acc','s','n'), ('nom','s','n'))),
    ('ura',  (('nom','s','f'),)),
)]

# "oportet, ui, 2, v. impers." -- an impersonal verb has no first person, and
# L&S cites it by its third singular. Treating that as a first singular and
# adding endings to it produced `oporteteam`, `oportetebam`, `decetebam`: 39 dead
# forms for each of 41 entries.
IMPERSONAL = re.compile(r'\bimpers\b')
# "miseror, atus, 1, v. dep." -- a deponent has passive forms with active
# meaning. It takes the passive-form endings only, and the treebanks tag its
# voice as neither active nor passive, so the reading states no voice.
DEPONENT = re.compile(r'\bdep\b')

def verb_stems(head_tokens, h, conj, impersonal=False):
    """(present, perfect, supine) stems from the principal parts; None if absent.

    L&S abbreviates a principal part that shares the headword's stem -- "amo,
    avi, atum" is amAVi and amATum -- while "dico, dixi, dictum" prints them in
    full. They are told apart the way the declensions do it: whether the printed
    part starts like the headword."""
    # A deponent's headword ends in -or, and the second and fourth conjugations'
    # in -eor / -ior: `vereor` is vere-, not vereor-, or every form it generated
    # (`uereoreo`, `uereores`) was a word that does not exist.
    pres = (r'(at|et|it)$' if impersonal
            else {'2': r'e(o|or)$', '4': r'i(o|or)$', '3io': r'i(o|or)$'}.get(conj, r'(or|o)$'))
    pres = re.sub(pres, '', h) or h
    def cut(part, suffix):
        if not part or not part.replace('-', '').isalpha(): return None
        f = fold(part)
        if not f.endswith(suffix) or len(f) <= len(suffix): return None
        body = f[:-len(suffix)]
        # L&S prints a principal part in full when it shares the headword's
        # opening, and abbreviates it to its ending otherwise. The opening test
        # alone misses the perfects that change their vowel -- capio makes cepi,
        # facio feci, rego rexi -- which were being glued on as `capcepi`. A body
        # of three letters or more starting with a consonant is a stem in its
        # own right; L&S's abbreviations (avi, ivi, ui, atum, itum, ertum) are
        # shorter than that or start with a vowel.
        if f[:2] == h[:2] or (len(body) >= 3 and body[0] not in 'aeiouy'):
            return body
        # An abbreviated part names the END of the word and may overlap the stem
        # it attaches to: "statuo, ui" is statuI, not statuUi, because the stem
        # already ends in -u. Join on the longest overlap.
        for k in range(min(len(pres), len(f)), 0, -1):
            if pres[-k:] == f[:k]:
                return (pres + f[k:])[:-len(suffix)]
        return (pres + f)[:-len(suffix)]
    perf = sup = None
    for t in head_tokens[1:4]:
        f = fold(t)
        if perf is None and f.endswith('i'): perf = cut(t, 'i')
        elif sup is None and f.endswith('um'): sup = cut(t, 'um')
        # A deponent has no active perfect and L&S prints its participle
        # instead: "miseror, atus, 1, v. dep." The participle stem is what the
        # supine endings attach to.
        elif sup is None and f.endswith('us'): sup = cut(t, 'us')
    return pres, perf, sup


# `^` is L&S's breve mark and sits inside the word -- "ăcădēmī^a", "Ā^drastus".
# Leaving it out of the class truncated the headword at the mark, so `HEAD` found
# no comma after it and 595 entries declined not at all. `fold` strips it, so the
# stem is unaffected.
HEAD = re.compile(r'^\s*([A-Za-zÀ-ɏ\^\-]+)\s*,\s*([A-Za-zÀ-ɏ\^]+)', re.U)
# L&S marks conjugation with a number before "v.": "amo, avi, atum, 1, v. a."
CONJ = re.compile(r',\s*([1-4])\s*(?:,\s*v\.|\(|,|\.|\s)')

def _join_abbrev(h, g):
    """The full genitive from a headword and L&S's abbreviated genitive.

    The abbreviation names the END of the word, starting where it diverges from
    the headword: "homo, inis" is hom-inis, "pater, tris" is pa-tris, "corpus,
    oris" is corp-oris, "liber, bri" is li-bri, "filius, ii" is fil-ii. So the
    join point is the first position from the right where the headword's
    remaining tail begins with the same letter as the abbreviation, or where
    both begin with a vowel (the vowel is what changed). Slicing two letters
    off the headword regardless gave `hoinis`, `pattris` and `filiusi`."""
    # A same-letter join within three letters of the end comes first: "pa-tris",
    # "li-bri", "fil-ii", "vigintivi-ri". Folded forms write v as u, so the vowel
    # rule alone would read "vigintivir, viri" as vigintiu-uiri.
    # Only for a headword ending in a consonant: "libido, inis" has an i three
    # letters from its end and is libid-inis, not lib-inis.
    if h[-1] not in VOWELS:
        for k in range(1, min(4, len(h))):
            if h[-k] == g[0] and not re.search(r'(.)\1\1', h[:-k] + g):
                return h[:-k] + g
    for k in range(1, len(h)):
        y = h[-k:]
        if y[0] == g[0] or (y[0] in VOWELS and g[0] in VOWELS):
            cand = h[:-k] + g
            if re.search(r'(.)\1\1', cand):
                continue                      # a triple letter: wrong split
            return cand
    return h[:-2] + g


# Second tokens of a headword line that are grammar, not a genitive. Folded,
# so "conj." is `coni` and "adj." is `adi`.
NOT_A_GENITIVE = {'coni', 'adi', 'adv', 'praep', 'prep', 'pron', 'interi', 'num', 'subst',
                  'indecl', 'part', 'comm', 'dep', 'impers', 'irreg', 'defect', 'freq',
                  'inch', 'intens', 'desid', 'sup', 'comp', 'gen', 'dat', 'acc', 'abl',
                  'nom', 'voc', 'plur', 'sing', 'fem', 'masc', 'neutr', 'arch', 'poet',
                  'class', 'also', 'and', 'or', 'the', 'see', 'temp', 'distr', 'ordin',
                  'card', 'rel', 'interrog', 'demonstr', 'indef', 'pers', 'poss', 'refl'}

def _noun_stem_and_key(head, gen):
    """(stem, paradigm key) from the headword and its genitive, or (None, None)."""
    h, g = fold(head), fold(gen)
    if not g: return None, None
    if g == 'ae':                 return (h[:-1] if h.endswith('a') else h), 'ae'
    if g == 'i':                  return (re.sub(r'(us|um|er|os)$', '', h) or h), 'i'
    # L&S often prints the genitive in full ("vir, viri"), but for compounds it
    # abbreviates ("vigintivir, viri" means vigintiviri). Taking the short form
    # literally makes the compound claim the simple word's whole paradigm --
    # vigintivir would own virum, viri, virorum.
    # ...and "ager, gri" / "puer, eri" abbreviate without being much shorter:
    # for a headword in -r, a genitive that does not open like it is
    # abbreviated too. Only for -r: folded, "conj" is `coni` and "adj" is
    # `adi`, and reading those as abbreviated genitives declined `atque` as
    # atqcon-i.
    abbreviated = len(g) < len(h) - 1 or (h.endswith('r') and not g.startswith(h[:2]))
    if g in NOT_A_GENITIVE:
        return None, None
    # 5th declension first: `rei` also ends in -i, and the -i test below would
    # otherwise claim it and inflect res as a 2nd-declension noun -- generating
    # reus/reum/reo (real forms of *reus*, 'defendant') and never rem/rebus/rerum.
    # Only a headword in -es is fifth declension: "deus, dei" is a second-
    # declension noun whose genitive happens to end in -ei, and reading it as
    # fifth gave `des`, `dem`, `derum`.
    if g.endswith('ei') and len(g) > 2 and not abbreviated and h.endswith('es'):
        return g[:-2], 'ei'                                     # res, rei -> r
    # L&S abbreviates the fifth declension's genitive to just "ei", which is too
    # short for the test above: "dies, ei" was read as a second-declension
    # genitive and declined with the stem `dies`, giving `diese`, `dieser`,
    # `diesorum`. A headword in -es with that genitive is fifth declension.
    if g == 'ei' and h.endswith('es') and len(h) > 3:
        return h[:-2], 'ei'                                     # dies, ei -> di
    # The same two letters after a Greek name in -eus are its second-declension
    # genitive: Adoneus, Adonei.
    if g == 'ei' and h.endswith('eus') and len(h) > 4:
        return h[:-2], 'i'                                      # Adoneus, ei -> adone
    # An abbreviated genitive is joined to the headword (`_join_abbrev`); the
    # old rule kept the whole headword as the stem, so "filius, ii" declined as
    # filius-i and "liber, bri" as liber-i, and the real forms never existed.
    if g.endswith('i') and len(g) > 1 and (abbreviated or g[:2] == h[:2]):
        return (_join_abbrev(h, g)[:-1] if abbreviated else g[:-1]), 'i'
    if g.endswith('ae') and len(g) > 2 and (abbreviated or g[:2] == h[:2]):
        return (_join_abbrev(h, g)[:-2] if abbreviated else g[:-2]), 'ae'
    if g == 'us':                 return (re.sub(r'us$', '', h) or h), 'us'
    # "civis, is", "nubes, is", "mare, is": a bare -is genitive on a
    # parisyllabic headword. These 1,900 entries declined not at all.
    if g == 'is':
        if h.endswith(('is', 'es')) and len(h) > 3: return h[:-2], 'is'
        if h.endswith('e') and len(h) > 2: return h[:-1], 'is'
        return None, None
    # An abbreviated genitive names the END of the word, not the whole of it:
    # `Spāco, cūs` is Spa-cus. Slicing the printed form gives the stem `c`, which
    # then generates cum, cui and cibus -- common words belonging to other lemmas.
    if g.endswith('us') and len(g) > 2:
        return (_join_abbrev(h, g)[:-2] if abbreviated else g[:-2]), 'us'
    if g.endswith('is') and len(g) > 2:
        # L&S abbreviates the genitive when it shares a stem: "corpus, oris" is
        # corpOris, so the real stem is corpor-, not or-. Detect that by whether
        # the printed genitive starts like the headword.
        if not g.startswith(h[:2]):
            g = _join_abbrev(h, g)                              # corpus + oris -> corporis
        return g[:-2], 'is'                                     # rex, regis -> reg
    return None, None

# ------------------------------------------------------------ treebank postags
# Perseus annotates every treebank word with a nine-character positional tag --
# `v3spip---` is the third singular present indicative passive of *for*. The
# package used to read `form` and `lemma` off those <word> elements and drop the
# tag, then write the word "treebank" into the morphology column; the morphology
# was in the source all along.
#
# Tag positions in order. A value with no token in the schema is skipped rather
# than approximated -- Greek's aorist and medio-passive, and the deponent voice,
# have nothing to map onto, and a deponent is not really passive.
POSTAG_SLOTS = [
    # only the indeclinable classes and `pron` become a token; everything else
    # that the tagset can say here, the case and tense slots say better
    ('category', {'p':'pron','d':'adv','r':'prep','c':'conj','i':'interj'}),
    ('person', {'1':'1','2':'2','3':'3'}),
    ('number', {'s':'s','p':'p'}),
    ('tense',  {'p':'pres','i':'impf','r':'perf','l':'plup','t':'futp','f':'fut'}),
    ('mood',   {'i':'ind','s':'sub','n':'inf','m':'imp','p':'part'}),
    ('voice',  {'a':'active','p':'passive'}),
    ('gender', {'m':'m','f':'f','n':'n','c':'c'}),
    ('case',   {'n':'nom','g':'gen','d':'dat','a':'acc','b':'abl','v':'voc','l':'loc'}),
    ('degree', {}),          # no token in the schema; Whitaker has none either
]

def postag_slots(tag):
    """Perseus postag -> one reading. Unknown characters are skipped rather than
    guessed at: the Greek treebanks use values the Latin tagset does not, and
    inventing a reading for one is worse than leaving the slot out."""
    out = {}
    for i, (slot, table) in enumerate(POSTAG_SLOTS):
        c = tag[i] if tag and i < len(tag) else '-'
        v = table.get(c)
        if v: out[slot] = v
    # An infinitive has no person and the tag leaves the slot empty; the schema
    # writes `0` there ("0 pres active inf"). Without this the same reading
    # arrives from the treebank and from the paradigm tables in two spellings,
    # and both end up in the cell.
    if out.get('mood') == 'inf' and 'person' not in out and 'case' not in out:
        out['person'] = '0'
    return out

def postag_morph(tag):
    """Perseus postag -> morph_info, through the one renderer."""
    return render_morph(postag_slots(tag))


# ----------------------------------------------------------- part of speech
# L&S prints the part of speech in the headword line, right after the inflection
# the paradigm needs: "porta, ae, f." is a feminine noun, "e-maculo, avi, atum,
# 1, v. a." a verb, "pertinenter, adv." an adverb. Reading it fills the `pos`
# slot for the ~35,000 forms whose paradigm the tables cannot build --
# indeclinables, third-declension nominatives, function words -- which otherwise
# ship with an empty morph_info.
#
# `v.` is the trap. It opens a verb entry ("v. a.", "v. dep. n.") and it is also
# the dictionary's abbreviation for "see" ("concitus, a, um, v. concieo"), which
# points AT a verb without being one. Only the first is matched: a subtype
# abbreviation has to follow.
POS_MARKERS = [
    # L&S's verb subtypes. The trailing period is optional because it writes
    # "v. a and n." without one; the match must still end at a word boundary
    # followed by space, comma or end, which is what keeps the cross-reference
    # "v. abicio" out -- `a` there is followed by `b`, not a boundary.
    (re.compile(r'\bv\.\s*(?:a|n|act|pass|dep|semidep|freq|inch|incoh|impers'
                r'|intens|desid|defect|irreg)\b\.?(?=[\s,]|$)'),
     {'pos': 'verb'}),
    (re.compile(r'\bP\.\s*a\.'),        {'pos': 'adj'}),      # participial adjective
    (re.compile(r'\bPart\.'),           {'pos': 'participle'}),
    (re.compile(r'\badj\.'),            {'pos': 'adj'}),
    (re.compile(r'\badv\.'),            {'pos': 'adv'}),
    (re.compile(r'\bprep\.'),           {'pos': 'prep'}),
    (re.compile(r'\bconj\.'),           {'pos': 'conj'}),
    (re.compile(r'\binterj\.'),         {'pos': 'interj'}),
    (re.compile(r'\bpron\.'),           {'pos': 'pron'}),
    (re.compile(r'\bnum\.'),            {'pos': 'num'}),
    (re.compile(r',\s*comm\.'),         {'pos': 'noun', 'gender': 'c'}),
    (re.compile(r',\s*m\.'),            {'pos': 'noun', 'gender': 'm'}),
    (re.compile(r',\s*f\.'),            {'pos': 'noun', 'gender': 'f'}),
    (re.compile(r',\s*n\.'),            {'pos': 'noun', 'gender': 'n'}),
]
# Consulted only when no marker above matched. L&S cites an adjective by its
# three nominatives -- "nemorosus, a, um" -- which is an inflection, not an
# abbreviation, so it cannot join the list above: it appears BEFORE the marker in
# "interdictus, a, um, Part.", and earliest-wins would call that participle an
# adjective.
ADJ_CITATION = re.compile(r',\s*a,\s*um\b')
# Only the headword line, not the definition: "adv." occurs freely in the prose
# of a noun entry, and the marker that counts is the one L&S prints first.
POS_WINDOW = 120

def strip_parens(text):
    """L&S interrupts the headword line with parenthetical variants and
    citations -- "bellum (ante-class. and poet. duel-lum), i, n." -- which hides
    the genitive from the declension parser and pushes the part-of-speech marker
    out of any fixed window. Twice, for the nested ones."""
    flat = re.sub(r'\s+', ' ', text)
    for _ in range(2):
        flat = re.sub(r'\([^()]*\)', ' ', flat)
    return re.sub(r'\s+', ' ', flat).strip()

def pos_from_entry(entry_text):
    """Every part of speech the L&S headword line names, earliest first.

    A word is often more than one: "inter, adv., and prep. with acc." is both,
    and "ne" is conjunction, adverb and interjection. Keeping only the first
    marker asserted one and denied the rest -- measured against the Perseus
    treebanks that was the single largest source of wrong readings, ~800 tokens
    of `inter`, `pro`, `ne`, `ubi`, `etiam` called adverbs when the annotator
    said preposition or conjunction.

    Returns [] when the entry names none, which is the honest answer for a
    cross-reference stub like "Naevianus, v. 2. Naevius, B."."""
    head = strip_parens(entry_text)[:POS_WINDOW]
    found = []
    for rx, slots in POS_MARKERS:
        m = rx.search(head)
        if m: found.append((m.start(), slots))
    if not found:
        return [{'pos': 'adj'}] if ADJ_CITATION.search(head) else []
    out, seen = [], set()
    for _, slots in sorted(found, key=lambda t: t[0]):
        if slots['pos'] in seen: continue
        seen.add(slots['pos']); out.append(dict(slots))
    return out


# L&S names a part of speech; the schema has a token for only some of them.
# Everything that inflects is described by its case and tense instead -- a noun
# row says "acc s f", never "noun".
CATEGORY_TOKEN = {'prep': 'prep', 'conj': 'conj', 'adv': 'adv', 'interj': 'interj'}
NOMINAL_POS = ('noun', 'adj', 'participle', 'pron', 'num')
# A genitive in -arum/-orum/-uum is a genitive PLURAL, so the entry is cited in
# the plural and its headword is a nominative plural: "divitiae, arum, f." is
# not a singular.
PLURAL_GENITIVE = re.compile(r'(arum|orum|uum)$')
# L&S cites a noun by its genitive and a GENDERED word by its three nominatives:
# "rex, regis, m." against "qui, quae, quod" and "bonus, a, um". Reading only the
# first two tokens confuses them, and `qui, quae` was declined as a
# first-declension noun with the stem `qu-`, which made `quae` a dative singular
# and `quas` an accusative plural of the relative pronoun. The third token
# separates them: a gender abbreviation ends in a period, a third nominative does
# not. Safe only with B2 already in place -- before it, this caught verbs whose
# third principal part is a bare word (`lego, legi, lectum`) and deleted their
# mapping without replacing it.
THIRD_NOMINATIVE = re.compile(r'^[A-Za-zÀ-ɏ]+$')

def forms_with_morph(headword, entry_text, limit=None, strict_gender=True,
                     pos_text=None):
    """{inflected form: morph_info}, for the paradigm this entry implies.

    Which forms this produces is unchanged: same headword, same declension and
    conjugation tests, same endings, same folding. What is new is that each form
    arrives with the reading of the paradigm slot that made it, because that slot
    is the only place the morphology is known -- once the endings are applied and
    collected, `portis` is a string and nothing downstream can recover that it is
    dative or ablative plural.

    A form can be several things at once and every reading is kept: within one
    paradigm (second-declension -i is genitive singular and nominative plural)
    and across the noun and verb passes."""
    out = {}
    h = fold(headword)
    if not h: return out
    def add(form, readings):
        out.setdefault(form, []).extend(readings)

    # The part of speech is read from the WHOLE entry, not the slice the
    # paradigm parser gets. L&S opens many entries with a parenthesis longer than
    # that slice, and the marker sits after it: `fero`, `video`, `jubeo`, `nego`
    # and `trado` were not recognised as verbs at all. Everything else here still
    # reads `entry_text`, so widening this cannot move the declension or the
    # conjugation test.
    poss = pos_from_entry(pos_text if pos_text is not None else entry_text)
    names = [q['pos'] for q in poss]
    # The citation tests read the whole entry too. L&S's parenthesis can run past
    # the slice the paradigm parser gets -- "fortis (archaic form FORCTIS,
    # Fragm. XII. Tab. ap. Fest. s. v. sanates" hides the ", e," that says this
    # is a third-declension adjective.
    citation = strip_parens(pos_text if pos_text is not None else entry_text)
    gender = next((q['gender'] for q in poss if q.get('gender')), None)
    # L&S interrupts the headword line with parenthetical variants and
    # citations -- "bellum (ante-class. and poet. duel-lum), i, n." and
    # "odor (odos), oris, m." -- and `HEAD` expects `word , word`, so the
    # parenthesis stopped those entries declining at all. Dropping it also keeps
    # a citation number out of the conjugation test.
    flat = strip_parens(entry_text)
    tokens = [t.strip() for t in flat.split(',')]

    def nominal(readings, number=None):
        """Fill in what the entry knows and the ending cannot."""
        done = []
        for r in readings:
            # An ending can carry a gender of its own -- second-declension
            # -um is the masculine accusative AND the neuter nominative. On a
            # masculine noun the neuter half is not a reading at all: `uirum`
            # and `equum` were claiming "nom s n". `c` is common gender, which
            # contradicts nothing, and an adjective inflects for every gender.
            #
            # `strict_gender` is off where the lemma has homographs, because the
            # entry's gender then speaks only for its own sense: the paradigm
            # behind `magnum` comes from the proper noun "Magnus, i, m.", and
            # its `m.` would deny the adjective *magnus, a, um* its real neuter.
            if (strict_gender and gender and gender != 'c' and 'adj' not in names
                    and r.get('gender') and r['gender'] != gender):
                continue
            r = dict(r)
            if number: r['number'] = number
            # An adjective inflects for all three genders, so the gender L&S
            # prints is a fact about the entry, not about the form.
            if gender and 'adj' not in names: r.setdefault('gender', gender)
            if 'pron' in names: r['category'] = 'pron'
            done.append(r)
            # A neuter's nominative, accusative and vocative are one form in
            # both numbers, so a neuter reading in any of the three is also the
            # other two.
            if r.get('gender') == 'n' and r.get('case') in ('nom', 'acc', 'voc'):
                for c in ('nom', 'acc', 'voc'):
                    if c != r['case']:
                        x = dict(r); x['case'] = c; done.append(x)
        return done

    declined = plural = False
    m = HEAD.match(flat)
    # B2: a verb entry is not a declension. "moneo, ui" and "dico, dixi" both
    # look like a headword and a genitive, and running them through the noun
    # tables produced `moneous`, `moneoorum` and `dixorum` -- and attached
    # nominal readings to real words belonging to the verb. Gated on the part of
    # speech, never on CONJ: only 37% of CONJ matches are verbs.
    # the FIRST word of the third token: L&S's parenthesis can run past the slice
    # this function is given, leaving `quod (old forms: nom. quei` unsplit
    # Both the second and the third token have to be bare words. "qui, quae,
    # quod" and "bonus, a, um" are; "species, ei (gen. sing. specie or specii,
    # Matius ap. Gell. 9, 14, 15" is not, and testing only the third token let an
    # unclosed parenthesis split into something that looked like one, blocking
    # the declension of a fifth-declension noun.
    three_gender = (len(tokens) > 2
                    and bool(THIRD_NOMINATIVE.match(tokens[1]))
                    and bool(THIRD_NOMINATIVE.match(tokens[2].split(' ')[0])))
    if m and 'verb' not in names and not three_gender:
        # A genitive in -arum/-orum/-uum is a genitive PLURAL, so the entry is
        # cited in the plural and its headword is not a singular. Read before the
        # declension is attempted, because the entries this matters most for are
        # the ones it cannot parse: `divitiae, arum, f.` has no singular and no
        # paradigm either.
        plural = bool(PLURAL_GENITIVE.search(fold(m.group(2))))
        stem, key = _noun_stem_and_key(m.group(1), m.group(2))
        if stem and key:
            declined = True
            if gender == 'n' and key + '-n' in NOUN: key += '-n'
            # The locative survives for place names and a handful of nouns, and
            # a capitalised headword is what L&S gives us to recognise one:
            # `Romae` is "at Rome". It is added as one more reading of a form
            # that already exists, so it cannot invent a word.
            proper = m.group(1)[:1].isupper()
            LOC = {'ae': 'ae', 'i': 'i'}.get(key)
            # a third-declension adjective ("felix, icis, adj.") is an i-stem
            # -- felici, felicia, felicium -- and its ablative doubles as the
            # adverb, as the -e of `omnis, e` does
            is_adj = 'adj' in names
            i_stem = is_adj or is_i_stem(m.group(1), stem, key)
            table = list(NOUN[key]) + (I_STEM_EXTRA.get(key, []) if i_stem else [])
            for e, readings in table[:limit]:
                need = NOM_ONLY_IF.get((key, e))
                if need == 'same' and stem + e != h:
                    continue
                if need and need != 'same' and not h.endswith(need):
                    continue
                if proper and e == LOC:
                    readings = list(readings) + [{'case': 'loc', 'number': 's'}]
                if is_adj and key == 'is' and e == 'e':
                    readings = list(readings) + [{'category': 'adv'}]
                add(stem + e, nominal(readings))
            # The headword is the nominative whatever else the tables make of
            # the same string: `civis` is the genitive singular AND the
            # nominative, `mare` the ablative AND the nominative. Where the
            # headword was already generated its nominative reading was lost.
            add(h, nominal([{'case': 'nom'}], number='p' if plural else 's'))
    # An adjective declines for all three genders; the readings below already
    # carry the gender, so they do not go through `nominal`, whose job is to add
    # the one the entry names.
    if not declined and h.endswith('us') and len(h) - 2 >= ADJ_MIN_STEM \
            and ADJ_CITATION.search(citation[:POS_WINDOW]):
        for e, readings in ADJ_PARADIGM[:limit]:
            add(h[:-2] + e, [dict(r) for r in readings])

    # B12: the conjugation number is read from the principal parts, but `CONJ`
    # also matches a citation -- "abactus, us, m. abigo" contains ", 4." -- so
    # 8,703 noun entries were generating a full verb paradigm. The part of speech
    # is what says this is a verb; the number only says which conjugation.
    # two-termination third-declension adjective: "omnis, e, adj."
    if (not declined and 'adj' in names and h.endswith('is') and len(h) - 2 >= ADJ_MIN_STEM
            and ADJ3_CITATION.match(citation)):
        for e, readings in ADJ3_PARADIGM[:limit]:
            add(h[:-2] + e, [dict(r) for r in readings])

    mc = CONJ.search(flat[:160])
    if mc and 'verb' in names:
        conj = mc.group(1)
        # a third-conjugation headword in -io (or a deponent in -ior) is the
        # mixed paradigm
        if conj == '3' and h.endswith(('io', 'ior')): conj = '3io'
        impersonal = bool(IMPERSONAL.search(flat[:200]))
        deponent = h.endswith('or') and bool(DEPONENT.search(flat[:200]))
        pres, perf, sup = verb_stems(tokens, h, conj, impersonal)
        for e, readings in PRESENT[conj][:limit]:
            if impersonal:
                # only the third person and the non-finite forms exist
                readings = [r for r in readings if r.get('person') in ('3', '0')]
                if not readings: continue
            if deponent:
                # passive in form, active in meaning: `moror` has `moratur`
                # and never `morat`, and its voice slot is left unstated
                readings = [{k: v for k, v in r.items() if k != 'voice'}
                            for r in readings if r.get('voice') == 'passive']
                if not readings: continue
            add(pres + e, readings)
        # A perfect stem the entry does not print generates no perfect forms;
        # building them on the present stem gave `monei` for monui and
        # `dicerunt` for dixerunt.
        if perf:
            for e, readings in PERFECT[:limit]:
                if impersonal:
                    readings = [r for r in readings if r.get('person') in ('3', '0')]
                    if not readings: continue
                add(perf + e, readings)
        if sup:
            for e, readings in SUPINE[:limit]:
                if deponent:
                    readings = [{k: v for k, v in r.items() if k != 'voice'} for r in readings]
                add(sup + e, readings)

    # What the headword itself is. A category is true of the word however it is
    # used, so it is stated whether or not the word also inflects: `adversus` is
    # an adverb AND a declined adjective.
    cats = [CATEGORY_TOKEN[n] for n in names if n in CATEGORY_TOKEN]
    if cats:
        add(h, [{'category': c} for c in cats])
    if h not in out:
        if ADJ_CITATION.search(citation[:POS_WINDOW]):
            # "nemorosus, a, um" cites the three nominatives in the order
            # masculine, feminine, neuter, so the headword is the masculine
            # nominative singular.
            add(h, nominal([{'case': 'nom', 'number': 's', 'gender': 'm'}]))
        elif any(n in NOMINAL_POS for n in names):
            # The entry names a noun but prints no genitive to decline it by, so
            # nothing says which case this form is. The gender is known, and so
            # is the number when the citation is a plural one.
            add(h, nominal([{'number': 'p'} if plural else {}]))
        elif 'verb' in names:
            # L&S cites a verb by its first singular present
            r = _f('1', 's', 'pres')
            if h.endswith('or') and DEPONENT.search(flat[:200]): r.pop('voice')
            add(h, [r])
    # The headword is always indexed, whether or not anything is known about it:
    # it is a form a reader meets. An entry that names no part of speech and
    # builds no paradigm -- a cross-reference stub like "Naevianus, v. 2.
    # Naevius, B." -- still gets its row, with an empty morph_info, which is what
    # the format expects for unknown. Dropping it here silently removed the
    # headword's -que and -ve rows from 3,546 entries.
    out.setdefault(h, [])

    # Fold at the boundary, not in the tables above.
    #
    # The stem is folded but the ending tables are written in conventional
    # orthography, so 'amo' + 'avit' produced `amavit` while a corpus token folds
    # to `amauit` -- a form that can never match anything. That was 20,835 dead
    # forms. Folding here makes "every generated form is a word_form key" a
    # property of the function rather than of whoever last edited a table.
    folded = {}
    for x, readings in out.items():
        f = fold(x)
        if 2 <= len(f) <= 24:
            folded.setdefault(f, []).extend(readings)
    return {f: render_readings(r) for f, r in folded.items()}

def forms_for(headword, entry_text, limit=None):
    """The forms of `forms_with_morph`, without their labels.

    Every caller that only indexes forms -- coverage metrics, the frequency
    weighting, the lemmatiser's candidate index -- wants a set and would have to
    discard the labels itself."""
    return set(forms_with_morph(headword, entry_text, limit))
