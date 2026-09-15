#!/usr/bin/env python3
"""Corpus characterisation: run every model-free function over the whole
dictionary and diff the result against a committed baseline.

Unit tests pin behaviour on cases someone thought to write down. This pins it on
all 51,643 real entries, which is where the surprises live -- the `diānœa`
ligature bug and the `Spāco, cūs` mis-stemming were both invisible to any
hand-written case but obvious in a corpus-wide diff.

The point is NOT that the diff stays empty. Every fix in REVIEW.md is meant to
change rows. The point is that a fix which should touch 3 rows can be SHOWN to
touch 3 rows, so collateral damage cannot hide inside an intended change.

    python3 regress.py --xml <ls.xml>              # diff against baseline, exit 1 on change
    python3 regress.py --xml <ls.xml> --accept     # rewrite the baseline after review

Needs no model and no network. Runs in a few seconds.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import txt, load_entries, load_rows, fold, plain, letters, focus
from clean_gloss import clean, enforce, strip_unstated_nationality
from namegloss import name_gloss, name_clean, is_name_entry, NAME_MAXWORDS
from ground import score as ground_score
from suspect import reasons, gloss_vocabulary
from inflect import forms_for, _noun_stem_and_key, HEAD
from lemmafreq import load_form_counts, lemma_frequencies
from eval.xref import is_xref

BASE = ROOT / 'baseline'


def _sha(items):
    h = hashlib.sha256()
    for s in items:
        h.update(s.encode('utf-8')); h.update(b'\n')
    return h.hexdigest()[:16]


# --------------------------------------------------------------- the probes
# Each probe returns {row_key: value}. Only rows where the function DOES
# something are recorded: a baseline listing 51,643 unchanged strings buries the
# signal, and the whole-corpus hash below still catches anything the filter drops.

def probe_clean(ctx):
    """clean() over RAW model output, not over the finished TSV.

    The shipped TSV has already been through clean(), so probing it is a no-op
    that would report an empty baseline and silently test nothing. out/ckpt.jsonl
    keeps every raw reply the model ever gave, which is the input this function
    actually has to survive."""
    out = {}
    for k, raw in ctx['raw'].items():
        c = clean(raw)
        if c != raw:
            out[k] = f"{raw}\t->\t{c}"
    return out


def probe_enforce(ctx):
    out = {}
    for k, raw in ctx['raw'].items():
        g = clean(raw)
        if not g.strip():
            continue
        e = enforce(g)
        if e != g:
            out[k] = f"{g}\t->\t{e}"
    return out


def probe_nationality(ctx):
    """strip_unstated_nationality() over RAW model output, for the same reason
    as probe_clean: the finished TSV has already had it applied."""
    out = {}
    for k, raw in ctx['raw'].items():
        i = int(k.rsplit(':', 1)[1])
        if i >= len(ctx['bodies']):
            continue
        g = clean(raw)
        n = strip_unstated_nationality(g, ctx['bodies'][i])
        if n != g:
            out[k] = f"{g}\t->\t{n}"
    return out


def probe_names(ctx):
    """name_gloss() over every capitalised entry: the italic definition each
    takes, after clean and the name cap, or nothing."""
    out = {}
    for e, r in zip(ctx['ents'], ctx['rows']):
        if not is_name_entry(r[1]):
            continue
        g = name_gloss(e, r[1])
        if g:
            out[r[0]] = enforce(name_clean(g, NAME_MAXWORDS, r[1]), NAME_MAXWORDS)
    return out


def probe_suspect(ctx):
    out = {}
    vocab = gloss_vocabulary(ctx['rows'])
    for r, body in zip(ctx['rows'], ctx['bodies']):
        w = reasons(r[1], r[2], r[3], body, vocab)
        if w:
            out[r[0]] = ','.join(w)
    return out


def probe_xref(ctx):
    return {k: '1' for k, body in zip(ctx['keys'], ctx['bodies']) if is_xref(body)}


def probe_stem(ctx):
    """The parsed paradigm stem for every entry L&S gives a headword line for."""
    out = {}
    for k, body in zip(ctx['keys'], ctx['bodies']):
        m = HEAD.match(re.sub(r'\s+', ' ', body))
        if not m:
            continue
        stem, key = _noun_stem_and_key(m.group(1), m.group(2))
        if stem:
            out[k] = f"{fold(m.group(2))}\t{stem}\t{key}"
    return out


def probe_forms(ctx):
    """Generated paradigm per entry, as a count plus a hash of the sorted forms.

    The forms themselves are 1.5M strings; the hash makes the baseline small
    while still going red on any change, and `--show` prints the real diff for
    the rows that moved."""
    out = {}
    for r, body in zip(ctx['rows'], ctx['bodies']):
        fs = forms_for(r[1], body[:200])
        out[r[0]] = f"{len(fs)}\t{_sha(sorted(fs))}"
    return out


def probe_lemmafreq(ctx):
    lf = lemma_frequencies(ctx['rows'], ctx['bodies'], ctx['form_counts'])
    return {k: str(v) for k, v in lf.items()}


def probe_norm(ctx):
    """fold/plain/letters over every headword: the three keys the whole package
    joins on. A drift here silently unlinks dictionary.csv from morphology.csv."""
    return {r[0]: f"{fold(r[1])}\t{plain(r[1])}\t{letters(r[1])}" for r in ctx['rows']}


PROBES = {
    'clean':     probe_clean,
    'enforce':   probe_enforce,
    'nationality': probe_nationality,
    'names':     probe_names,
    'suspect':   probe_suspect,
    'xref':      probe_xref,
    'stem':      probe_stem,
    'forms':     probe_forms,
    'lemmafreq': probe_lemmafreq,
    'norm':      probe_norm,
}


# ------------------------------------------------------------------ metrics
# Frequency-weighted defect counts. These must never get worse: a fix that
# repairs one class while breaking another shows up here even when the
# per-probe diffs look reasonable in isolation.

def metrics(ctx):
    rows, bodies = ctx['rows'], ctx['bodies']
    lf = lemma_frequencies(rows, bodies, ctx['form_counts'])
    freq = lambda r: lf.get(r[0], 0)
    # Denominator is the CORPUS, not the sum of lemma frequencies. That sum
    # double-counts any form two entries can both generate, so it moves whenever
    # attribution changes -- which would make every share look better or worse for
    # reasons that have nothing to do with the defect being measured.
    total = sum(ctx['form_counts'].values())

    m = {'corpus_tokens': total, 'attributed_tokens': sum(lf.values()),
         'rows': len(rows)}
    vocab = gloss_vocabulary(rows)
    det_rows, det_tok = {}, {}
    for r, body in zip(rows, bodies):
        if not r[2].strip():
            det_rows['empty'] = det_rows.get('empty', 0) + 1
            det_tok['empty'] = det_tok.get('empty', 0) + freq(r)
            continue
        for w in reasons(r[1], r[2], r[3], body, vocab):
            det_rows[w] = det_rows.get(w, 0) + 1
            det_tok[w] = det_tok.get(w, 0) + freq(r)
    m['detector_rows'] = dict(sorted(det_rows.items()))
    m['detector_tokens'] = dict(sorted(det_tok.items()))

    # coverage: how much of the corpus the generated paradigms actually index
    indexed = set()
    for r, body in zip(rows, bodies):
        indexed |= forms_for(r[1], body[:200])
    fc = ctx['form_counts']
    covered = sum(n for w, n in fc.items() if w in indexed)
    m['form_coverage_tokens'] = covered
    m['form_coverage_pct'] = round(100.0 * covered / max(1, sum(fc.values())), 3)
    m['glossed_rows'] = sum(1 for r in rows if r[2].strip())
    return m


# --------------------------------------------------------------------- diff

def resolve(p):
    """Resolve an input path, preferring the WORKING tree over the repo copy.

    There are two `out/` directories: this repo commits its data products under
    `lsgloss/out/`, while the pipeline is run from the directory above and writes
    to `../out/`. An earlier version of this function tried `ROOT / p` before
    `ROOT.parent / p`, so the probes silently read the committed copy while the
    pipeline had already updated the working one -- and reported "no change" after
    a run that had changed 14 rows. Order matters, and main() prints what it
    actually opened so this can never go unnoticed again.
    """
    cand = Path(p)
    if cand.is_absolute():
        return str(cand)
    for c in (Path.cwd() / p, ROOT.parent / p, ROOT / p):
        if c.exists():
            return str(c)
    return str(p)


def load_raw(path):
    """{checkpoint_key: raw model reply} from a *_ckpt.jsonl.

    Keyed by pass and entry index so a row keeps its identity across runs even
    though several passes gloss the same entry."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding='utf-8').splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        g = d.get('g')
        if isinstance(g, str) and g.strip() and 'i' in d:
            out[f"{d.get('p', 'main')}:{d['i']}"] = re.sub(r'\s+', ' ', g).strip()
    return out


