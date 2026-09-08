#!/usr/bin/env python3
"""Draw every plate in the notebook, and write the entries that grow with it.

The page is a naturalist's field notebook kept in the Grinnell system. What
makes that conceit hold rather than decorate is that it grows: a species account
is a catalog entry, and a real notebook runs to hundreds of them without ever
changing shape. So nothing here is written for three repositories. Every section
that enumerates work is built for an arbitrary count, derived from the API, and
the README's own entry blocks are rewritten in place by this script.

Open-sourcing a new project therefore takes no edit to this repository at all.

Standing rule, absolute: no plate, caption, title, desc or alt string on this
page names a tool, an assistant, or how the code was written. See CLAUDE.md.
"""
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# The plates are full of box-drawing and a numero sign; a Windows console at
# cp1252 would raise on the progress lines alone, which is no reason to fail a
# run that produced good files.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import caliper                                             # noqa: E402
from r3d import paths_to_d                                 # noqa: E402

try:
    import tomllib                                         # 3.11+, stdlib
except ModuleNotFoundError:                                # pragma: no cover
    tomllib = None

USER = "techlogist1"
API = "https://api.github.com"
GQL = "https://api.github.com/graphql"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DATA = os.path.join(ROOT, "data")
README = os.path.join(ROOT, "README.md")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

# -- grid ---------------------------------------------------------------
FS = 14          # font-size, px
CH = 8.4         # character advance at FS for a 0.6-ratio monospace face
LH = 16          # line advance. Measured, not chosen: at FS 14 the box-drawing
                 # glyphs tile with 100% vertical continuity at 16 and leave
                 # visible gaps at 17, which is what the page ran at before.
PADX, PADY = 22, 26
COLS = 61        # every plate shares one width, so the page reads as one
                 # object rather than a stack of differently-scaled widgets

FONT = ('ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,'
        '"Cascadia Mono","DejaVu Sans Mono","Liberation Mono",monospace')

# -- palette ------------------------------------------------------------
# 90s vintage warmth: ivory, aged brass and oxblood on warm near-black. Every
# value was checked with a contrast ratio against GitHub's own page grounds
# (#0d1117 dark, #ffffff light), because the previous warm pass was rejected
# partly for accents landing under 3:1 and this one must not repeat it.
#
#   dark   body 10.5:1  hi 15.6:1  dm 6.6:1  fr 3.0:1  ox 5.2:1
#   light  body 11.0:1  hi 16.7:1  dm 5.2:1  fr 3.1:1  ox 8.1:1
#
# OXBLOOD MEANS EXACTLY ONE THING: a collector's number. It marks a figure that
# was counted and that a reader can go and re-check. It is never used for
# emphasis, for a language, for release state, or in the hero -- the caliper
# reading wanted it and did not get it. If a second thing wants it, the answer
# is no. Its luminance sits close to the body ink by design, so the meaning is
# carried by the No. glyph independently and the colour only reinforces it.
DK = dict(gl="#16130F", ed="#3A3125", tx="#CEC2AD", hi="#F3EBDB",
          dm="#AA9877", fr="#6E6047", ox="#CF6A56")
LT = dict(gl="#FAF6EC", ed="#D6C9AF", tx="#3F362A", hi="#1B1610",
          dm="#75664F", fr="#9C8B6E", ox="#8E241A")

BASE_CSS = """
.glass{fill:%(gl)s}
.edge{fill:none;stroke:%(ed)s;stroke-width:1}
text{font-family:%(font)s;font-size:%(fs)dpx;white-space:pre;fill:%(tx)s}
.fr{fill:%(fr)s} .hi{fill:%(hi)s} .dm{fill:%(dm)s} .ox{fill:%(ox)s} .tx{fill:%(tx)s}
.ln{fill:none;stroke:%(tx)s;stroke-width:1.15;stroke-linecap:round;stroke-linejoin:round}
.q0{fill:%(ed)s} .q1{fill:%(fr)s} .q2{fill:%(dm)s} .q3{fill:%(tx)s} .q4{fill:%(hi)s}
@media (prefers-color-scheme: light){
  .glass{fill:%(lgl)s}
  .edge{stroke:%(led)s}
  text{fill:%(ltx)s}
  .fr{fill:%(lfr)s} .hi{fill:%(lhi)s} .dm{fill:%(ldm)s} .ox{fill:%(lox)s} .tx{fill:%(ltx)s}
  .ln{stroke:%(ltx)s}
  .q0{fill:%(led)s} .q1{fill:%(lfr)s} .q2{fill:%(ldm)s} .q3{fill:%(ltx)s} .q4{fill:%(lhi)s}
}
""" % dict(font=FONT, fs=FS,
           gl=DK["gl"], ed=DK["ed"], tx=DK["tx"], hi=DK["hi"], dm=DK["dm"],
           fr=DK["fr"], ox=DK["ox"],
           lgl=LT["gl"], led=LT["ed"], ltx=LT["tx"], lhi=LT["hi"],
           ldm=LT["dm"], lfr=LT["fr"], lox=LT["ox"])


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def svg_doc(w, h, title, desc, css, body, defs=""):
    # xml:space="preserve" on the root is load-bearing for every plate: the CSS
    # white-space:pre property is honoured by browsers but not by resvg's text
    # layout, and without the attribute every run of padding spaces collapses to
    # one and the ASCII grid stops closing.
    d = "<defs>" + defs + "</defs>" if defs else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'width="%d" height="%d" role="img" aria-labelledby="t d" '
        'xml:space="preserve">\n'
        '<title id="t">%s</title>\n<desc id="d">%s</desc>\n'
        '<style>%s%s</style>%s\n'
        '<rect class="glass" width="%d" height="%d" rx="8"/>\n%s\n'
        '<rect class="edge" x=".5" y=".5" width="%d" height="%d" rx="8"/>\n'
        '</svg>\n'
        % (w, h, w, h, esc(title), esc(desc), BASE_CSS, css, d, w, h, body,
           w - 1, h - 1))


