"""Shared test setup: make the package importable and locate optional corpus data."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPO = ROOT.parent


def _first(*cands):
    """The first existing path, else the first candidate (so messages name it)."""
    for c in cands:
        if c.exists():
            return c
    return cands[0]


# The dictionary and corpus are cloned into data-sources/ next to the repo (the
# README's layout) or inside it; the committed data products live in the repo's
# own out/, with the working tree above it as a fallback.
XML = _first(ROOT / 'data-sources/lexica/CTS_XML_TEI/perseus/pdllex/lat/ls/lat.ls.perseus-eng2.xml',
             REPO / 'data-sources/lexica/CTS_XML_TEI/perseus/pdllex/lat/ls/lat.ls.perseus-eng2.xml')
TSV = _first(ROOT / 'out/ls_glosses.tsv', REPO / 'out/ls_glosses.tsv')
FREQ = _first(ROOT / 'out/latin_freq.tsv', REPO / 'out/latin_freq.tsv')
ZIP = _first(ROOT / 'out/lewis-short-glosses.zip', REPO / 'out/lewis-short-glosses.zip')

needs_corpus = unittest.skipUnless(
    XML.exists() and TSV.exists(),
    'corpus not present (see README setup); corpus-level checks skipped')
