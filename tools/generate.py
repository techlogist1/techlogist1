#!/usr/bin/env python3
"""Regenerate every dynamic SVG on the profile, in one run.

One script, one workflow, one commit. Four workflows would be four independent
failure surfaces and four ways for the profile to end up partially stale with
no signal that it had.

Failure contract, in order of importance:

  1. A generator that raises leaves its existing file untouched on disk. The
     last good SVG survives, so the README never shows a broken image.
  2. A generator whose data source comes back empty emits a legible "no data"
     frame rather than an empty or malformed file. An empty file rendered
     through <img> is a broken-image icon, which is worse than stale data.
  3. Every write is atomic (temp file, validated, then os.replace) so a crash
     mid-write cannot leave a truncated SVG in place.
  4. If ANY generator failed, the process exits non-zero. The run goes red in
     the Actions tab. Failure is never silent.

Hard constraints every emitted file must satisfy, asserted before it is
written: no <script>, no external URL, no webfont, no CSS custom properties
(resvg renders var() as black), a prefers-color-scheme block, and a
prefers-reduced-motion block if the file animates.
"""

import json, os, sys, time, traceback, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, date

USER = "techlogist1"
API = "https://api.github.com"
GQL = "https://api.github.com/graphql"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

# ── grid ────────────────────────────────────────────────────────────────
FS = 14          # font-size, px
CH = 8.4         # character advance at FS for a 0.6-ratio monospace face
LH = 17          # line advance; ~1.21em, near where box-drawing tiles
PADX, PADY = 22, 26
COLS = 61        # every panel and the hero share one width, so the page reads
                 # as one object rather than a stack of differently-scaled widgets

FONT = ('ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,'
        '"Cascadia Mono","DejaVu Sans Mono","Liberation Mono",monospace')

# Warm phosphor. Literal colours in the base rules, overridden by the light
# media block -- never CSS custom properties, which resvg drops to black.
BASE_CSS = f"""
.glass{{fill:#0E0E10}}
.edge{{fill:none;stroke:#26262B;stroke-width:1}}
text{{font-family:{FONT};font-size:{FS}px;white-space:pre;fill:#B8B8BE}}
.fr{{fill:#4A4A52}} .hi{{fill:#EDEDEF}} .ac{{fill:#B8B8BE}} .dm{{fill:#7A7A82}}
.cool{{fill:#EDEDEF}} .deep{{fill:#4A4A52}} .body{{fill:#B8B8BE}}
.rust{{fill:#B8B8BE}} .gold{{fill:#EDEDEF}} .plum{{fill:#7A7A82}}
.q0{{fill:#26262B}} .q1{{fill:#4A4A52}} .q2{{fill:#7A7A82}} .q3{{fill:#B8B8BE}} .q4{{fill:#EDEDEF}}
.g0{{fill:#1E1E22}} .g1{{fill:#2E2E34}} .g2{{fill:#3E3E46}} .g3{{fill:#55555E}}
.scan{{opacity:0}}
.vig{{opacity:0}}
.scrim{{opacity:1}}
@media (prefers-color-scheme: light){{
  .glass{{fill:#FBFBFC}}
  .edge{{stroke:#E2E2E6}}
  text{{fill:#45454C}}
  .fr{{fill:#A8A8B0}} .hi{{fill:#16161A}} .ac{{fill:#45454C}} .dm{{fill:#76767E}}
  .cool{{fill:#16161A}} .deep{{fill:#A8A8B0}} .body{{fill:#45454C}}
  .rust{{fill:#45454C}} .gold{{fill:#16161A}} .plum{{fill:#76767E}}
  .q0{{fill:#EAEAEE}} .q1{{fill:#C6C6CC}} .q2{{fill:#94949C}} .q3{{fill:#5C5C64}} .q4{{fill:#16161A}}
  .g0{{fill:#F0F0F2}} .g1{{fill:#E2E2E6}} .g2{{fill:#D0D0D6}} .g3{{fill:#B8B8C0}}
  .scrim{{opacity:0}}
}}
"""

DEFS = """
  <pattern id="sl" width="6" height="6" patternUnits="userSpaceOnUse">
    <rect width="6" height="3" fill="#000"/>
  </pattern>
  <radialGradient id="vig" cx="50%" cy="46%" r="78%">
    <stop offset="58%" stop-color="#000" stop-opacity="0"/>
    <stop offset="100%" stop-color="#000" stop-opacity=".34"/>
  </radialGradient>
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def svg_doc(w, h, title, desc, css, body, defs_extra=""):
    # xml:space="preserve" on the root is load-bearing for every panel: the CSS
    # white-space:pre property is honoured by browsers but not by resvg's text
    # layout, and without this every run of padding spaces -- the month ruler,
    # the dotted leaders, the frame padding -- collapses to a single space and
    # the ASCII grid stops lining up.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-labelledby="t d" xml:space="preserve">
<title id="t">{esc(title)}</title>
<desc id="d">{esc(desc)}</desc>
<style>{BASE_CSS}{css}</style>
<defs>{DEFS}{defs_extra}</defs>
<rect class="glass" width="{w}" height="{h}" rx="8"/>
{body}
<rect class="scan" x="0" y="-12" width="{w}" height="{h+24}" fill="url(#sl)"/>
<rect class="vig" width="{w}" height="{h}" rx="8" fill="url(#vig)"/>
<rect class="edge" x=".5" y=".5" width="{w-1}" height="{h-1}" rx="8"/>
</svg>
"""