def line(y, cells, cols=COLS, cls=""):
    """One full-width row as a single <text>, pinned to exactly cols*CH.

    Everything inside a row MUST go through here. Mixing a string-rendered run
    with a separately-positioned element makes the two disagree the moment the
    viewer's monospace advance differs from CH -- Consolas is 0.55em, DejaVu and
    SF Mono 0.60em -- so textLength pins the row to the grid instead of trusting
    the font. Padding is folded into the second-to-last cell so it stays inside
    a styled tspan; emitted bare, resvg loses it and the closing rule collapses
    back against the content.
    """
    total = sum(len(t) for _, t in cells)
    pad = cols - total
    if pad > 0:
        i = -2 if len(cells) > 1 else -1
        cells = list(cells)
        c, t = cells[i]
        cells[i] = (c, t + " " * pad)
    elif pad < 0 and len(cells) > 1:
        c, t = cells[-2]
        if len(t) > -pad:
            cells = cells[:-2] + [(c, t[:pad])] + cells[-1:]
    # EVERY run is wrapped, including unclassed ones. Emitted as a bare run the
    # padding is lost by resvg, the row's natural width collapses, and
    # lengthAdjust then spreads the surviving glyphs across the full width --
    # which is what "d e p o s i t e d  p u b l i c l y" looks like on a plate.
    # An unclassed tspan still inherits the text fill, so this costs nothing.
    spans = "".join(
        ('<tspan class="%s">%s</tspan>' % (c, esc(t))) if c
        else ("<tspan>%s</tspan>" % esc(t))
        for c, t in cells)
    a = ' class="%s"' % cls if cls else ""
    return ('<text%s x="%d" y="%d" textLength="%.1f" lengthAdjust="spacing">'
            '%s</text>' % (a, PADX, y, cols * CH, spans))


def rule(title, right="", cols=COLS):
    head = "|- " + title + " "
    head = head.replace("|-", "┌─")
    tail = (" " + right + " ─┐") if right else " ─┐"
    fill = cols - len(head) - len(tail)
    if fill < 1:
        fill = 1
    return head + "─" * fill + tail


def foot(right="", left="", cols=COLS):
    head = ("└─ " + left + " ") if left else "└"
    tail = (" " + right + " ─┘") if right else "──┘"
    fill = cols - len(head) - len(tail)
    if fill < 1:
        fill = 1
    return head + "─" * fill + tail


def row(inner, cols=COLS):
    inner = inner[: cols - 6]
    return "│  " + inner + " " * (cols - 5 - len(inner)) + "│"


def blank(cols=COLS):
    return "│" + " " * (cols - 2) + "│"


# -- http ---------------------------------------------------------------

def _req(url, data=None, headers=None):
    h = {"Accept": "application/vnd.github+json",
         "User-Agent": "techlogist1-profile-generator"}
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    if headers:
        h.update(headers)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode()), r.status


def rest(path, retries=4):
    """GET a REST endpoint. stats/* answers 202 while GitHub computes it
    asynchronously, so those are retried rather than treated as failures."""
    url = path if path.startswith("http") else API + path
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
        raise RuntimeError("graphql: %s" % payload["errors"])
    return payload["data"]


# -- the collection -----------------------------------------------------

def hand():
    """The hand-kept half of an entry, keyed by repository name.

    Everything a machine can read comes from the API. This file holds only what
    needs judgement -- the one running observation per account, and the entries
    for work that has no repository. A repository absent from this file still
    renders a complete account from API data alone; a field absent from an entry
    is omitted rather than printed empty, because nothing on this page names
    what is not there.
    """
    p = os.path.join(DATA, "accounts.toml")
    if not os.path.exists(p) or tomllib is None:
        return {}
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except Exception:
        traceback.print_exc()
        return {}


def species():
    """Every public repository that counts as a specimen, oldest number first.

    INCLUSION RULE, explicit rather than incidental. A repository is catalogued
    when all of these hold:

      * it is public                     -- the notebook is the public record
      * it is not a fork                 -- someone else collected it
      * it is not archived               -- withdrawn from the collection
      * it is not empty (size > 0)       -- nothing to catalogue
      * it is not this repository        -- a notebook does not catalogue itself

    COLLECTOR'S NUMBERS are assigned by creation date, ascending, over the
    included set. Creation order is the order things entered the collection, it
    never changes, and a new repository always takes the next number -- so
    numbers are stable across runs where a sort by activity would shuffle them
    daily. Sorting by number also keeps the section free of any ranking claim.
    """
    repos = rest("/users/%s/repos?per_page=100&type=owner" % USER) or []
    keep = [r for r in repos
            if not r.get("private")
            and not r.get("fork")
            and not r.get("archived")
            and (r.get("size") or 0) > 0
            and r.get("name") != USER]
    keep.sort(key=lambda r: r.get("created_at") or "")
    for i, r in enumerate(keep, 1):
        r["no"] = i
    return keep


