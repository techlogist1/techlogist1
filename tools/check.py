#!/usr/bin/env python3
"""Rasterise an SVG in both palettes and assert the hard constraints.

resvg honours neither @media nor @keyframes, which is exactly what we want to
exploit: it shows the *base* state, and our base state is deliberately the
finished frame. To see the light branch we append the light rules to the end of
the style block so they win on source order.
"""
import re, subprocess, sys, os, pathlib

def light_variant(raw: str) -> str:
    m = re.search(r'@media \(prefers-color-scheme: ?light\)\s*\{(.*?)\n\}', raw, re.S)
    if not m:
        return raw
    return raw.replace('</style>', m.group(1) + '\n</style>')

def check(path, outdir='render', zoom=2):
    p = pathlib.Path(path)
    raw = p.read_text(encoding='utf-8')
    os.makedirs(outdir, exist_ok=True)
    stem = p.stem
    problems = []

    if '<script' in raw.lower():
        problems.append('contains <script>')
    ext = [u for u in re.findall(r'(?:href|src)\s*=\s*["\'](?!#)([^"\']+)', raw, re.I)]
    if ext:
        problems.append(f'external refs: {ext}')
    urls = re.findall(r'https?://(?!www\.w3\.org)[^\s"\'<>]+', raw)
    if urls:
        problems.append(f'external URLs: {urls}')
    if '@font-face' in raw or 'url(http' in raw:
        problems.append('webfont reference')
    if 'var(--' in raw:
        problems.append('CSS custom properties (resvg renders these black)')
    if 'prefers-color-scheme' not in raw:
        problems.append('no prefers-color-scheme block')
    if '@keyframes' in raw and 'prefers-reduced-motion' not in raw:
        problems.append('animated but no prefers-reduced-motion block')

    lp = pathlib.Path(outdir) / f'{stem}-light.svg'
    lp.write_text(light_variant(raw), encoding='utf-8')

    renders = {}
    for label, src in (('dark', p), ('light', lp)):
        out = pathlib.Path(outdir) / f'{stem}-{label}.png'
        r = subprocess.run(['resvg', str(src), str(out), '--zoom', str(zoom)],
                           capture_output=True, text=True)
        noisy = [l for l in r.stderr.splitlines()
                 if 'not supported' not in l and 'Skipped' not in l and l.strip()]
        if r.returncode != 0:
            problems.append(f'{label}: resvg failed rc={r.returncode} {r.stderr[:200]}')
        if noisy:
            problems.append(f'{label}: resvg warnings {noisy[:3]}')
        renders[label] = out

    if renders['dark'].exists() and renders['light'].exists():
        if renders['dark'].read_bytes() == renders['light'].read_bytes():
            problems.append('light and dark render IDENTICALLY (palette not applying)')

    size = p.stat().st_size
    print(f'{p.name:28} {size:>7,} B   ' + ('OK' if not problems else 'PROBLEMS'))
    for x in problems:
        print(f'    !! {x}')
    return size, problems

if __name__ == '__main__':
    total = 0
    bad = 0
    for a in sys.argv[1:]:
        s, pr = check(a)
        total += s
        bad += len(pr)
    print(f'\ntotal {total:,} B across {len(sys.argv)-1} file(s); {bad} problem(s)')
    sys.exit(1 if bad else 0)
