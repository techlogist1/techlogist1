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

# Monochrome: white and greys on near-black. Literal colours in the base rules,
# overridden by the light media block -- never CSS custom properties, which resvg
# drops to black. Warm phosphor was tried and rejected; see CLAUDE.md.
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

def frame_css(nslots, cycle, phases):
    """N discrete slots sharing one keyframe, separated by animation-delay.

    One shared keyframe plus a per-group delay costs a fraction of what N
    separate keyframe blocks would, and the hard cut at the slot boundary is
    what keeps this a substitution rather than a crossfade -- an interpolated
    blend between two frames would make the middle of the transformation a
    smear instead of a state you can read.

    Delays are always negative so the cycle is already under way at t=0.
    A positive delay would leave every group in its base state until its first
    turn came round, which means the finished frame flashes on load.
    """
    frac = 100.0 / nslots
    css = [f"""
@keyframes slot{{
  0%{{opacity:1}} {frac:.4f}%{{opacity:1}}
  {frac + 0.0001:.4f}%{{opacity:0}} 100%{{opacity:0}}
}}"""]
    for cls, delay in phases:
        d = delay % cycle - cycle
        # No opacity in this rule. Each group's base state is carried by its
        # own presentation attribute, and a CSS declaration would outrank it --
        # which rasterised the whole panel blank, since resvg runs no keyframes.
        # Rasterise the animated file, not only the stills.
        css.append(f".{cls}{{animation:slot {cycle}s linear "
                   f"{d:.3f}s infinite}}")
    return "\n".join(css)


# Two true sentences about how this gets built, interleaved character by
# character. Read as one line they are noise; the characters then separate into
# the two statements that were there the whole time. Nothing is ever added and
# nothing is ever removed -- every character on screen in the last frame is on
# screen in the first one, in a different place.
#
# This is deliberately NOT about any one repository. An earlier hero animated a
# log line being normalised, which was the easiest thing on the account to draw
# and turned the whole page into an argument for ulpf. A pipeline is that same
# shape wearing a costume, so this is not a pipeline: it is a rearrangement.
#
# Hand-authored, and nothing on this panel claims to be live. The live panel is
# IN FLIGHT below. Giving the hero a data source would put a failure surface on
# the one image that must never break.
SAY_A = "I decide what it should do      "
SAY_B = "Claude Code does the typing     "
ROUNDS = 6                     # round 0 fully interleaved, round 5 separated
HOLD = 4                       # slots the separated pair sits still
SLOTS = ROUNDS + HOLD


def _unshuffle(stage):
    """The interleaved sequence after `stage` merge rounds.

    One merge round per step, NOT a de-interleave -- de-interleaving a block is
    not the inverse of interleaving it, and using it produces frames that never
    resolve. Two adjacent blocks that are each already [A-part, B-part] merge
    into one such block by swapping their middle two quarters. That is what
    makes the intermediate states real: runs of each sentence appear and grow,
    so the middle of the transformation is legible instead of being a wipe.
    """
    seq = [x for pair in zip([(0, c) for c in SAY_A], [(1, c) for c in SAY_B])
           for x in pair]
    n, b = len(seq), 4
    for _ in range(min(stage, ROUNDS - 1)):
        q, out = b // 4, []
        for s in range(0, n, b):
            blk = seq[s:s + b]
            out += blk[:q] + blk[2 * q:3 * q] + blk[q:2 * q] + blk[3 * q:]
        seq, b = out, b * 2
    return seq


def _say_cells(half, stage):
    """One of the two rows at one stage, run-length coloured by source.

    The colour is the mechanism made visible rather than decoration: a
    character drawn in .hi came from the first sentence and one in .dm from the
    second, so even the fully interleaved frame reads as two things tangled
    together rather than as noise.
    """
    seq = _unshuffle(stage)
    part = seq[:len(SAY_A)] if half == 0 else seq[len(SAY_A):]
    cells, cur, buf = [("fr", "│    ")], None, ""
    for src, ch in part:
        cls = "hi" if src == 0 else "dm"
        if cls != cur:
            if buf:
                cells.append((cur, buf))
            cur, buf = cls, ch
        else:
            buf += ch
    if buf:
        cells.append((cur, buf))
    cells.append(("fr", "│"))
    return cells