def read_baseline(name):
    p = BASE / f'{name}.tsv'
    if not p.exists():
        return None
    out = {}
    for line in p.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        k, _, v = line.partition('\t')
        out[k] = v
    return out


def write_baseline(name, data):
    p = BASE / f'{name}.tsv'
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(f"# {name}: {len(data)} rows -- regenerate with `make baseline`\n")
        for k in sorted(data):
            fh.write(f"{k}\t{data[k]}\n")


def diff(name, old, new, show):
    if old is None:
        print(f"  {name:10} no baseline (run --accept to create)")
        return 1
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    n = len(added) + len(removed) + len(changed)
    if not n:
        print(f"  {name:10} unchanged ({len(new):,} rows)")
        return 0
    print(f"  {name:10} CHANGED  +{len(added)} -{len(removed)} ~{len(changed)}  "
          f"(baseline {len(old):,} -> {len(new):,})")
    for label, keys, fmt in (('+', added, lambda k: new[k]),
                             ('-', removed, lambda k: old[k]),
                             ('~', changed, lambda k: f"{old[k]}  =>  {new[k]}")):
        for k in keys[:show]:
            print(f"      {label} {k}: {fmt(k)}")
        if len(keys) > show:
            print(f"      {label} ... and {len(keys)-show} more")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--xml', default='data-sources/lexica/CTS_XML_TEI/perseus/'
                                     'pdllex/lat/ls/lat.ls.perseus-eng2.xml')
    ap.add_argument('--tsv', default='out/ls_glosses.tsv')
    ap.add_argument('--freq', default='out/latin_freq.tsv')
    ap.add_argument('--ckpt', default='out/ckpt.jsonl',
                    help='raw model replies, the input corpus for the clean/enforce probes')
    ap.add_argument('--accept', action='store_true',
                    help='rewrite the baseline from current behaviour, AFTER reviewing the diff')
    ap.add_argument('--only', help='comma-separated probe names to run')
    ap.add_argument('--show', type=int, default=8, help='example rows to print per change kind')
    a = ap.parse_args()

    a.xml, a.tsv, a.freq, a.ckpt = (resolve(x) for x in (a.xml, a.tsv, a.freq, a.ckpt))
    for f in (a.xml, a.tsv, a.freq):
        if not Path(f).exists():
            sys.exit(f"missing input: {f}\n(regress.py needs the corpus; see README setup)")

    print("inputs:")
    for label, path in (('xml', a.xml), ('tsv', a.tsv), ('freq', a.freq), ('ckpt', a.ckpt)):
        print(f"  {label:5} {path}")
    print()
    ents = load_entries(a.xml)
    rows = load_rows(a.tsv)
    if len(rows) != len(ents):
        sys.exit(f"row/entry mismatch: {len(rows)} rows vs {len(ents)} entries -- "
                 "the TSV is positional, so this invalidates every probe")
    ctx = {'rows': rows,
           'ents': ents,
           'bodies': [txt(e) for e in ents],
           'keys': [r[0] for r in rows],
           'form_counts': load_form_counts(a.freq),
           'raw': load_raw(a.ckpt)}

    names = a.only.split(',') if a.only else list(PROBES)
    print(f"characterising {len(rows):,} entries over {len(names)} probes\n")
    total = 0
    for name in names:
        data = PROBES[name](ctx)
        if a.accept:
            write_baseline(name, data)
            print(f"  {name:10} baseline written ({len(data):,} rows)")
        else:
            total += diff(name, read_baseline(name), data, a.show)

    m = metrics(ctx)
    mp = BASE / 'metrics.json'
    if a.accept:
        mp.write_text(json.dumps(m, indent=2, sort_keys=True) + '\n')
        print(f"\n  metrics    baseline written")
    else:
        print()
        if not mp.exists():
            print("  metrics    no baseline (run --accept to create)"); total += 1
        else:
            old = json.loads(mp.read_text())
            total += diff_metrics(old, m)

    if a.accept:
        print("\nbaseline accepted. Review the diff in version control before keeping it.")
        return 0
    if total:
        print(f"\n{total:,} differences from baseline. If they are all intended, "
              f"re-run with --accept.")
        return 1
    print("\nno change from baseline.")
    return 0


