"""Exercise the degradation path. The design's whole point is what it does when
something upstream is broken, so that has to be run rather than reasoned about.
"""
import os
import shutil
import sys
import tempfile

PROF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROF, "tools"))
import generate as g                                          # noqa: E402

OK = "PASS"
NO = "FAIL"


def case(name, fn):
    try:
        detail = fn()
        print("%s  %-42s %s" % (OK, name, detail))
    except AssertionError as e:
        print("%s  %-42s %s" % (NO, name, e))


def t_generator_raises():
    """A generator that throws must leave its committed plate untouched."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "catalog.svg")
    open(p, "w", encoding="utf-8").write("LAST GOOD")
    try:
        g.write_atomic(p, (_ for _ in ()).throw(RuntimeError("boom")), "catalog")
    except Exception:
        pass
    left = open(p, encoding="utf-8").read()
    assert left == "LAST GOOD", "the committed plate was clobbered"
    assert not os.path.exists(p + ".tmp"), "a .tmp file was left behind"
    return "last good plate kept, no temp file left"


def t_empty_source():
    """An empty upstream must produce a legible frame, never an empty file."""
    svg = g.no_data("LINES SET", "no tagged line is out")
    g.validate(svg, "no_data")
    assert "no tagged line is out" in svg, "the frame does not say why"
    assert len(svg) > 800, "frame suspiciously small"
    return "%d B legible 'no data' frame, validates" % len(svg)


def t_banned_url():
    """A third-party image URL must be refused at write time."""
    bad = g.gen_catalog([], {}).replace(
        "</svg>", '<image href="https://img.shields.io/x.svg"/></svg>')
    try:
        g.validate(bad, "catalog")
    except ValueError as e:
        return "refused: %s" % str(e)[:52]
    raise AssertionError("an external URL was accepted")


def t_names_a_tool():
    """A plate that names a tool must be refused at write time."""
    svg = g.no_data("X", "built with Claude Code")
    try:
        g.validate(svg, "x")
    except ValueError as e:
        return "refused: %s" % str(e)[:52]
    raise AssertionError("a plate naming a tool was accepted")


def t_missing_hand_file():
    """A repository absent from accounts.toml still renders a full account."""
    r = {"name": "widget", "no": 7, "description": "a real description",
         "_langs": ["Rust"], "_rel": ("v2.0.0", "released", "■")}
    md = g.account_md(r, {}, {"rust"})
    lines = md.split("\n")
    assert len(lines) == 2, "expected 2 lines with no hand entry, got %d" % len(lines)
    assert "№ 7" in md and "widget" in md and "a real description" in md
    assert all(l.endswith("  ") for l in lines), "lost the load-bearing break"
    assert "None" not in md and "unknown" not in md.lower()
    return "complete 2-line account from API data alone"


def t_no_description():
    """A repository with no description omits the field rather than empty it."""
    r = {"name": "widget", "no": 8, "description": None,
         "_langs": ["Rust"], "_rel": ("", "in progress", "□")}
    md = g.account_md(r, {}, set())
    assert "—" not in md.split("\n")[0], "printed a dangling em dash"
    assert "None" not in md
    return "hook omitted cleanly, no empty field"


def t_readme_marker_missing():
    """A missing marker must raise and leave the README untouched."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "README.md")
    shutil.copy(os.path.join(PROF, "README.md"), p)
    raw = open(p, encoding="utf-8").read().replace(g.ACC_OPEN, "")
    open(p, "w", encoding="utf-8").write(raw)
    old = g.README
    g.README = p
    try:
        g.write_readme([], {}, set())
    except ValueError:
        after = open(p, encoding="utf-8").read()
        assert after == raw, "the README was modified despite the failure"
        return "raised, README left exactly as it was"
    finally:
        g.README = old
    raise AssertionError("a missing marker was not caught")


if __name__ == "__main__":
    for n, f in [("generator raises", t_generator_raises),
                 ("empty data source", t_empty_source),
                 ("third-party URL injected", t_banned_url),
                 ("plate names a tool", t_names_a_tool),
                 ("repo absent from accounts.toml", t_missing_hand_file),
                 ("repo with no description", t_no_description),
                 ("README marker deleted", t_readme_marker_missing)]:
        case(n, f)