def release_state(name):
    """(tag, state, glyph) for a repository, from releases then tags.

    Glyph rather than hue, because hue on this page is spoken for: a filled
    square is downloadable now, a half square is a pre-release, a hollow square
    is tagged. Nothing here reports what a repository lacks.
    """
    rel = [x for x in (rest("/repos/%s/%s/releases" % (USER, name)) or [])
           if not x.get("draft")]
    if rel:
        rel.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        t = rel[0]
        if t.get("prerelease"):
            return t["tag_name"], "pre-release", "◧"
        return t["tag_name"], "released", "■"
    tags = rest("/repos/%s/%s/tags?per_page=1" % (USER, name)) or []
    if tags:
        return tags[0]["name"], "tagged", "□"
    return "", "in progress", "□"


def languages(name):
    """Languages in a repository, largest first, cut at a tenth of its bytes.

    A tenth rather than a top-N: at 4% a language can qualify on a few hundred
    bytes out of millions, and one commit would then add or drop it with nothing
    on the page explaining why.
    """
    d = rest("/repos/%s/%s/languages" % (USER, name)) or {}
    total = sum(d.values()) or 1
    out = [k for k, v in sorted(d.items(), key=lambda kv: -kv[1])
           if v * 10 >= total]
    return out


# -- the flyleaf: vernier calipers ---------------------------------------
#
# What is on the loudest position on the page, and why it earns it: a measuring
# instrument resolving a reading. The mechanism is the vernier principle -- ten
# slider divisions spanning nine beam divisions, so exactly one slider tick
# lines up with a beam tick and which one it is IS the fractional digit. A
# second scale makes a number exact.
#
# That is this page's own claim about every count on it, and it belongs to no
# single repository and to no tool. Two elements have previously been promoted
# to headline for the wrong reason -- one project's log pipeline, because it was
# the easiest thing on the account to draw, and a line about tooling, because it
# came up often as background. This is neither.
#
# The plate takes no API call. Nothing on it claims to be live, which removes
# the last failure surface from the one image that must never break.

OPEN_X, GAP = -0.72, 1.15
SHUT_X = -3.86 + GAP
NCLOSE = 12                  # distinct geometries: the closing stroke
NHOLD = 8                    # slots the jaws sit shut and the reading resolves
BAND = 13                    # rows of the plate given over to the drawing
TOP = 30
CYCLE = 7.2


def _ease(t):
    return 1 - (1 - t) ** 2.4


def _slots():
    """slot -> (geometry index, caption class, caption).

    The opening stroke is the closing stroke played backwards, so it costs no
    new geometry at all: 31 slots are drawn from 12 paths through <use>. That is
    what keeps a 31-frame animation inside a third of the per-file budget, where
    the same animation with one path per frame ran to 109 KB.
    """
    out = []
    for i in range(NCLOSE):
        out.append((i, "dm", "closing on the work"))
    for k in range(NHOLD):
        if k < 2:
            out.append((NCLOSE - 1, "hi", "main scale        24    mm"))
        else:
            out.append((NCLOSE - 1, "hi", "with the vernier  24·35 mm"))
    for i in range(NCLOSE - 2, -1, -1):
        out.append((i, "dm", "opening"))
    return out


STILL = NCLOSE + 4           # the frame reduced-motion freezes on: jaws shut,
                             # reading resolved. Frozen, the plate still says
                             # what it is for, which is the test a concept has
                             # to pass to be a candidate at all.


def gen_hero():
    W = int(COLS * CH + PADX * 2)
    draw_h = BAND * LH
    dy = TOP + 6
    rows_y = TOP + (BAND + 1) * LH
    h = int(rows_y + LH + 22)

    geoms = []
    for i in range(NCLOSE):
        x = OPEN_X + (SHUT_X - OPEN_X) * _ease(i / (NCLOSE - 1))
        segs = caliper.frame(x, GAP, W, draw_h, scale=735, dist=16,
                             tilt=9, turn=-13, samples=6)
        segs = [((a[0], a[1] + dy), (b[0], b[1] + dy)) for a, b in segs]
        geoms.append(paths_to_d(segs, 1))

    sl = _slots()
    n = len(sl)
    frac = 100.0 / n
    css = ["@keyframes sl{0%%{opacity:1}%.4f%%{opacity:1}%.4f%%{opacity:0}"
           "100%%{opacity:0}}" % (frac, frac + 0.0001)]
    for i in range(n):
        # Negative delays so the cycle is already under way at t=0. A positive
        # delay leaves every group in its base state until its first turn,
        # which flashes the finished frame on load.
        css.append(".s%d{animation:sl %ss linear %.3fs infinite}"
                   % (i, CYCLE, (i * CYCLE / n) - CYCLE))
    css.append("@media (prefers-reduced-motion:reduce){"
               + "".join(".s%d{animation:none;opacity:0}" % i
                         for i in range(n) if i != STILL)
               + ".s%d{animation:none;opacity:1}}" % STILL)

    defs = "".join('<path id="g%d" class="ln" d="%s"/>' % (i, d)
                   for i, d in enumerate(geoms))

    body = [line(TOP, [("fr", rule("FIELD NOTEBOOK",
                                   "L. SINGH · JAIPUR 26°55′N 75°47′E"))])]
    for r in range(1, BAND + 1):
        body.append(line(TOP + r * LH, [("fr", blank())]))
    for i, (gi, cls, cap) in enumerate(sl):
        # No opacity in the CSS rule: each group's base state is carried by its
        # own presentation attribute, and a CSS declaration would outrank it --
        # which once rasterised the whole plate blank, because resvg runs no
        # keyframes. Rasterise the animated file, not only the stills.
        body.append('<g class="s%d" opacity="%d"><use href="#g%d"/>%s</g>'
                    % (i, 1 if i == 0 else 0, gi,
                       line(rows_y, [("fr", "│  "), (cls, cap), ("fr", "  │")])))
    body.append(line(rows_y + LH,
                     [("fr", foot("0·05 MM PER DIVISION",
                                  left="COMMENCED FEB 2022"))]))

    return svg_doc(
        W, h,
        "Field notebook flyleaf — vernier calipers",
        "A pair of vernier calipers drawn in line, closing on a machined pin. "
        "The sliding vernier scale travels along the fixed main scale until the "
        "jaws meet the work, and the reading resolves from 24 mm read off the "
        "main scale alone to 24·35 mm once the vernier is read against it. "
        "Hand-drawn geometry; nothing on this plate is live.",
        "\n".join(css), "".join(body), defs)


