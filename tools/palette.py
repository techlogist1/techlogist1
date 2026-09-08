#!/usr/bin/env python3
"""Check every palette value against the ground it is actually drawn on.

The previous warm palette was rejected partly because several accents fell under
3:1 on GitHub's dark page. That is not something to judge by eye on a monitor you
happen to be using, so it is computed here and the numbers are copied into the
comment block in generate.py.

    python tools/palette.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate import DK, LT                                   # noqa: E402

GH_DARK, GH_LIGHT = "#0d1117", "#ffffff"

# 4.5:1 for anything carrying a word, 3:1 for rule work -- WCAG 1.4.3 and
# 1.4.11. Box-drawing is structural rather than decorative here: it is what
# tells a reader where a plate begins and ends, so it is held to 3:1 rather
# than exempted.
NEED = {"tx": 4.5, "hi": 4.5, "dm": 4.5, "fr": 3.0, "ox": 4.5}
ROLE = {"tx": "body ink", "hi": "primary, values", "dm": "secondary, labels",
        "fr": "structure, box-drawing", "ox": "collector's number ONLY"}


def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def main():
    bad = 0
    for name, P, page in (("dark", DK, GH_DARK), ("light", LT, GH_LIGHT)):
        print("\n%s  -- plate %s on GitHub %s" % (name.upper(), P["gl"], page))
        for k in ("tx", "hi", "dm", "fr", "ox"):
            r = ratio(P[k], P["gl"])
            ok = r >= NEED[k]
            if not ok:
                bad += 1
            print("  .%-3s %s  %5.2f:1  need %.1f  %-4s %s"
                  % (k, P[k], r, NEED[k], "ok" if ok else "LOW", ROLE[k]))
        # The accent is close to the body ink in luminance on purpose; the
        # meaning is carried by the numero glyph, so this is reported rather
        # than enforced.
        print("  accent vs body ink %.2f:1 -- carried by the No. glyph, not by hue"
              % ratio(P["ox"], P["tx"]))
    if bad:
        print("\n::error::%d palette value(s) under the required ratio" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
