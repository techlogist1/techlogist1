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
FS = 13          # font-size, px
CH = 7.8         # character advance at FS for a 0.6-ratio monospace face
LH = 16          # line advance; ~1.23em, near where box-drawing tiles
PADX, PADY = 22, 26

FONT = ('ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,'
        '"Cascadia Mono","DejaVu Sans Mono","Liberation Mono",monospace')

# Warm phosphor. Literal colours in the base rules, overridden by the light
# media block -- never CSS custom properties, which resvg drops to black.
BASE_CSS = f"""
.glass{{fill:#15110C}}
.edge{{fill:none;stroke:#241B12;stroke-width:1}}
text{{font-family:{FONT};font-size:{FS}px;white-space:pre;fill:#E8A33D}}
.fr{{fill:#B07D2A}} .hi{{fill:#F7E7C6}} .ac{{fill:#9B3A2E}} .dm{{fill:#7A5A2E}}
.q0{{fill:#3A2E1E}} .q1{{fill:#8A6224}} .q2{{fill:#C08A2E}} .q3{{fill:#E8A33D}} .q4{{fill:#F7E7C6}}
.scan{{opacity:.05}}
.vig{{opacity:1}}
@media (prefers-color-scheme: light){{
  .glass{{fill:#F2E7D3}}
  .edge{{stroke:#DCC9A8}}
  text{{fill:#8A4F14}}
  .fr{{fill:#9A6E24}} .hi{{fill:#2B1D0E}} .ac{{fill:#8C2F27}} .dm{{fill:#A08769}}
  .q0{{fill:#DFCDAC}} .q1{{fill:#C9A263}} .q2{{fill:#A9741F}} .q3{{fill:#8A4F14}} .q4{{fill:#4A2A0A}}
  .scan{{opacity:.028}}
  .vig{{opacity:.18}}
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
    LABEL = 8                        # "|  Mon  "
    cols = LABEL + ncols * 2 + 1

    ruler = [" "] * (ncols * 2)
    seen = set()
    for i, w in enumerate(weeks):
        d0 = w["contributionDays"][0]["date"]
        mo = d0[:7]
        m = datetime.strptime(d0, "%Y-%m-%d")
        if mo not in seen and m.day <= 7 and i < ncols - 2:
            seen.add(mo)
            for j, c in enumerate(m.strftime("%b")):
                if i * 2 + j < len(ruler):
                    ruler[i * 2 + j] = c

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
        cells = [("fr", "│"), ("dm", "  " + DAYNAME[wd].ljust(3) + "  ")]
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
            buf += ch + " "
        if buf:
            runs.append((cur, buf))
        cells += runs
        cells.append(("fr", "│"))
        grid.append(line(y + LH * (wd + 2), cells, cols))
    parts.append('<g class="grid">' + "".join(grid) + "</g>")

    legend = f"  {active} active days   peak {peak} in a day   less "
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
        ("commits, public repositories", f"{commits:,}"),
        ("lines added, public repositories", f"{added:,}"),
        ("contributions, last 365 days", f"{cal_total:,}"),
        ("longest daily streak", f"{best} days"),
        ("releases published", f"{releases}"),
        ("public repositories", f"{len(repos)}"),
        ("Rust, bytes on disk", kb(langs.get("Rust", 0))),
        ("TypeScript, bytes on disk", kb(langs.get("TypeScript", 0))),
        ("account opened", f"{opened:%b %Y} ({yrs:.1f} yrs)"),
    ]

    cols = 62
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
        for i, c in enumerate(cs[:5]):
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
    cols = 78
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
    cols = 108
    w_px = int(cols * CH + PADX * 2)
    h_px = PADY + LH * 3 + 10
    inner_x = PADX + 2 * CH
    y = PADY + LH

    parts = [
        line(y, [("fr", rule("RECENT COMMITS", cols, "newest first"))], cols),
        f'<clipPath id="cl"><rect x="{inner_x:.1f}" y="{y + 4}" '
        f'width="{(cols - 4) * CH:.1f}" height="{LH + 6}"/></clipPath>',
        line(y + LH, [("fr", "│"), ("fr", "│")], cols),
        f'<g clip-path="url(#cl)"><g class="mv">'
        f'<text class="dm" x="{inner_x:.1f}" y="{y + LH}" '
        f'textLength="{2 * n * CH:.1f}" lengthAdjust="spacing">'
        f'{esc(seg)}{esc(seg)}</text></g></g>',
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
@media (prefers-reduced-motion: reduce){{ .mv{{animation:none}} }}
"""
    return svg_doc(w_px, h_px, "Recent commits",
                   "A scrolling ticker of the most recent commit subjects across "
                   "the public repositories, newest first.", css, "\n".join(parts))


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
    ("activity", "activity.svg", gen_activity),
    ("stats",    "stats.svg",    gen_stats),
    ("releases", "releases.svg", gen_releases),
    ("chain",    "chain.svg",    gen_chain),
    ("ticker",   "ticker.svg",   gen_ticker),
]


def main():
    os.makedirs(ASSETS, exist_ok=True)
    only = sys.argv[1:]
    ok, failed = [], []
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