# -- badges -------------------------------------------------------------

def _pill(text, cls, w_extra=20):
    """A small clickable plate. Badges live in the README and never inside a
    larger image, because an <img> cannot contain a clickable region."""
    bfs, bch, h = 12, 7.0, 22
    w = int(len(text) * bch) + w_extra
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'width="%d" height="%d" role="img" xml:space="preserve">'
        '<title>%s</title>'
        '<style>%stext{font-size:%dpx}'
        '.pill{fill:none;stroke:%s;stroke-width:1}.pbg{fill:%s}'
        '@media (prefers-color-scheme: light){.pill{stroke:%s}.pbg{fill:%s}}'
        '</style>'
        '<rect class="pbg" x=".5" y=".5" width="%d" height="%d" rx="5"/>'
        '<rect class="pill" x=".5" y=".5" width="%d" height="%d" rx="5"/>'
        '<text class="%s" x="10" y="15" textLength="%.1f" '
        'lengthAdjust="spacing">%s</text></svg>'
        % (w, h, w, h, esc(text), BASE_CSS, bfs, DK["ed"], DK["gl"],
           LT["ed"], LT["gl"], w - 1, h - 1, w - 1, h - 1, cls,
           len(text) * bch, esc(text)))


def lang_link(lang, repos, primary):
    """Where a language badge points, decided from data rather than by hand.

    GitHub's ?language= filter matches a repository's PRIMARY language only, so
    it is used when at least one catalogued repository has this language as its
    primary and would therefore actually come back. Otherwise the badge points
    at the repository holding the most of that language, because a badge that
    links to an empty filter page is worse than one that does not link at all.
    """
    if lang.lower() in primary:
        return ("https://github.com/%s?tab=repositories&language=%s"
                % (USER, lang.lower()))
    best = None
    for r in repos:
        if lang in r.get("_langs", []):
            best = r["name"]
            break
    return "https://github.com/%s/%s" % (USER, best or USER)


def gen_badges(repos):
    """One plate per language in the collection, one release marker and one
    collector's number per repository. All generated here, so the palette is
    exact and the page carries no third-party dependency that can 404."""
    made = []
    langs = []
    for r in repos:
        for L in r.get("_langs", []):
            if L not in langs:
                langs.append(L)
    for L in langs:
        write_atomic(os.path.join(ASSETS, "badge-%s.svg" % L.lower()),
                     _pill(L.lower(), "hi"), "badge-%s" % L.lower())
        made.append(L.lower())
    for r in repos:
        tag, state, glyph = r["_rel"]
        text = ("%s %s %s" % (glyph, tag, state)) if tag else \
               ("%s %s" % (glyph, state))
        write_atomic(os.path.join(ASSETS, "rel-%s.svg" % r["name"]),
                     _pill(text, "dm"), "rel-%s" % r["name"])
        # The one place the accent appears in the README: the collector's
        # number. It means this was counted and you can go and re-check it.
        write_atomic(os.path.join(ASSETS, "no-%s.svg" % r["name"]),
                     _pill("№ %d" % r["no"], "ox", 16), "no-%s" % r["name"])
        made.append(r["name"])
    return made


# -- lines set ----------------------------------------------------------

