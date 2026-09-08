#!/usr/bin/env python3
"""Assert the hard constraints on every committed SVG.

Runs in CI as well as by hand. This is the guard that stops a future edit from
quietly reintroducing a third-party image URL, a webfont, an animation with no
reduced-motion path, or a CSS custom property. It does no rasterising, so it
needs nothing installed -- look at the PNGs with tools/../check.py locally when
you want to see the pixels.
"""
import glob, os, re, sys
import xml.etree.ElementTree as ET

MAX_TOTAL = 400_000          # whole-README budget, hero included
MAX_ONE = 150_000


def check(path):
    raw = open(path, encoding="utf-8").read()
    low = raw.lower()
    bad = []

    if "<!doctype" in low or "<!entity" in low:
        bad.append("doctype or entity declaration")
    else:
        try:
            ET.fromstring(raw)
        except Exception as e:
            bad.append(f"does not parse as XML: {e}")

    if "<script" in low:
        bad.append("contains <script> (never executes in an <img>, and has no business here)")
    if "@font-face" in low or "url(http" in low:
        bad.append("webfont reference — silently fails to load and breaks the layout")
    if "var(--" in raw:
        bad.append("CSS custom property — resvg renders these black")
    for m in re.findall(r'https?://[^\s"\'<>)]+', raw):
        if not m.startswith("http://www.w3.org") and not m.startswith("https://www.w3.org"):
            bad.append(f"external URL: {m}")
    for m in re.findall(r'(?:href|src)\s*=\s*["\'](?!#)([^"\']+)', raw, re.I):
        bad.append(f"external reference: {m}")
    if "prefers-color-scheme" not in raw:
        bad.append("no prefers-color-scheme block")
    if "@keyframes" in raw and "prefers-reduced-motion" not in raw:
        bad.append("animates with no prefers-reduced-motion block")
    if "xml:space" not in raw:
        bad.append('no xml:space="preserve" — padding collapses and the ASCII grid breaks')

    size = os.path.getsize(path)
    if size > MAX_ONE:
        bad.append(f"{size:,} B exceeds the {MAX_ONE:,} B per-file budget")
    if size < 300:
        bad.append(f"{size:,} B — suspiciously small, probably truncated")
    return size, bad


README_MARKERS = ["notebook:accounts", "notebook:plans",
                  "notebook:deposited"]
# Nothing on this page names a tool, an assistant, or how the code was written.
# The rule is in CLAUDE.md; this is the guard that stops it coming back by
# accident, in an alt string or an HTML comment where nobody would look.
BANNED = ["claude", "copilot", "chatgpt", "vibe cod", "openai"]
# Nothing on this page describes the author rather than the work. These are the
# specific things that were on it and were cut; the rule is in CLAUDE.md.
PERSONAL = ["whisk", "glenlivet", "proraso", "edwin jagger", "razor",
            "fountain pen", "wristwatch", "tame impala", "mac demarco",
            "kahaani", "andhadhun", "jaane jaan", "nolan", "fincher",
            "villeneuve", "26°55", "75°47", "shiv nadar", "arizona state",
            "outfit carried", "in camp"]


def check_readme(path="README.md"):
    """The generator rewrites four blocks in README.md in place. If a marker
    goes missing the rewrite raises and the page silently stops growing, so the
    markers are checked here rather than discovered months later."""
    bad = []
    if not os.path.exists(path):
        return ["README.md is missing"]
    raw = open(path, encoding="utf-8").read()
    for m in README_MARKERS:
        if raw.count("<!--%s-->" % m) != 1 or raw.count("<!--/%s-->" % m) != 1:
            bad.append("README.md: marker pair <!--%s--> is not intact" % m)
    low = raw.lower()
    # The repository's own notes file is named CLAUDE.md by convention. A
    # pointer to it in a non-rendered comment is a filename, not a credit, so
    # the token is removed before the banlist runs rather than the banlist
    # being weakened.
    low_ban = low.replace("claude.md", "")
    for b in BANNED:
        if b in low_ban:
            bad.append("README.md: names a tool (%r) -- see CLAUDE.md" % b)
    for b in PERSONAL:
        if b in low:
            bad.append("README.md: describes the author (%r) rather than the "
                       "work -- see CLAUDE.md" % b)

    # HTML comments do not nest. A "<!--" inside a comment body means the first
    # "-->" closes the block early and everything after it renders as body text
    # at the top of the profile -- which is exactly what shipped once, because
    # the explanatory comment quoted a marker name literally. Found on the live
    # page, not in review, so it is checked here now.
    i = 0
    while True:
        a = raw.find("<!--", i)
        if a < 0:
            break
        b = raw.find("-->", a + 4)
        if b < 0:
            bad.append("README.md: an HTML comment is never closed")
            break
        if "<!--" in raw[a + 4:b]:
            bad.append("README.md: a comment at offset %d contains '<!--', so it "
                       "closes early and leaks body text" % a)
        i = b + 3
    return bad


def main(paths):
    files = []
    for p in paths:
        files.extend(glob.glob(p))
    files = sorted(set(files))
    if not files:
        print("::error::no SVGs matched — refusing to pass vacuously")
        return 1

    failed = 0
    for b in check_readme(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "README.md")):
        failed += 1
        print("::error::%s" % b)
    if not failed:
        print("ok    README.md        markers intact, names no tool")

    total = 0
    for f in files:
        size, bad = check(f)
        total += size
        status = "ok" if not bad else "FAIL"
        print(f"{status:5} {os.path.basename(f):16} {size:>8,} B")
        for b in bad:
            failed += 1
            print(f"      ::error file={f}::{b}")

    print(f"\ntotal {total:,} B across {len(files)} files "
          f"(budget {MAX_TOTAL:,} B)")
    if total > MAX_TOTAL:
        print(f"::error::total {total:,} B exceeds the {MAX_TOTAL:,} B budget")
        failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["assets/*.svg"]))
