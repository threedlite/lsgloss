#!/usr/bin/env python3
"""Score the gloss prompt against eval/gold.tsv (25 hand-checked entries)."""
import re, sys, json, unicodedata, urllib.request, argparse
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
from common import txt, load_entries
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.xref import is_xref
from clean_gloss import clean

p = argparse.ArgumentParser()
p.add_argument('--xml', required=True)
p.add_argument('--url', default='http://127.0.0.1:8080/v1/chat/completions')
p.add_argument('-j', '--jobs', type=int, default=4)
p.add_argument('-n', type=int, default=25, help='sample size')
p.add_argument('--offset', type=int, default=0, help='shift the sample to get held-out entries')
p.add_argument('--effort', default='low')
p.add_argument('--maxchars', type=int, default=2000)
A = p.parse_args()

SYS = (ROOT/'prompts/gloss-system.txt').read_text(encoding='utf-8').strip()
USR = (ROOT/'prompts/gloss-user.txt').read_text(encoding='utf-8').strip()
gold = {}
for line in (ROOT/'eval/gold.tsv').read_text(encoding='utf-8').splitlines():
    if line.strip() and not line.startswith('#'):
        k, v = line.split('\t')[:2]; gold[k] = v

ents = load_entries(A.xml)

need = []
for e in ents:
    b = txt(e)
    trs = re.findall(r'<tr\b[^>]*>(.*?)</tr>', e, re.S)
    f = txt(trs[0]) if trs else ''
    if (f and 1 <= len(f.split()) <= 5) or is_xref(b): continue
    need.append(e)
if A.offset:                       # held-out mode: positional sample, no gold
    step = max(1, len(need)//A.n)
    picked = [need[(i*step + A.offset) % len(need)] for i in range(A.n)]
else:                              # gold mode: select the gold headwords themselves, so the
    by_orth = {}                   # eval set stays fixed when classification rules change
    for e in need:
        o = txt((re.search(r'<orth\b[^>]*>(.*?)</orth>', e, re.S) or [None, ''])[1])
        by_orth.setdefault(o, e)
    picked = [by_orth[k] for k in gold if k in by_orth]
    missing = [k for k in gold if k not in by_orth]
    if missing:
        print(f"note: {len(missing)} gold entries no longer reach the model "
              f"(now handled deterministically): {', '.join(missing)}\n", file=sys.stderr)

def go(e):
    orth = txt((re.search(r'<orth\b[^>]*>(.*?)</orth>', e, re.S) or [None, ''])[1])
    body = txt(e)[:A.maxchars]
    payload = json.dumps({"messages":[{"role":"system","content":SYS},
                                      {"role":"user","content":USR.replace('{ENTRY}', body)}],
                          "temperature":0, "max_tokens":96,
                          "chat_template_kwargs":{"reasoning_effort":A.effort}}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request(
        A.url, data=payload, headers={"Content-Type":"application/json"}), timeout=300))
    return orth, clean(r["choices"][0]["message"]["content"])

def words(s):
    s = unicodedata.normalize('NFKD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return [w for w in re.sub(r'[^a-z0-9 ]', ' ', s).split() if w not in ('a','an','the','of','to')]

def verdict(pred, want):
    if not pred.strip(): return 'EMPTY'
    a, b = set(words(pred)), set(words(want))
    if 'xref' in a or 'xref' in b: return 'PASS' if ('xref' in a and 'xref' in b) else 'FAIL'
    if not a or not b: return 'FAIL'
    if a == b or (a & b and (a <= b or b <= a)): return 'PASS'
    if len(a & b)/max(1, len(a | b)) >= 0.5: return 'PASS'
    return 'REVIEW' if a & b else 'FAIL'

with ThreadPoolExecutor(max_workers=A.jobs) as ex:
    out = list(ex.map(go, picked))
tally = {}
print(f"{'entry':16} {'verdict':8} {'gold':30} pred")
print('-'*92)
for orth, g in out:
    want = gold.get(orth, '?')
    v = verdict(g, want) if want != '?' else '-'
    tally[v] = tally.get(v, 0) + 1
    print(f"{orth[:15]:16} {v:8} {want[:29]:30} {g[:38]!r}")
print('-'*92)
n = len(out)
print(" | ".join(f"{k} {v} ({v/n*100:.0f}%)" for k, v in sorted(tally.items())))