def line(y, cells, cols, cls=""):
    """One full-width row as a single <text>, forced to exactly cols*CH wide.

    Everything inside a row MUST go through here. Mixing a string-rendered run
    with a separately-positioned element makes the two disagree the moment the
    viewer's monospace advance differs from CH -- Consolas is 0.55em, DejaVu
    and SF Mono are 0.60em, so a hardcoded constant is wrong on some machine
    no matter which value it holds. textLength pins the row to the grid instead
    of trusting the font, and because xml:space keeps the padding intact the
    natural width is already within a few percent, so the correction spacing
    distributes is invisible.
    """
    total = sum(len(t) for _, t in cells)
    pad = cols - total
    if pad > 0:
        # Fold the padding into the second-to-last cell so it stays inside a
        # styled tspan. Emitted as a bare unstyled run instead, resvg's
        # textLength handling loses it and the row's closing rule collapses
        # back against the content -- measured, not guessed.
        i = -2 if len(cells) > 1 else -1
        c, t = cells[i]
        cells = list(cells)
        cells[i] = (c, t + " " * pad)
    elif pad < 0 and len(cells) > 1:
        c, t = cells[-2]
        if len(t) > -pad:
            cells = cells[:-2] + [(c, t[:pad])] + cells[-1:]
    spans = "".join(f'<tspan class="{c}">{esc(t)}</tspan>' if c else esc(t)
                    for c, t in cells)
    a = f' class="{cls}"' if cls else ""
    return (f'<text{a} x="{PADX}" y="{y}" textLength="{cols*CH:.1f}" '
            f'lengthAdjust="spacing">{spans}</text>')


def rule(title, cols, right=""):
    """A titled top border: '┌─ TITLE ─────── right ─┐' at exactly `cols` chars."""
    head = f"┌─ {title} "
    tail = (f" {right} ─┐" if right else " ─┐")
    fill = cols - len(head) - len(tail)
    if fill < 1:
        head, fill = f"┌─ {title} ", 1
    return head + "─" * fill + tail


def foot(cols, right=""):
    tail = (f" {right} ─┘" if right else "──┘")
    fill = cols - 1 - len(tail)
    return "└" + "─" * fill + tail


def row(inner, cols):
    """Pad an interior line to the frame width with the side rules."""
    inner = inner[: cols - 6]
    return "│  " + inner + " " * (cols - 5 - len(inner)) + "│"


# ── http ────────────────────────────────────────────────────────────────

def _req(url, data=None, headers=None):
    h = {"Accept": "application/vnd.github+json",
         "User-Agent": "techlogist1-profile-generator"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    if headers:
        h.update(headers)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode()), r.status


def rest(path, retries=4):
    """GET a REST endpoint. The stats/* endpoints answer 202 while GitHub
    computes them asynchronously, so those need to be retried, not failed."""
    url = path if path.startswith("http") else f"{API}{path}"
    last = None
    for i in range(retries):
        try:
            payload, status = _req(url)
            if status == 202 or payload in ([], None):
                if status == 202:
                    time.sleep(3 * (i + 1))
                    continue
            return payload
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429) and i < retries - 1:
                time.sleep(5 * (i + 1))
                continue
            if e.code == 404:
                return None
            raise
        except urllib.error.URLError as e:
            last = e
            time.sleep(3 * (i + 1))
    if last:
        raise last
    return None


def graphql(query):
    payload, _ = _req(GQL, data={"query": query})
    if "errors" in payload:
        raise RuntimeError(f"graphql: {payload['errors']}")
    return payload["data"]


# ── data ────────────────────────────────────────────────────────────────