def gen_lines(repos):
    """LINES SET -- commits on the default branch ahead of the newest tag.

    A collector records lines and traps that are out and have not been checked;
    the count is real, outstanding, and resolved on a later page. Checked
    against the live profile rather than assumed: GitHub already renders the
    contribution calendar, an activity radar, a month-by-month timeline and a
    pinned card per repository carrying language, stars and forks. Release and
    tag state is the one substantial thing about these repositories that appears
    nowhere on a profile page.

    ahead_by is used rather than len(commits): the compare endpoint caps its
    commit list at 250, so summing the returned diff reports a floor as though
    it were a total.
    """
    rows = []
    for r in repos:
        tag = r["_rel"][0]
        if not tag:
            continue
        cmp_ = rest("/repos/%s/%s/compare/%s...%s"
                    % (USER, r["name"], tag, r["default_branch"]))
        if not cmp_:
            continue
        rows.append((r["no"], r["name"], tag, cmp_.get("ahead_by", 0)))
    if not rows:
        return no_data("LINES SET", "no tagged line is out")

    widest = max(a for _, _, _, a in rows) or 1
    nw = max(len(n) for _, n, _, _ in rows)
    cw = max(len("%d ahead" % a) for _, _, _, a in rows
             if a) if any(a for _, _, _, a in rows) else 9
    cw = max(cw, len("run and entered"))
    # The bar goes LAST, after the count. The row is pinned to COLS and anything
    # over that is truncated from the right, so putting the bar at the end means
    # a long repository name can only ever cost bar, never the figure itself.
    # Widths are computed from the rows present, so ten entries lay out the same
    # way three do.
    barw = COLS - 3 - 5 - (nw + 2) - cw - 2 - 3
    barw = max(0, min(barw, 20))
    parts = [line(PADY + LH, [("fr", rule("LINES SET", "OUT SINCE THE LAST TAG"))]),
             line(PADY + LH * 2, [("fr", blank())])]
    y = PADY + LH * 3
    for no, name, tag, ahead in rows:
        if ahead:
            count = ("%d ahead" % ahead).rjust(cw)
            fill = max(1, int(round(barw * ahead / widest))) if barw else 0
            bar = "▪" * fill + "·" * (barw - fill)
        else:
            # Zero here is the good answer, so it is stated as one. Printing a 0
            # beside a 157 would let the smallest number do the talking.
            count = "run and entered".rjust(cw)
            bar = " " * barw
        parts.append(line(y, [("fr", "│  "), ("ox", "№ %-3d" % no),
                              ("hi", name.ljust(nw + 2)),
                              ("tx", count), ("dm", "  " + bar),
                              ("fr", "  │")]))
        y += LH
    parts.append(line(y, [("fr", blank())]))
    y += LH
    scale = max(1, int(round(widest / barw))) if barw else 0
    parts.append(line(y, [("fr", foot("ONE MARK = %d COMMITS" % scale
                                      if barw else "COUNTED AGAINST THE NEWEST TAG"))]))
    h = y + 20
    return svg_doc(int(COLS * CH + PADX * 2), h,
                   "Lines set — commits ahead of each newest tag",
                   "For every catalogued repository, the commits on its default "
                   "branch that are ahead of its newest tag, drawn as a bar. A "
                   "repository level with its tag is entered as run.",
                   "", "\n".join(parts))


# -- catalog ------------------------------------------------------------

def gen_catalog(repos, hd):
    """CATALOG -- one numbered series, one line each, disposition separating.

    The Grinnell catalog numbers everything the collector handled, including
    material deposited elsewhere rather than kept. So the repositories and the
    work that has no repository share a single series, and what tells them apart
    is the disposition column, which is the field a real catalog uses for
    exactly that. Everything gets a number; only some things get an account.
    """
    extra = hd.get("catalog", {}).get("entries", [])
    rows = []
    for r in repos:
        rows.append((r["no"], r["name"], "deposited publicly",
                     (r.get("description") or "")))
    n = len(repos)
    for i, e in enumerate(extra, 1):
        if not e.get("name"):
            continue
        rows.append((n + i, e["name"],
                     e.get("disposition", "kept in the field"),
                     e.get("note", "")))
    if not rows:
        return no_data("CATALOG", "the series has no entry yet")

    # No date column. Repositories have a creation date and the hand-kept
    # entries do not, and a column that prints blank for half the series is a
    # field rendered empty -- which this page does not do.
    nw = max(len(x[1]) for x in rows)
    dw = max(len(x[2]) for x in rows)
    parts = [line(PADY + LH, [("fr", rule("CATALOG", "ONE RUNNING SERIES"))]),
             line(PADY + LH * 2, [("fr", blank())])]
    y = PADY + LH * 3
    for no, name, disp, _note in rows:
        parts.append(line(y, [("fr", "│  "), ("ox", "№ %-3d" % no),
                              ("hi", name.ljust(nw + 2)),
                              ("", disp.ljust(dw)), ("fr", "  │")]))
        y += LH
    parts.append(line(y, [("fr", blank())]))
    y += LH
    parts.append(line(y, [("fr", foot("%d ENTRIES" % len(rows),
                                      left="NUMBERED AS ENTERED"))]))
    return svg_doc(int(COLS * CH + PADX * 2), y + 20,
                   "Catalog — the numbered series",
                   "Every entry in one running series, numbered in the order it "
                   "entered the collection, with the month it was entered and "
                   "its disposition. Numbers are assigned by creation date and "
                   "do not change.",
                   "", "\n".join(parts))


# -- provenance ---------------------------------------------------------

