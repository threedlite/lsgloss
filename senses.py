"""A compact map of an entry's senses, for the judge.

The judge was shown the first 800 characters of the focused article, and for
the commonest words that is philology: *ab* does not say "from" until
character 3,760, *quam* opens with a paragraph on its derivation. So the judge
rated "more ... the more" acceptable for *quam* and could not tell "to
choose, prefer" from a gloss of *vel*: what it needed was the list of senses
in the dictionary's own order, and L&S marks them -- `<sense n="I">`,
`<sense n="II">` -- each opening with its definition in italics. This view
prints the headword line and then one line per sense: its number and its
first italic phrase (or its first words where there is none), top levels
first, cut to a budget. The primary sense is the first line, which is what
a gloss has to match.
"""
import re, html
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parent))
from common import txt
from namegloss import _is_note

SENSE = re.compile(r'<sense\b([^>]*)>(.*?)(?=<sense\b|</entryFree>|$)', re.S)
ATTR = re.compile(r'\b(level|n)="([^"]*)"')
ITALIC = re.compile(r'<hi rend="ital">(.*?)</hi>', re.S)
LIG = str.maketrans({'æ': 'ae', 'œ': 'oe', 'Æ': 'Ae', 'Œ': 'Oe'})


def _clean(xml):
    xml = re.sub(r'<(cit|quote|bibl|foreign)\b.*?</\1>', ' ', xml, flags=re.S)
    return html.unescape(txt(xml)).translate(LIG)


def _headword_line(entry_xml):
    head = entry_xml.split('<sense', 1)[0]
    head = re.sub(r'<etym\b.*?</etym>', ' ', head, flags=re.S)
    line = _clean(head)
    line = re.sub(r'\([^()]*\)', ' ', line)
    line = re.sub(r'\s+', ' ', line).strip(' ,;:')
    return line[:120]


def sense_headings(entry_xml, budget=900, per_sense=70):
    """The headword line, then "I. definition / II. definition ..." in the
    dictionary's order, level-1 senses before their subdivisions."""
    lines = [_headword_line(entry_xml)]
    senses = []
    for m in SENSE.finditer(entry_xml):
        attrs = dict(ATTR.findall(m.group(1)))
        level = int(attrs.get('level', '1') or 1)
        label = attrs.get('n', '')
        body = m.group(2)
        its = [_clean(h) for h in ITALIC.findall(body)]
        # a grammar note in italics ("conj.", "inf. pres. pass.") is not a sense
        its = [s for s in its if re.search(r'[a-z]', s) and not _is_note(s)]
        text = '; '.join(its[:2]) if its else _clean(body)
        text = re.sub(r'(?:[:;,]\s*){2,}', ' ', text)      # ": : : ;" runs, not "a; b"
        text = re.sub(r'\s+', ' ', text).strip(' ,;:.')
        if not text or _is_note(text):
            continue
        senses.append((level, label, text[:per_sense]))
    used = len(lines[0])
    for want in (1, 2):
        for level, label, text in senses:
            if level != want:
                continue
            line = f"{label}. {text}" if label else text
            if used + len(line) > budget:
                break
            lines.append(line); used += len(line) + 1
    return '\n'.join(lines)