def public_repos():
    repos = rest(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed") or []
    return [r for r in repos if not r["private"] and not r["fork"]
            and r["name"] != USER]


def calendar():
    d = graphql("""
    { user(login:"%s"){ createdAt
        contributionsCollection{ contributionCalendar{ totalContributions
          weeks{ contributionDays{ date contributionCount weekday } } } } } }
    """ % USER)
    u = d["user"]
    weeks = u["contributionsCollection"]["contributionCalendar"]["weeks"]
    total = u["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    return u["createdAt"], weeks, total


# ── generators ──────────────────────────────────────────────────────────

def gen_hero():
    """The hero. Text is hand-authored; the field behind it is not.

    The field runs elementary cellular automaton rule 110 -- the Turing-complete
    one -- seeded with the real contribution year bucketed to the field width.
    The pattern is therefore derived from this account's actual history and no
    other profile produces it, and the motion comes from a system with rules
    rather than a keyframe asserting that something should appear.

    Deliberately NOT: typewriter reveal, matrix rain, blinking cursor, glow
    pulse, scanline sweep, generic fade-in. Rule 110's output is triangular and
    self-similar, which is what keeps it from reading as matrix rain -- falling
    glyph columns are random; this is structured, and the structure is the point.
    """
    W, H = COLS, 30
    try:
        _, weeks, _ = calendar()
        days = [d for w in weeks for d in w["contributionDays"]]
    except Exception:
        days = []

    if days:
        n = len(days)
        buckets = [sum(d["contributionCount"]
                       for d in days[i * n // W: max(i * n // W + 1, (i + 1) * n // W)])
                   for i in range(W)]
        nz = sorted(b for b in buckets if b)
        thresh = nz[len(nz) // 2] if nz else 1
        cur = [1 if b >= thresh else 0 for b in buckets]
    else:
        cur = [0] * W
        cur[W - 2] = 1

    # Burn-in. Rule 110 grows leftward and this account's live cells all sit in
    # recent months on the right, so without this two thirds of the panel is bare.
    for _ in range(60):
        cur = [(110 >> (cur[(i - 1) % W] * 4 + cur[i] * 2 + cur[(i + 1) % W])) & 1
               for i in range(W)]

    RAMP = " ·░▒▓█"
    rows, age = [], [0] * W
    for _ in range(H):
        age = [(age[i] + 1 if cur[i] else 0) for i in range(W)]
        rows.append("".join(RAMP[0] if not cur[i] else RAMP[min(5, 1 + age[i])]
                            for i in range(W)))
        cur = [(110 >> (cur[(i - 1) % W] * 4 + cur[i] * 2 + cur[(i + 1) % W])) & 1
               for i in range(W)]

    w_px = int(COLS * CH + PADX * 2)
    BLH = 11
    band_h = H * BLH
    band = []
    for rep in (0, 1):                    # drawn twice so the scroll loop is seamless
        for gi, r in enumerate(rows):
            # textLength is required here, not optional. Without it the band
            # rows render at their natural advance while the framed rows are
            # pinned to the panel width, and the field stops dead at ~73% with
            # a hard vertical seam and a bald right margin. Measured, not guessed.
            band.append(f'<text class="g{gi * 4 // H}" x="{PADX}" '
                        f'y="{(rep * H + gi) * BLH + BLH}" font-size="10" '
                        f'textLength="{COLS * CH:.1f}" lengthAdjust="spacing">'
                        f'{esc(r)}</text>')

    art = [
        [("fr", "┌─ "), ("hi", "LOKAVYA SINGH"), ("fr", " "), ("fr", "─" * 29),
         ("dm", " JAIPUR · IN "), ("fr", "─┐")],
        [("fr", "│"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "),
         ("hi", "Local-first desktop software that keeps"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("hi", "its receipts."), ("fr", "│")],
        [("fr", "│"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("dm", "> "), ("hi", "flint   "),
         ("body", "a timer that is really a plugin engine"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("dm", "> "), ("hi", "vysted  "),
         ("body", "a finance terminal an agent can drive"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("dm", "> "), ("hi", "ulpf    "),
         ("body", "a log pipeline that proves what it read"), ("fr", "│")],
        [("fr", "│"), ("fr", "│")],
        [("fr", foot(COLS, "the field below is rule 110, seeded by my year"))],
    ]
    ty, LH2 = 44, 20
    text_rows = [line(ty + i * LH2, cells, COLS) for i, cells in enumerate(art)]

    h_px = ty + LH2 * len(art) + 118
    css = f"""
@keyframes climb{{from{{transform:translateY(0)}}to{{transform:translateY(-{band_h}px)}}}}
.band{{animation:climb 46s linear infinite}}
@media (prefers-reduced-motion: reduce){{ .band{{animation:none}} }}
"""
    band_top = ty + LH2 * len(art) - 6
    body = f"""
<defs>
  <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#fff" stop-opacity="0"/>
    <stop offset="34%" stop-color="#fff" stop-opacity="1"/>
    <stop offset="100%" stop-color="#fff" stop-opacity="1"/>
  </linearGradient>
  <mask id="bandmask">
    <rect x="0" y="{band_top}" width="{w_px}" height="{h_px - band_top}" fill="url(#fade)"/>
  </mask>
  <clipPath id="bandclip">
    <rect x="0" y="{band_top}" width="{w_px}" height="{h_px - band_top}"/>
  </clipPath>
</defs>
<g clip-path="url(#bandclip)" mask="url(#bandmask)">
  <g class="band" transform="translate(0,{band_top})">{''.join(band)}</g>
</g>
{''.join(text_rows)}
"""
    return svg_doc(w_px, h_px,
                   "Lokavya Singh — local-first desktop software that keeps its receipts",
                   "A monochrome terminal frame over a field running cellular automaton "
                   "rule 110, seeded with the real contribution year. Three projects: "
                   "flint, a timer that is really a plugin engine; vysted, a finance "
                   "terminal an agent can drive; ulpf, a log pipeline that proves what "
                   "it read.",
                   css, body)


BADGES = [
    # (label, link target, why this target)
    ("rust",       "https://github.com/techlogist1?tab=repositories&language=rust"),
    ("typescript", "https://github.com/techlogist1?tab=repositories&language=typescript"),
    # The language filter matches a repo's PRIMARY language only. python returns
    # just this profile repo (its own tooling) and svelte returns nothing at all,
    # so both point at the project where that work actually lives instead of at
    # a filter page that is empty or misleading.
    ("python",     "https://github.com/techlogist1/vysted-terminal"),
    ("svelte",     "https://github.com/techlogist1/ulpf"),
    ("tauri",      "https://github.com/techlogist1/flint"),
]


def _badge(label):
    """A pill. Monochrome, sized from its own text so a row of them wraps on
    whole badges rather than breaking one in half."""
    BFS, BCH, H = 12, 7.0, 22
    w = int(len(label) * BCH) + 20
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {H}" '
            f'width="{w}" height="{H}" role="img" xml:space="preserve">'
            f'<title>{esc(label)}</title>'
            f'<style>{BASE_CSS}text{{font-size:{BFS}px}}'
            f'.pill{{fill:none;stroke:#3A3A42;stroke-width:1}}'
            f'.pbg{{fill:#161619}}'
            f'@media (prefers-color-scheme: light){{'
            f'.pill{{stroke:#DADADE}}.pbg{{fill:#F4F4F6}}}}</style>'
            f'<rect class="pbg" x=".5" y=".5" width="{w-1}" height="{H-1}" rx="5"/>'
            f'<rect class="pill" x=".5" y=".5" width="{w-1}" height="{H-1}" rx="5"/>'
            f'<text class="hi" x="10" y="15" textLength="{len(label)*BCH:.1f}" '
            f'lengthAdjust="spacing">{esc(label)}</text></svg>')


def _release_badge(tag, state, filled):
    """Release state, carried by glyph and value rather than by hue -- the page
    has no accent colour, so a filled square means downloadable, a half square
    means pre-release and a hollow square means nothing is cut yet."""
    BFS, BCH, H = 12, 7.0, 22
    glyph = {"full": "■", "half": "◧", "none": "□"}[filled]
    text = f"{glyph} {tag} {state}" if tag else f"{glyph} {state}"
    w = int(len(text) * BCH) + 20
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {H}" '
            f'width="{w}" height="{H}" role="img" xml:space="preserve">'
            f'<title>{esc(text)}</title>'
            f'<style>{BASE_CSS}text{{font-size:{BFS}px}}'
            f'.pill{{fill:none;stroke:#3A3A42;stroke-width:1}}'
            f'.pbg{{fill:#161619}}'
            f'@media (prefers-color-scheme: light){{'
            f'.pill{{stroke:#DADADE}}.pbg{{fill:#F4F4F6}}}}</style>'
            f'<rect class="pbg" x=".5" y=".5" width="{w-1}" height="{H-1}" rx="5"/>'
            f'<rect class="pill" x=".5" y=".5" width="{w-1}" height="{H-1}" rx="5"/>'
            f'<text class="dm" x="10" y="15" textLength="{len(text)*BCH:.1f}" '
            f'lengthAdjust="spacing">{esc(text)}</text></svg>')


def gen_badges():
    """One SVG per technology plus one release marker per repo. Generated here
    rather than pulled from a badge service so the palette is exact and the page
    carries no third-party dependency."""
    made = []
    for label, _ in BADGES:
        write_atomic(os.path.join(ASSETS, f"badge-{label}.svg"), _badge(label),
                     f"badge-{label}")
        made.append(label)

    repos = public_repos()
    if not repos:
        raise RuntimeError("no public repositories returned")
    for r in repos:
        rel = [x for x in (rest(f"/repos/{USER}/{r['name']}/releases") or [])
               if not x.get("draft")]
        if rel:
            rel.sort(key=lambda x: x.get("published_at") or "", reverse=True)
            t = rel[0]
            tag = t["tag_name"]
            state, filled = (("pre-release", "half") if t.get("prerelease")
                             else ("released", "full"))
        else:
            tags = rest(f"/repos/{USER}/{r['name']}/tags?per_page=1") or []
            tag = tags[0]["name"] if tags else ""
            state, filled = ("tagged, no release" if tags else "no release"), "none"
        write_atomic(os.path.join(ASSETS, f"rel-{r['name']}.svg"),
                     _release_badge(tag, state, filled), f"rel-{r['name']}")
        made.append(f"rel-{r['name']}")
    return made


def gen_activity():
    created, weeks, total = calendar()
    if not weeks:
        return no_data("ACTIVITY", "the contribution calendar returned no weeks")

    days = [d for w in weeks for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in days]
    peak = max(counts) if counts else 0
    active = sum(1 for c in counts if c > 0)

    # Thresholds are taken against the actual peak rather than fixed cuts, so
    # the graph keeps its shape whatever the volume happens to be.
    def level(c):
        if c == 0:
            return 0
        if peak <= 4:
            return min(4, c)
        for i, f in enumerate((.10, .25, .50), start=1):
            if c <= max(1, round(peak * f)):
                return i
        return 4

    RAMP = "·░▒▓█"
    ncols = len(weeks)
    LABEL = 7                        # "|  Mon "
    cols = COLS

    # One character per week means a 3-letter month name occupies three weeks
    # and months sit ~4.3 weeks apart, so labels only just fit. Track where the
    # last one ended rather than gating on a modulus, which silently dropped
    # most of the year.
    ruler = [" "] * ncols
    seen, last_end = set(), -99
    for i, w in enumerate(weeks):
        d0 = w["contributionDays"][0]["date"]
        mo = d0[:7]
        m = datetime.strptime(d0, "%Y-%m-%d")
        if mo not in seen and m.day <= 7 and i < ncols - 3 and i > last_end:
            seen.add(mo)
            for j, c in enumerate(m.strftime("%b")):
                if i + j < len(ruler):
                    ruler[i + j] = c
            last_end = i + 3

    DAYNAME = ["Mon", "", "Wed", "", "Fri", "", ""]
    w_px = int(cols * CH + PADX * 2)
    h_px = int(PADY + LH * 12 + 10)

    parts = []
    y = PADY + LH
    parts.append(line(y, [("fr", rule("ACTIVITY", cols,
                                      f"{total:,} contributions in the last year"))], cols))
    parts.append(line(y + LH, [("fr", "│"),
                               ("dm", " " * (LABEL - 1) + "".join(ruler)),
                               ("fr", "│")], cols))

    grid = []
    for wd in range(7):
        cells = [("fr", "│"), ("dm", "  " + DAYNAME[wd].ljust(3) + " ")]
        runs, cur, buf = [], None, ""
        for w in weeks:
            day = next((d for d in w["contributionDays"] if d["weekday"] == wd), None)
            lv = level(day["contributionCount"]) if day else 0
            ch = RAMP[lv] if day else " "
            cls = f"q{lv}"
            if cls != cur and buf:
                runs.append((cur, buf))
                buf = ""
            cur = cls
            buf += ch
        if buf:
            runs.append((cur, buf))
        cells += runs
        cells.append(("fr", "│"))
        grid.append(line(y + LH * (wd + 2), cells, cols))
    parts.append('<g class="grid">' + "".join(grid) + "</g>")

    legend = f"  {active} active days  peak {peak}  less "
    parts.append(line(y + LH * 10,
                      [("fr", "│"), ("dm", legend)]
                      + [(f"q{i}", c) for i, c in enumerate(RAMP)]
                      + [("dm", " more"), ("fr", "│")], cols))
    parts.append(line(y + LH * 11,
                      [("fr", foot(cols, "densest week on the right"))], cols))

    css = """
/* Base state is the finished grid. The wipe's start frame is supplied by
   fill-mode backwards, so a renderer without animation support shows the
   graph complete rather than blank. Animates once on load, then settles. */
.grid{clip-path:none}
@keyframes wipe{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
.grid{animation:wipe 1.6s cubic-bezier(.25,.6,.25,1) .2s backwards}
@media (prefers-reduced-motion: reduce){ .grid{animation:none} }
"""
    return svg_doc(w_px, h_px,
                   f"Contribution activity — {total} contributions in the last year",
                   f"An ASCII density graph of {total} contributions across {ncols} "
                   f"weeks. {active} active days, peak {peak} in a single day.",
                   css, "\n".join(parts))


def gen_stats():
    created, weeks, cal_total = calendar()
    repos = public_repos()
    if not repos:
        return no_data("BY THE NUMBERS", "no public repositories returned")

    days = sorted(({"d": d["date"], "c": d["contributionCount"]}
                   for w in weeks for d in w["contributionDays"]),
                  key=lambda x: x["d"])
    best = run = 0
    for d in days:
        run = run + 1 if d["c"] > 0 else 0
        best = max(best, run)

    added = commits = releases = 0
    langs = {}
    for r in repos:
        for c in (rest(f"/repos/{USER}/{r['name']}/stats/contributors") or []):
            commits += c.get("total", 0)
            added += sum(w["a"] for w in c.get("weeks", []))
        for k, v in (rest(f"/repos/{USER}/{r['name']}/languages") or {}).items():
            langs[k] = langs.get(k, 0) + v
        releases += sum(1 for x in (rest(f"/repos/{USER}/{r['name']}/releases") or [])
                        if not x.get("draft"))

    opened = datetime.fromisoformat(created.replace("Z", "+00:00"))
    yrs = (datetime.now(timezone.utc) - opened).days / 365.25

    def kb(n):
        return f"{n/1000:.0f}k" if n >= 10000 else f"{n:,}"

    rows = [
        ("commits, public repos", f"{commits:,}"),
        ("lines added, public repos", f"{added:,}"),
        ("contributions, 365 days", f"{cal_total:,}"),
        ("longest daily streak", f"{best} days"),
        ("releases published", f"{releases}"),
        ("public repositories", f"{len(repos)}"),
        ("Rust, bytes", kb(langs.get("Rust", 0))),
        ("TypeScript, bytes", kb(langs.get("TypeScript", 0))),
        ("account opened", f"{opened:%b %Y} ({yrs:.1f} yrs)"),
    ]

    cols = COLS
    w_px = int(cols * CH + PADX * 2)
    h_px = int(PADY + LH * (len(rows) + 2) + 12)
    y = PADY + LH
    parts = [line(y, [("fr", rule("BY THE NUMBERS", cols))], cols)]
    for i, (label, val) in enumerate(rows):
        dots = "." * max(2, cols - 6 - len(label) - len(val))
        parts.append(line(y + LH * (i + 1),
                          [("fr", "│  "), ("dm", f"{label} {dots} "),
                           ("hi", val), ("fr", "│")], cols))
    parts.append(line(y + LH * (len(rows) + 1),
                      [("fr", foot(cols, "no stars, no followers"))], cols))
    return svg_doc(w_px, h_px, "By the numbers",
                   "Real counts from the GitHub API: commits, lines added, "
                   "contributions, longest streak, releases, repositories, "
                   "language bytes and account age. No stars or followers.",
                   "", "\n".join(parts))


def gen_releases():
    repos = public_repos()
    if not repos:
        return no_data("LATEST RELEASE", "no public repositories returned")
    rows = []
    for r in repos:
        rel = [x for x in (rest(f"/repos/{USER}/{r['name']}/releases") or [])
               if not x.get("draft")]
        if rel:
            rel.sort(key=lambda x: x.get("published_at") or "", reverse=True)
            t = rel[0]
            rows.append((r["name"], t["tag_name"], (t.get("published_at") or "")[:10],
                         f"{len(t.get('assets', []))} assets, "
                         f"{'pre-release' if t.get('prerelease') else 'release'}"))
        else:
            tags = rest(f"/repos/{USER}/{r['name']}/tags?per_page=1") or []
            rows.append((r["name"], tags[0]["name"] if tags else "—", "",
                         "tagged, no release cut" if tags else "no tags yet"))

    cols = 74
    w_px = int(cols * CH + PADX * 2)
    h_px = int(PADY + LH * (len(rows) + 2) + 12)
    y = PADY + LH
    parts = [line(y, [("fr", rule("LATEST RELEASE", cols, "per repository"))], cols)]
    for i, (name, tag, when, note) in enumerate(rows):
        parts.append(line(y + LH * (i + 1),
                          [("fr", "│  "), ("hi", name.ljust(17)),
                           ("ac", tag.ljust(14)), ("dm", when.ljust(12) + note),
                           ("fr", "│")], cols))
    # Deliberately no timestamp. A generated-at stamp woulddiffer  every run, so the
    # workflow would commit every single time it fired whether anything changed
    # or not -- and those commits would then show up in the activity graph this
    # same script draws. Freshness is legible from the commit history instead.
    parts.append(line(y + LH * (len(rows) + 1),
                      [("fr", foot(cols, "published releases only"))], cols))
    return svg_doc(w_px, h_px, "Latest release per repository",
                   "The most recent published release or tag for each public "
                   "repository, with asset counts.", "", "\n".join(parts))


def gen_chain():
    """Git is already a digest-chained provenance store: every commit names its
    parent's hash. That is structurally the thing ulpf builds for logs, so walk
    the real chain and actually verify the links rather than illustrating one."""
    repos = public_repos()
    rows, links, broken = [], 0, 0
    for r in repos[:4]:
        cs = rest(f"/repos/{USER}/{r['name']}/commits?per_page=6") or []
        if len(cs) < 2:
            continue
        shas = []
        for i, c in enumerate(cs[:4]):
            shas.append(c["sha"][:7])
            if i + 1 < len(cs):
                parents = [p["sha"] for p in c.get("parents", [])]
                if cs[i + 1]["sha"] in parents:
                    links += 1
                elif parents:
                    broken += 1
        rows.append((r["name"], shas))

    if not rows:
        return no_data("INTEGRITY", "fewer than two commits available to chain")

    prose = ("every commit names its parent's digest, so a branch is a hash "
             "chain a stranger can re-verify. that is the thing ulpf builds "
             f"for logs. {links} links checked, {broken} broken.")
    cols = COLS
    words, wrapped, cur = prose.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > cols - 7:
            wrapped.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    if cur:
        wrapped.append(cur)

    nrows = 1 + len(rows) * 2 + 1 + len(wrapped) + 1
    w_px = int(cols * CH + PADX * 2)
    h_px = int(PADY + LH * (nrows + 1) + 12)
    y = PADY + LH
    verdict = "chain ok" if broken == 0 else f"{broken} BROKEN"
    parts = [line(y, [("fr", rule("INTEGRITY", cols, verdict))], cols)]
    n = 0
    for name, shas in rows:
        n += 1
        parts.append(line(y + LH * n, [("fr", "│  "), ("dm", name),
                                       ("fr", "│")], cols))
        n += 1
        cells = [("fr", "│    ")]
        for j, s in enumerate(shas):
            if j:
                cells.append(("dm", " <── "))
            cells.append(("hi", s))
        cells.append(("fr", "│"))
        parts.append(line(y + LH * n, cells, cols))
    n += 1
    parts.append(line(y + LH * n, [("fr", "│"), ("fr", "│")], cols))
    for wline in wrapped:
        n += 1
        parts.append(line(y + LH * n, [("fr", "│  "), ("dm", wline),
                                       ("fr", "│")], cols))
    n += 1
    parts.append(line(y + LH * n, [("fr", foot(cols, "verified at build time"))], cols))
    return svg_doc(w_px, h_px,
                   f"Commit chain — {links} links verified, {broken} broken",
                   f"The most recent commits in each public repository shown as a "
                   f"hash chain, each commit naming its parent. {links} links "
                   f"verified, {broken} broken.", "", "\n".join(parts))


def gen_ticker():
    repos = public_repos()
    items = []
    for r in repos:
        for c in (rest(f"/repos/{USER}/{r['name']}/commits?per_page=12") or []):
            msg = (c.get("commit", {}).get("message") or "").split("\n")[0].strip()
            if not msg:
                msg = "(no commit message)"
            if len(msg) < 2:
                msg = msg + " …"
            if len(msg) > 70:
                msg = msg[:69].rstrip() + "…"
            items.append((c["commit"]["author"]["date"], r["name"], msg))
    items.sort(reverse=True)
    items = items[:22]
    if not items:
        return no_data("RECENT COMMITS", "no commits returned for any public repo")

    seg = "".join(f"  {r} · {m}   ◦" for _, r, m in items) + "   "
    n = len(seg)
    cols = 64
    w_px = int(cols * CH + PADX * 2)
    h_px = PADY + LH * 3 + 10
    inner_x = PADX + 2 * CH
    y = PADY + LH

    newest = items[0]
    frozen = f"{newest[1]} · {newest[2]}"
    if len(frozen) > cols - 7:
        # break on a word, not mid-token -- a frozen frame that ends "has a"
        # reads as a truncation bug rather than a deliberate still
        frozen = frozen[: cols - 8].rsplit(" ", 1)[0] + " …"

    parts = [
        line(y, [("fr", rule("RECENT COMMITS", cols, "newest first"))], cols),
        f'<clipPath id="cl"><rect x="{inner_x:.1f}" y="{y + 4}" '
        f'width="{(cols - 4) * CH:.1f}" height="{LH + 6}"/></clipPath>',
        line(y + LH, [("fr", "│"), ("fr", "│")], cols),
        f'<g clip-path="url(#cl)"><g class="mv">'
        f'<text class="dm" x="{inner_x:.1f}" y="{y + LH}" '
        f'textLength="{2 * n * CH:.1f}" lengthAdjust="spacing">'
        f'{esc(seg)}{esc(seg)}</text></g></g>',
        # A stopped marquee freezes at an arbitrary character and reads as a
        # broken image. Reduced motion gets a purpose-built frame instead: the
        # newest commit, whole, ending where it should.
        '<g class="frz">'
        + line(y + LH, [("fr", "│  "), ("dm", frozen), ("fr", "│")], cols)
        + '</g>',
        line(y + LH * 2,
             [("fr", foot(cols, f"{len(items)} commits across "
                                f"{len(repos)} repositories"))], cols),
    ]

    css = f"""
/* One of only two continuously-animating elements on the whole profile. The
   strip is rendered twice back to back and translated by exactly one copy's
   width, so the loop has no visible seam. textLength pins that width to the
   grid, which is what keeps the seam invisible on a font whose advance is
   not the CH this file assumes. */
@keyframes roll{{from{{transform:translateX(0)}}to{{transform:translateX(-{n * CH:.1f}px)}}}}
.mv{{animation:roll {max(30, n // 8)}s linear infinite}}
.frz{{display:none}}
@media (prefers-reduced-motion: reduce){{
  .mv{{display:none}} .frz{{display:block}}
}}
"""
    return svg_doc(w_px, h_px, "Recent commits",
                   "A scrolling ticker of the most recent commit subjects across "
                   "the public repositories, newest first.", css, "\n".join(parts))


LANG_CLASS = {
    "Rust": "rust", "TypeScript": "gold", "Python": "plum",
    "JavaScript": "gold", "Svelte": "ac", "Shell": "dm", "CSS": "dm",
    "HTML": "dm", "Dockerfile": "dm", "PowerShell": "dm",
}


def _row_svg(stack, tag, state, cls, alt):
    """One compact metadata strip: stack tokens colour-coded by language, then
    the release state. Colour means something here -- language identity and
    release maturity -- rather than decorating.

    This is an SVG rather than markdown backticks because a code span picks up
    GitHub's grey default styling, which drags a generic dev-portfolio look into
    a page that is deliberately warm phosphor throughout.
    """
    CH, FS, H = 7.0, 12, 20
    cells = []
    for i, (name, lcls) in enumerate(stack):
        if i:
            cells.append(("dm", " · "))
        cells.append((lcls, name))
    cells.append(("dm", "   "))
    cells.append((cls, f"■ {tag}" if tag else "■"))
    cells.append(("dm", f" {state}"))

    text = "".join(t for _, t in cells)
    w = int(len(text) * CH) + 8
    spans = "".join(f'<tspan class="{c}">{esc(t)}</tspan>' for c, t in cells)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {H}" '
            f'width="{w}" height="{H}" role="img" xml:space="preserve">'
            f'<title>{esc(alt)}</title>'
            f'<style>{BASE_CSS}text{{font-size:{FS}px}}</style>'
            f'<text x="2" y="14" textLength="{len(text)*CH:.1f}" '
            f'lengthAdjust="spacing">{spans}</text></svg>')


def gen_rows():
    """A metadata strip per public repository. Scales by construction: adding a
    repo adds a file, and the README grows by one line. Nothing about the layout
    degrades at six or eight entries because each entry is independent."""
    repos = public_repos()
    if not repos:
        raise RuntimeError("no public repositories returned")

    made = []
    for r in repos:
        langs = rest(f"/repos/{USER}/{r['name']}/languages") or {}
        # Byte count alone surfaces build and config noise -- Shell scripts and
        # a CSS file are not what the project is written in. Drop those, and
        # drop JavaScript when TypeScript is present since it is almost always
        # config and generated output rather than a second language.
        NOISE = {"Shell", "PowerShell", "CSS", "HTML", "Dockerfile", "Makefile",
                 "Batchfile", "SCSS"}
        langs = {k: v for k, v in langs.items() if k not in NOISE}
        if "TypeScript" in langs:
            langs.pop("JavaScript", None)
        top = sorted(langs.items(), key=lambda kv: -kv[1])[:3]
        stack = [(k.lower(), LANG_CLASS.get(k, "dm")) for k, _ in top] or [("—", "dm")]

        rel = [x for x in (rest(f"/repos/{USER}/{r['name']}/releases") or [])
               if not x.get("draft")]
        if rel:
            rel.sort(key=lambda x: x.get("published_at") or "", reverse=True)
            t = rel[0]
            tag, state = t["tag_name"], ("pre-release" if t.get("prerelease") else "released")
            cls = "rust" if t.get("prerelease") else "gold"
        else:
            tags = rest(f"/repos/{USER}/{r['name']}/tags?per_page=1") or []
            if tags:
                tag, state, cls = tags[0]["name"], "tagged, no release", "ac"
            else:
                tag, state, cls = "", "no release yet", "deep"

        alt = (f"{r['name']}: " + ", ".join(k for k, _ in stack)
               + f" — {tag + ' ' if tag else ''}{state}")
        svg = _row_svg(stack, tag, state, cls, alt)
        path = os.path.join(ASSETS, f"row-{r['name']}.svg")
        write_atomic(path, svg, f"row-{r['name']}")
        made.append(r["name"])
    return made


def no_data(title, reason):
    """A legible frame. Never an empty file -- <img> renders that as a broken
    image icon, which is worse on the page than stale or absent data."""
    cols = 62
    w_px = int(cols * CH + PADX * 2)
    h_px = PADY + LH * 5 + 10
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    parts = [
        f'<text class="fr" x="{PADX}" y="{PADY+LH}">{esc(rule(title, cols, "no data"))}</text>',
        f'<text class="fr" x="{PADX}" y="{PADY+LH*2}">{esc(row("", cols))}</text>',
        f'<text x="{PADX}" y="{PADY+LH*3}"><tspan class="fr">│  </tspan>'
        f'<tspan class="ac">{esc(reason[:cols-8])}</tspan></text>',
        f'<text class="fr" x="{PADX + (cols-1)*CH:.1f}" y="{PADY+LH*3}">│</text>',
        f'<text class="fr" x="{PADX}" y="{PADY+LH*4}">{esc(row("", cols))}</text>',
        f'<text class="fr" x="{PADX}" y="{PADY+LH*5}">{esc(foot(cols, stamp))}</text>',
    ]
    return svg_doc(w_px, h_px, f"{title} — no data",
                   f"No data available: {reason}", "", "\n".join(parts))


# ── write ───────────────────────────────────────────────────────────────

def validate(svg, name):
    if not svg or len(svg) < 300:
        raise ValueError(f"{name}: suspiciously small ({len(svg)} bytes)")
    low = svg.lower()
    # Refuse a doctype or entity declaration before parsing. These are the
    # vector for XXE and billion-laughs, and an SVG we generate ourselves has
    # no business carrying either -- so reject rather than harden the parser.
    if "<!doctype" in low or "<!entity" in low:
        raise ValueError(f"{name}: doctype/entity declaration in generated SVG")
    ET.fromstring(svg)                                    # must parse as XML
    if "<script" in low:
        raise ValueError(f"{name}: contains <script>")
    if "var(--" in svg:
        raise ValueError(f"{name}: CSS custom properties render black in resvg")
    if "@font-face" in svg or "url(http" in low:
        raise ValueError(f"{name}: external font reference")
    for tok in ("http://", "https://"):
        for hit in [s for s in svg.split(tok)[1:]]:
            if not hit.startswith("www.w3.org"):
                raise ValueError(f"{name}: external URL {tok}{hit[:40]}")
    if "prefers-color-scheme" not in svg:
        raise ValueError(f"{name}: no prefers-color-scheme block")
    if "@keyframes" in svg and "prefers-reduced-motion" not in svg:
        raise ValueError(f"{name}: animates with no prefers-reduced-motion block")


def write_atomic(path, svg, name):
    validate(svg, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    os.replace(tmp, path)                                 # atomic on POSIX+NTFS


GENERATORS = [
    ("hero",     "hero.svg",     gen_hero),
    ("activity", "activity.svg", gen_activity),
    ("stats",    "stats.svg",    gen_stats),
    ("chain",    "chain.svg",    gen_chain),
]


def main():
    os.makedirs(ASSETS, exist_ok=True)
    only = sys.argv[1:]
    ok, failed = [], []
    if not only or "badges" in only:
        try:
            made = gen_badges()
            ok.append(f"badges ({len(made)})")
            print(f"ok      {'badges':9} -> {len(made)} files",
                  flush=True)
        except Exception:
            failed.append("badges")
            print("FAILED  badges    -> kept last committed badge SVGs", flush=True)
            traceback.print_exc()
    for name, fname, fn in GENERATORS:
        if only and name not in only:
            continue
        path = os.path.join(ASSETS, fname)
        try:
            svg = fn()
            write_atomic(path, svg, name)
            ok.append(f"{name} ({len(svg):,} B)")
            print(f"ok      {name:9} -> assets/{fname}  {len(svg):,} B", flush=True)
        except Exception:
            failed.append(name)
            existing = "kept last committed file" if os.path.exists(path) else "NO existing file to fall back on"
            print(f"FAILED  {name:9} -> {existing}", flush=True)
            traceback.print_exc()
        finally:
            for junk in (path + ".tmp",):
                if os.path.exists(junk):
                    os.remove(junk)

    print(f"\ngenerated {len(ok)}  failed {len(failed)}")
    if failed:
        print(f"::error::generators failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