def diff_metrics(old, new):
    """Report every metric move, and call out the ones that are regressions.

    Token-weighted counts are compared as a SHARE of the corpus, never as raw
    totals. Fixing a paradigm bug makes more forms match, which raises every
    lemma's frequency and therefore every token-weighted defect count at once --
    a scale change, not a regression. `detector_rows` is weight-independent and is
    the count that actually says whether a defect got more common.
    """
    bad = 0
    scale_old = max(1, old.get('corpus_tokens', 1))
    scale_new = max(1, new.get('corpus_tokens', 1))
    INFORMATIONAL = {'corpus_tokens', 'attributed_tokens', 'rows'}

    for k in sorted(set(old) | set(new)):
        o, n = old.get(k), new.get(k)
        if isinstance(o, dict) or isinstance(n, dict):
            o, n = o or {}, n or {}
            share = k == 'detector_tokens'
            for sk in sorted(set(o) | set(n)):
                ov, nv = o.get(sk, 0), n.get(sk, 0)
                if ov == nv:
                    continue
                if share:
                    os_, ns_ = 100.0 * ov / scale_old, 100.0 * nv / scale_new
                    # Worse only if BOTH the count and the share rose. Either one
                    # alone moves when the frequency attribution changes scale:
                    # removing Spaco's bogus 65,861 tokens shrinks the denominator,
                    # which raises every share without any defect getting commoner.
                    worse = nv > ov and round(ns_, 4) > round(os_, 4)
                    print(f"  metrics    {'WORSE' if worse else 'better'} "
                          f"{k}.{sk}: {ov:,} -> {nv:,} "
                          f"({os_:.3f}% -> {ns_:.3f}% of corpus)")
                else:
                    worse = nv > ov
                    print(f"  metrics    {'WORSE' if worse else 'better'} "
                          f"{k}.{sk}: {ov:,} -> {nv:,}")
                bad += worse
            continue
        if o == n:
            continue
        if k in INFORMATIONAL:
            fmt = lambda v: 'absent' if v is None else (f'{v:,}' if isinstance(v, int) else str(v))
            print(f"  metrics    (scale) {k}: {fmt(o)} -> {fmt(n)}")
            continue
        if o is None or n is None:          # metric added or removed
            print(f"  metrics    (new) {k}: {o} -> {n}")
            continue
        # coverage and glossed rows going DOWN is the regression
        worse = (n < o) if k.startswith(('form_coverage', 'glossed')) else (n > o)
        bad += worse
        shown = f"{o:,} -> {n:,}" if isinstance(o, int) else f"{o} -> {n}"
        print(f"  metrics    {'WORSE' if worse else 'better'} {k}: {shown}")
    return bad


if __name__ == '__main__':
    sys.exit(main())