def gen_hero():
    """The hero. One line of interleaved noise separating into two statements.

    What it is about. Nothing on this page may be an argument for a single
    repository, and the previous hero -- a log line being normalised -- made the
    whole page one. This is true of the author instead: the work here is deciding
    what a thing should do, and the typing is driven rather than done. It is also
    true of the mechanism, which is the point of choosing it: two things that
    looked like one noisy thing were always two, and every character needed to
    read them was on screen from the first frame.

    Why this one won. Two rivals were built and rasterised at the real 847px
    column first. A watch escapement -- continuous torque becoming a counted
    beat -- was defeated by its own physics at this frame budget: to see a count
    change you need many beats, and many beats per loop makes the balance swing
    too fast to draw discretely, so twelve frames showed a dot sliding along a
    line and a number moving twice. A pruned decision tree read as a bullet list
    being crossed off, and spent the hero arguing against three alternatives.

    Deliberately NOT: typewriter reveal, matrix rain, blinking cursor, glow
    pulse, scanline sweep, generic fade-in, rule 110. Nothing accumulates here
    and nothing is revealed -- the full character set is present in every frame
    and only its arrangement changes, which is what makes this a different thing
    from a text reveal.
    """
    art = [
        [("fr", "┌─ "), ("hi", "LOKAVYA SINGH"), ("fr", " "),
         ("fr", "─" * 29), ("dm", " JAIPUR · IN "), ("fr", "─┐")],
        [("fr", "│"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "),
         ("hi", "Desktop apps that run on your own computer"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("hi", "and keep your data there."),
         ("fr", "│")],
        [("fr", "│"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("dm", "> "), ("hi", "flint   "),
         ("body", "a timer whose every mode is a plugin"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("dm", "> "), ("hi", "vysted  "),
         ("body", "a finance terminal an AI agent can drive"), ("fr", "│")],
        [("fr", "│"), ("dm", "   "), ("dm", "> "), ("hi", "ulpf    "),
         ("body", "a log parser that keeps the original bytes"), ("fr", "│")],
        [("fr", "│"), ("fr", "│")],
    ]
    head = "├─ nothing is added and nothing is removed "
    art.append([("fr", head + "─" * (COLS - len(head) - 2) + "─┤")])

    ty, LH2 = 44, 20
    rows = [line(ty + i * LH2, cells, COLS) for i, cells in enumerate(art)]
    base = len(art)
    rows.append(line(ty + base * LH2, [("fr", "│"), ("fr", "│")], COLS))

    # Guard, not decoration: if the merge rounds ever stop separating cleanly
    # the animation resolves into gibberish, which is worse than not animating.
    # Raising here leaves the last good hero.svg committed and turns the run red.
    if "".join(c for _, c in _unshuffle(ROUNDS - 1)[:len(SAY_A)]) != SAY_A:
        raise RuntimeError("unshuffle does not separate; hero would be gibberish")

    cycle, phases = 9.0, []
    for half in range(2):
        ry = ty + (base + 1 + half) * LH2
        for sl in range(SLOTS):
            cls = f"s{half}{sl}"
            # Base state is the LAST slot, the separated pair. A renderer with
            # no animation support, and reduced motion, both land on the two
            # readable sentences rather than on a frame of noise.
            op = "" if sl == SLOTS - 1 else ' opacity="0"'
            rows.append(f'<g class="{cls}"{op}>'
                        + line(ry, _say_cells(half, sl), COLS) + "</g>")
            phases.append((cls, sl * cycle / SLOTS))

    n = base + 3
    rows.append(line(ty + n * LH2, [("fr", "│"), ("fr", "│")], COLS))
    rows.append(line(ty + (n + 1) * LH2,
                     [("fr", foot(COLS, "the characters only change places"))],
                     COLS))

    css = (frame_css(SLOTS, cycle, phases)
           + "\n@media (prefers-reduced-motion: reduce){"
           + "".join(f".s{half}{sl}{{animation:none;opacity:0}}"
                     for half in range(2) for sl in range(SLOTS - 1))
           + "".join(f".s{half}{SLOTS-1}{{animation:none;opacity:1}}"
                     for half in range(2))
           + "}")

    w_px = int(COLS * CH + PADX * 2)
    h_px = ty + (n + 2) * LH2 + 18
    return svg_doc(
        w_px, h_px,
        "Lokavya Singh — desktop apps that run on your own computer",
        "A terminal frame. Two sentences -- \"I decide what it should do\" and "
        "\"Claude Code does the typing\" -- are interleaved character by "
        "character and separate back into two readable lines; nothing is added "
        "or removed at any point. Three projects: flint, a timer whose every "
        "mode is a plugin; vysted, a finance terminal an AI agent can drive; "
        "ulpf, a log parser that keeps the original bytes.",
        css, "\n".join(rows))


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
            state, filled = ("tagged" if tags else "in progress"), "none"
        write_atomic(os.path.join(ASSETS, f"rel-{r['name']}.svg"),
                     _release_badge(tag, state, filled), f"rel-{r['name']}")
        made.append(f"rel-{r['name']}")
    return made


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

    # Languages as an unordered set, not a leaderboard. Two rows reading
    # "Rust, bytes" and "TypeScript, bytes" ranked one repository's language
    # above the others' and tilted the whole panel toward the Rust project --
    # and a byte count per language is in any case a second copy of the primary
    # language GitHub already prints on every pinned card. Alphabetical, so the
    # order carries no claim.
    # A tenth of all bytes, not a top-N and not a lower bar. At 4% Shell
    # qualified by 294 bytes out of 5.3 million, so one commit could add or drop
    # a language from the panel with nothing on the page explaining why; a tenth
    # separates the three languages these projects are actually written in from
    # the tooling around them by more than an order of magnitude.
    tot = sum(langs.values()) or 1
    keep = sorted(k for k, v in langs.items() if v * 10 >= tot)
    while len(" · ".join(keep)) > 40 and len(keep) > 1:
        keep.remove(min(keep, key=lambda k: langs[k]))     # drop the smallest
    langline = " · ".join(keep)

    rows = [
        ("commits, public repos", f"{commits:,}"),
        ("lines added, public repos", f"{added:,}"),
        ("contributions, 365 days", f"{cal_total:,}"),
        ("longest daily streak", f"{best} days"),
        ("releases published", f"{releases}"),
        ("public repositories", f"{len(repos)}"),
        ("main languages", langline),
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
    # No footer naming what is absent. An earlier version closed this panel
    # with "no stars, no followers", which took something no visitor had noticed
    # and set it in monospace at the bottom of the page. Absence is invisible
    # until you announce it.
    parts.append(line(y + LH * (len(rows) + 1),
                      [("fr", foot(cols, "counted from the API at build time"))], cols))
    return svg_doc(w_px, h_px, "By the numbers",
                   "Real counts from the GitHub API: commits, lines added, "
                   "contributions, longest streak, releases published, public "
                   f"repositories, the languages used ({langline}) and account "
                   "age.", "", "\n".join(parts))


def gen_chain():
    """Git is already a digest-chained provenance store: every commit names its
    parent's hash. Walk the real chain and actually verify the links rather than
    illustrating one.

    This panel used to close by saying the chain was "the thing ulpf builds for
    logs", which made it an argument for one repository sitting in the middle of
    a page that is meant to hold three. The mechanism is git's, every repository
    listed here is in it equally, and the panel now says only what it checked.
    """
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
        return no_data("PROVENANCE", "fewer than two commits available to chain")

    prose = ("every commit names its parent's digest, so each branch above is a "
             "hash chain a stranger can re-walk without trusting this page. "
             f"{links} links checked here, {broken} broken.")
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
    parts = [line(y, [("fr", rule("PROVENANCE", cols, verdict))], cols)]
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
                   f"Provenance — {links} links verified, {broken} broken",
                   f"The most recent commits in each public repository shown as a "
                   f"hash chain, each commit naming its parent. {links} links "
                   f"verified, {broken} broken.", "", "\n".join(parts))


def gen_inflight():
    """Commits on the default branch that are ahead of the newest tag.

    Why this and not something contribution-shaped. Checked against the live
    profile page rather than assumed: GitHub already renders a contribution
    calendar with per-day counts, an "Activity overview" radar giving the
    commit/PR/issue/review split, a month-by-month contribution timeline, and a
    pinned card per repo carrying its primary language, star count and fork
    count. Anything built from contributions, languages, stars or forks would be
    a second copy of something sitting a screen below it. Release and tag state
    is the one substantial thing about these repositories that appears nowhere
    on the profile page.

    And it is live in the sense that matters -- ulpf moved 157 commits ahead of
    its newest tag inside two days, and the count resets to zero the moment a
    release is cut, so the panel changes shape on a real event rather than
    drifting by one a week.

    `ahead_by` is used rather than len(commits): the compare endpoint caps its
    commit list at 250 and its file list at 300, so summing the returned diff
    would silently report a floor as if it were a total. vysted-terminal
    returns exactly 250 files, which is what that cap looks like from outside.
    """
    repos = public_repos()
    rows, newest, total = [], "", 0
    for r in repos:
        rel = [x for x in (rest(f"/repos/{USER}/{r['name']}/releases") or [])
               if not x.get("draft")]
        rel.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        tags = rest(f"/repos/{USER}/{r['name']}/tags?per_page=1") or []
        base = rel[0]["tag_name"] if rel else (tags[0]["name"] if tags else None)
        if not base:
            # A repository with no tag has nothing to say on this panel, so it
            # is left off rather than given a row that reports an absence.
            continue
        cmp_ = rest(f"/repos/{USER}/{r['name']}/compare/{base}...{r['default_branch']}")
        if not cmp_:
            continue
        ahead = cmp_.get("ahead_by", 0)
        total += ahead
        for c in (cmp_.get("commits") or []):
            d = c.get("commit", {}).get("author", {}).get("date", "")[:10]
            newest = max(newest, d)
        rows.append((r["name"], base, ahead))

    if not rows:
        return no_data("IN FLIGHT", "no tagged repository to compare against")

    rows.sort(key=lambda x: -x[2])
    peak = max(a for _, _, a in rows) or 1
    BAR = 16
    cols = COLS
    w_px = int(cols * CH + PADX * 2)
    h_px = int(PADY + LH * (len(rows) + 4) + 12)
    y = PADY + LH

    parts = [line(y, [("fr", rule("IN FLIGHT", cols,
                                  f"{total} commits since the last tag"))], cols),
             line(y + LH, [("fr", "│"), ("fr", "│")], cols)]

    bars = []
    for i, (name, tag, ahead) in enumerate(rows):
        cells = [("fr", "│  "), ("hi", name.ljust(17))]
        if ahead:
            fill = max(1, round(BAR * ahead / peak))
            # Only U+2588 and U+2591 are used for the bar. A run of the lower
            # block glyphs (U+2581..U+2587) falls back to a face with a
            # different advance, and lengthAdjust="spacing" cannot correct a
            # glyph that is itself the wrong width -- a 46-long run of them
            # pushed a panel's closing rule outside the frame when this was
            # tried. Measured by rasterising, not reasoned about.
            # A DISCRETE meter, not a solid bar, and that is forced rather
            # than chosen. lengthAdjust="spacing" spreads the row's width
            # correction across every inter-glyph gap, so a run of U+2588 comes
            # out as blocks separated by ragged sub-pixel gaps that read as a
            # rendering fault rather than as a bar. Squares with deliberate gaps
            # absorb that correction invisibly, and U+25A0 is already the release
            # badges' glyph, so the page's vocabulary stays consistent.
            #
            # The lower block glyphs U+2581..U+2587 are worse: they fall back to
            # a face with a different advance, and lengthAdjust cannot correct a
            # glyph that is itself the wrong width -- a 46-long run of them
            # pushed a panel's closing rule outside its frame.
            cells += [("hi", "■" * fill), ("fr", "·" * (BAR - fill)),
                      ("hi", f"{ahead:>5}")]
        else:
            # Zero ahead is the good end of this scale: everything that has
            # been built is downloadable. Say that, rather than printing a 0
            # next to a 157 and letting the small number do the talking.
            cells += [("dm", "released in full".ljust(BAR)), ("dm", "     ")]
        cells += [("dm", "  " + tag.ljust(12)), ("fr", "│")]
        bars.append(line(y + LH * (i + 2), cells, cols))
    parts.append('<g class="bars">' + "".join(bars) + "</g>")

    parts.append(line(y + LH * (len(rows) + 2), [("fr", "│"), ("fr", "│")], cols))
    parts.append(line(y + LH * (len(rows) + 3),
                      [("fr", foot(cols, f"newest commit {newest}"))], cols))

    css = """
/* Base state is the finished chart; the keyframe supplies only the entrance,
   via fill-mode backwards. A renderer with no animation support shows the bars
   complete rather than blank, and reduced motion is then one line. Animates
   once and settles -- the hero is the page's only continuous motion. */
.bars{clip-path:none}
@keyframes grow{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
.bars{animation:grow 1.4s cubic-bezier(.25,.6,.25,1) .2s backwards}
@media (prefers-reduced-motion: reduce){ .bars{animation:none} }
"""
    return svg_doc(w_px, h_px,
                   f"In flight — {total} commits since the last tag",
                   "Per repository, the number of commits on the default branch "
                   "that are ahead of its newest tag, drawn as a bar. "
                   + "; ".join(f"{n}: {a} ahead of {t}" if a
                               else f"{n}: released in full at {t}"
                               for n, t, a in rows) + ".",
                   css, "\n".join(parts))


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
    ("inflight", "inflight.svg", gen_inflight),
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