def gen_chain(repos):
    """The numbers themselves, walked and verified.

    Git is already a digest-chained provenance store -- every commit names its
    parent's hash -- so this walks the real chain and actually checks each link
    rather than illustrating one. The mechanism is git's, and every catalogued
    repository is in it equally: this panel makes no argument for any one of
    them. It prints what it checked.
    """
    # The panel walks fewer links per repository as the collection grows, so it
    # stays about one screen whether there are three entries or thirty. The
    # footer always reports the true totals, so a smaller sample is visible in
    # the count rather than silently dropped.
    per = max(2, min(4, 14 // max(1, len(repos))))
    parts = [line(PADY + LH, [("fr", rule("PROVENANCE", "EACH NAMES THE ONE BEFORE"))]),
             line(PADY + LH * 2, [("fr", blank())])]
    y = PADY + LH * 3
    checked = broken = 0
    any_row = False
    for r in repos:
        commits = rest("/repos/%s/%s/commits?per_page=%d"
                       % (USER, r["name"], per + 1)) or []
        if len(commits) < 2:
            continue
        any_row = True
        parts.append(line(y, [("fr", "│  "), ("ox", "№ %-3d" % r["no"]),
                              ("hi", r["name"]), ("fr", "  │")]))
        y += LH
        for i in range(len(commits) - 1):
            sha = commits[i]["sha"]
            parents = [p["sha"] for p in commits[i].get("parents", [])]
            nxt = commits[i + 1]["sha"]
            ok = nxt in parents
            checked += 1
            if not ok:
                broken += 1
            link = "%s → %s" % (sha[:9], nxt[:9])
            parts.append(line(y, [("fr", "│     "), ("dm", link),
                                  ("", "  " + ("linked" if ok else "unlinked")),
                                  ("fr", "  │")]))
            y += LH
        parts.append(line(y, [("fr", blank())]))
        y += LH
    if not any_row:
        return no_data("PROVENANCE", "the series is too short to walk")
    parts.append(line(y, [("fr", foot("%d LINKS CHECKED, %d BROKEN"
                                      % (checked, broken)))]))
    return svg_doc(int(COLS * CH + PADX * 2), y + 20,
                   "Provenance — the chain walked and verified",
                   "Recent commits in each catalogued repository shown as a "
                   "digest chain, each naming the one before it, with every "
                   "link checked: %d links checked, %d broken." % (checked, broken),
                   "", "\n".join(parts))


# -- measurements -------------------------------------------------------

def gen_measure(repos):
    """MEASUREMENTS, TAKEN IN THE FLESH.

    A real convention, and the reason the phrase earns its place: measurements
    written "in the flesh" are taken from the fresh specimen and are trusted
    over measurements taken later from a dried skin. These are counted from the
    API at the moment the workflow runs, not remembered.

    Nothing here ranks one repository above another. Languages are an
    alphabetical set with no byte counts, because a per-language byte count is
    both an ordering claim and a second copy of the primary language GitHub
    prints on every pinned card.
    """
    weeks = total = None
    created = ""
    try:
        d = graphql(
            '{ user(login:"%s"){ createdAt contributionsCollection{'
            ' contributionCalendar{ totalContributions weeks{ contributionDays{'
            ' date contributionCount } } } } } }' % USER)
        u = d["user"]
        created = u["createdAt"]
        cal = u["contributionsCollection"]["contributionCalendar"]
        total = cal["totalContributions"]
        weeks = cal["weeks"]
    except Exception:
        traceback.print_exc()

    langs = sorted({L for r in repos for L in r.get("_langs", [])})
    releases = 0
    for r in repos:
        rel = rest("/repos/%s/%s/releases" % (USER, r["name"])) or []
        releases += len([x for x in rel if not x.get("draft")])

    streak = 0
    if weeks:
        run = 0
        for w in weeks:
            for day in w["contributionDays"]:
                if day["contributionCount"] > 0:
                    run += 1
                    streak = max(streak, run)
                else:
                    run = 0

    # The collection first, then the observer. A measurements page records the
    # specimen; a contribution count records the naturalist, and saying which is
    # which is the honest version rather than mixing them in one column.
    rows = [("THE COLLECTION", None)]
    rows.append(("deposited publicly", "%d" % len(repos)))
    if releases:
        rows.append(("releases published", "%d" % releases))
    if langs:
        rows.append(("languages", ", ".join(langs)))
    rows.append(("THE OBSERVER, SAME PERIOD", None))
    if total is not None:
        rows.append(("contributions, last 365 days", "%d" % total))
    if streak:
        rows.append(("longest unbroken run", "%d days" % streak))
    if created:
        rows.append(("commenced", created[:7]))
    if len([r for r in rows if r[1] is not None]) == 0:
        return no_data("MEASUREMENTS", "the counts did not come back")

    parts = [line(PADY + LH, [("fr", rule("MEASUREMENTS", "TAKEN IN THE FLESH"))]),
             line(PADY + LH * 2, [("fr", blank())])]
    y = PADY + LH * 3
    for label, val in rows:
        if val is None:                    # a sub-head inside the plate
            parts.append(line(y, [("fr", "│  "), ("dm", label), ("fr", "  │")]))
            y += LH
            continue
        # Built to exactly COLS, so line() never has to pad or truncate. It folds
        # slack into the second-to-last cell, which here is the value -- and a
        # measurement clipped to "TypeScrip" is a wrong figure, not a tight one.
        # The dot leader absorbs the slack instead, which is its job on a ruled
        # page anyway.
        room = COLS - 5 - len(label) - 1 - 1 - len(val) - 3
        lab = label
        if room < 2:                       # a long value shortens the LABEL
            cut = label[:max(0, len(label) + room - 2)]
            lab = cut.rsplit(" ", 1)[0] if " " in cut else cut
            room = COLS - 5 - len(lab) - 1 - 1 - len(val) - 3
            room = max(room, 1)
        # .hi, not .ox. Oxblood means a collector's number and nothing else; a
        # measurement is a second thing wanting it, and the answer is no.
        parts.append(line(y, [("fr", "│    "), ("tx", lab + " "),
                              ("fr", "·" * room), ("hi", " " + val),
                              ("fr", "  │")]))
        y += LH
    parts.append(line(y, [("fr", blank())]))
    y += LH
    parts.append(line(y, [("fr", foot("COUNTED WHEN THIS RAN",
                                      left="NOT REMEMBERED"))]))
    return svg_doc(int(COLS * CH + PADX * 2), y + 20,
                   "Measurements, taken in the flesh",
                   "Counts read from the API at the moment this was generated: "
                   + "; ".join("%s %s" % (a, b) for a, b in rows if b) + ".",
                   "", "\n".join(parts))


# -- degradation --------------------------------------------------------

def no_data(title, reason):
    """A legible frame. Never an empty file -- an <img> renders that as a broken
    image icon, which is worse on the page than stale or absent data."""
    w = int(COLS * CH + PADX * 2)
    h = PADY + LH * 5 + 10
    parts = [
        line(PADY + LH, [("fr", rule(title, "NO DATA"))]),
        line(PADY + LH * 2, [("fr", blank())]),
        line(PADY + LH * 3, [("fr", "│  "), ("", reason[:COLS - 8]),
                             ("fr", "  │")]),
        line(PADY + LH * 4, [("fr", blank())]),
        line(PADY + LH * 5, [("fr", foot(datetime.now(timezone.utc)
                                         .strftime("%Y-%m-%d %H:%MZ")))]),
    ]
    return svg_doc(w, h, title + " — no data",
                   "No data available: " + reason, "", "\n".join(parts))


# -- write --------------------------------------------------------------

def validate(svg, name):
    if not svg or len(svg) < 300:
        raise ValueError("%s: suspiciously small (%d bytes)" % (name, len(svg)))
    low = svg.lower()
    # Refuse a doctype or entity declaration before parsing: these are the
    # vector for XXE and billion-laughs, and an SVG we generate ourselves has no
    # business carrying either, so reject rather than harden the parser.
    if "<!doctype" in low or "<!entity" in low:
        raise ValueError("%s: doctype/entity declaration" % name)
    ET.fromstring(svg)
    if "<script" in low:
        raise ValueError("%s: contains <script>" % name)
    if "var(--" in svg:
        raise ValueError("%s: CSS custom properties render black in resvg" % name)
    if "@font-face" in svg or "url(http" in low:
        raise ValueError("%s: external font reference" % name)
    for tok in ("http://", "https://"):
        for hit in svg.split(tok)[1:]:
            if not hit.startswith("www.w3.org"):
                raise ValueError("%s: external URL %s%s" % (name, tok, hit[:40]))
    if "prefers-color-scheme" not in svg:
        raise ValueError("%s: no prefers-color-scheme block" % name)
    if "@keyframes" in svg and "prefers-reduced-motion" not in svg:
        raise ValueError("%s: animates with no prefers-reduced-motion" % name)
    for banned in ("claude", "copilot", "chatgpt", "vibe cod"):
        if banned in low:
            raise ValueError("%s: names a tool -- see CLAUDE.md" % name)


def write_atomic(path, svg, name):
    validate(svg, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    os.replace(tmp, path)                          # atomic on POSIX and NTFS


# -- the entries that grow -----------------------------------------------
#
# The README's species accounts and kit list are written by this script, not by
# hand. That is the whole reason this conceit was chosen: open-sourcing a new
# project must take no edit to this repository. Push a repository and it appears
# in the notebook with the next collector's number.

KIT_OPEN, KIT_CLOSE = "<!--notebook:kit-->", "<!--/notebook:kit-->"
ACC_OPEN, ACC_CLOSE = "<!--notebook:accounts-->", "<!--/notebook:accounts-->"
PLN_OPEN, PLN_CLOSE = "<!--notebook:plans-->", "<!--/notebook:plans-->"
DEP_OPEN, DEP_CLOSE = "<!--notebook:deposited-->", "<!--/notebook:deposited-->"

# Two trailing spaces are LOAD-BEARING. GitHub's profile README does not render
# a soft newline as a break, so without them each entry collapses onto one line
# and the section stops scanning. Verified on the live page; the /markdown API
# renders soft breaks differently and will not reproduce it.
BR = "  "


def repo_url(name):
    return "https://github.com/%s/%s" % (USER, name)


def account_md(r, hd, primary):
    """One species account. Same field set, same order, every entry.

    Structure does the balancing, not prose restraint: every repository gets
    exactly these fields in exactly this order, so no entry can be argued into
    prominence over another. A field with nothing behind it is omitted rather
    than printed empty -- nothing on this page names what is not there.
    """
    url = repo_url(r["name"])
    out = []
    head = ("[![№ %d](assets/no-%s.svg)](%s) **[%s](%s)**"
            % (r["no"], r["name"], url, r["name"], url))
    desc = (r.get("description") or "").strip()
    over = hd.get(r["name"], {}).get("hook")
    if over:
        desc = over.strip()
    if desc:
        head += " — " + desc
    out.append(head + BR)

    marks = ["[![%s](assets/badge-%s.svg)](%s)"
             % (L.lower(), L.lower(), lang_link(L, [r], primary))
             for L in r.get("_langs", [])]
    tag, state, glyph = r["_rel"]
    # Where the marker points is decided by which endpoint the tag came from.
    # A repository that is tagged but has cut no release has an EMPTY /releases
    # page, and a badge linking to an empty page is worse than one that does not
    # link at all -- so "tagged" goes to /tags and only a real release goes to
    # /releases.
    rel_url = url + {"released": "/releases", "pre-release": "/releases",
                     "tagged": "/tags"}.get(state, "/commits")
    marks.append("[![%s %s](assets/rel-%s.svg)](%s)"
                 % (glyph, (tag + " " + state) if tag else state,
                    r["name"], rel_url))
    out.append(" ".join(marks) + BR)

    obs = hd.get(r["name"], {}).get("observation")
    if obs:
        out.append("<sub>%s</sub>" % obs.strip() + BR)
    return "\n".join(out)


def kit_md(repos, primary):
    langs = sorted({L for r in repos for L in r.get("_langs", [])})
    if not langs:
        return ""
    return " ".join("[![%s](assets/badge-%s.svg)](%s)"
                    % (L.lower(), L.lower(), lang_link(L, repos, primary))
                    for L in langs)


def splice(text, open_tag, close_tag, body):
    i, j = text.find(open_tag), text.find(close_tag)
    if i < 0 or j < 0 or j < i:
        raise ValueError("README marker %s missing" % open_tag)
    return text[:i + len(open_tag)] + "\n" + body + "\n" + text[j:]


def plans_md(repos, hd):
    """Plans for tomorrow, one line per repository that has one.

    Built from the same per-repository file as everything else, so it grows and
    shrinks with the collection. A repository with no plan recorded simply does
    not appear here; it is never given a line that reports having none.
    """
    out = []
    for r in repos:
        p = hd.get(r["name"], {}).get("plan")
        if p:
            out.append("**[%s](%s)** — %s%s"
                       % (r["name"], repo_url(r["name"]), p.strip(), BR))
    return "\n".join(out)


def deposited_md(hd):
    """The catalogued work that has no repository, linked where a link exists."""
    out = []
    for e in hd.get("catalog", {}).get("entries", []):
        if not e.get("name"):
            continue
        name = e["name"]
        head = "**[%s](%s)**" % (name, e["url"]) if e.get("url") else "**%s**" % name
        note = e.get("note")
        out.append(head + (" — " + note if note else "") + BR)
    return "\n".join(out)


def write_readme(repos, hd, primary):
    """Rewrite the generated blocks in place, leaving all hand-written prose."""
    src = open(README, encoding="utf-8").read()
    accounts = "\n\n".join(account_md(r, hd, primary) for r in repos)
    out = splice(src, KIT_OPEN, KIT_CLOSE, kit_md(repos, primary))
    out = splice(out, ACC_OPEN, ACC_CLOSE, accounts)
    out = splice(out, PLN_OPEN, PLN_CLOSE, plans_md(repos, hd))
    out = splice(out, DEP_OPEN, DEP_CLOSE, deposited_md(hd))
    for banned in ("Claude", "copilot", "vibe cod"):
        if banned.lower() in out.lower():
            raise ValueError("README names a tool -- see CLAUDE.md")
    if out != src:
        tmp = README + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(out)
        os.replace(tmp, README)
    return len(repos)


# -- main ---------------------------------------------------------------

def enrich(repos):
    for r in repos:
        r["_langs"] = languages(r["name"])
        r["_rel"] = release_state(r["name"])
    return repos


def main():
    os.makedirs(ASSETS, exist_ok=True)
    only = sys.argv[1:]
    ok, failed = [], []

    try:
        repos = enrich(species())
        if not repos:
            raise RuntimeError("no repository met the inclusion rule")
        hd = hand()
        primary = {(r.get("language") or "").lower() for r in repos}
    except Exception:
        traceback.print_exc()
        print("::error::could not read the collection; every plate keeps its "
              "last committed file and the README is untouched")
        return 1

    print("catalogued %d: %s" % (len(repos), ", ".join(
        "no.%d %s" % (r["no"], r["name"]) for r in repos)))

    jobs = [
        ("hero", "hero.svg", lambda: gen_hero()),
        ("lines", "lines-set.svg", lambda: gen_lines(repos)),
        ("catalog", "catalog.svg", lambda: gen_catalog(repos, hd)),
        ("chain", "chain.svg", lambda: gen_chain(repos)),
        ("measure", "measurements.svg", lambda: gen_measure(repos)),
    ]

    if not only or "badges" in only:
        try:
            made = gen_badges(repos)
            ok.append("badges (%d)" % len(made))
            print("ok      %-9s -> %d files" % ("badges", len(made)), flush=True)
        except Exception:
            failed.append("badges")
            print("FAILED  badges    -> kept last committed badge plates",
                  flush=True)
            traceback.print_exc()

    for name, fname, fn in jobs:
        if only and name not in only:
            continue
        path = os.path.join(ASSETS, fname)
        try:
            svg = fn()
            write_atomic(path, svg, name)
            ok.append("%s (%d B)" % (name, len(svg)))
            print("ok      %-9s -> assets/%s  %d B" % (name, fname, len(svg)),
                  flush=True)
        except Exception:
            failed.append(name)
            kept = ("kept last committed file" if os.path.exists(path)
                    else "NO existing file to fall back on")
            print("FAILED  %-9s -> %s" % (name, kept), flush=True)
            traceback.print_exc()
        finally:
            if os.path.exists(path + ".tmp"):
                os.remove(path + ".tmp")

    if not only or "readme" in only:
        try:
            n = write_readme(repos, hd, primary)
            ok.append("readme (%d accounts)" % n)
            print("ok      %-9s -> %d species accounts" % ("readme", n),
                  flush=True)
        except Exception:
            failed.append("readme")
            print("FAILED  readme    -> left as committed", flush=True)
            traceback.print_exc()

    print("\ngenerated %d  failed %d" % (len(ok), len(failed)))
    if failed:
        print("::error::failed: %s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
