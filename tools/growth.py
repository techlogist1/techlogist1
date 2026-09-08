"""Exercise the growth path. A path you have not run is a path you do not have.

Injects synthetic repositories into the collection, regenerates every plate and
the README into a scratch tree, and checks that nothing assumed a count of three:
that each plate still lays out on the grid, that no row overflows or is clipped,
and that a repository carrying no hand-kept entry still renders a complete
account from API data alone.
"""
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

PROF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROF, "tools"))
import generate as g                                          # noqa: E402

REAL = g.species
REAL_LANG = g.languages
REAL_REL = g.release_state
REAL_REST = g.rest

FAKE_LANGS = ["Go", "Zig", "Rust", "TypeScript", "C", "Lua", "Elixir"]


def fake_repo(i):
    return {
        "name": "specimen-%02d" % i,
        "description": "a synthetic entry used to exercise the growth path",
        "language": FAKE_LANGS[i % len(FAKE_LANGS)],
        "default_branch": "main",
        "created_at": "2026-0%d-01T00:00:00Z" % (1 + i % 9),
        "private": False, "fork": False, "archived": False, "size": 10,
    }


def run(n, outdir):
    """Regenerate everything with n total repositories into outdir."""
    base = REAL()
    extra = [fake_repo(i) for i in range(1, max(0, n - len(base)) + 1)]
    all_repos = base + extra
    all_repos.sort(key=lambda r: r.get("created_at") or "")
    for i, r in enumerate(all_repos, 1):
        r["no"] = i

    names = {r["name"] for r in extra}

    g.species = lambda: all_repos
    g.languages = lambda nm: ([FAKE_LANGS[hash(nm) % len(FAKE_LANGS)], "Rust"]
                              if nm in names else REAL_LANG(nm))
    g.release_state = lambda nm: (("v1.2.3", "released", "■")
                                  if nm in names else REAL_REL(nm))

    def rest_stub(path, retries=4):
        for nm in names:
            if "/" + nm in path:
                if "/compare/" in path:
                    return {"ahead_by": 17 + len(nm)}
                if "/commits" in path:
                    return [{"sha": "%040x" % (i * 7919),
                             "parents": [{"sha": "%040x" % ((i + 1) * 7919)}]}
                            for i in range(6)]
                return []
        return REAL_REST(path, retries)
    g.rest = rest_stub

    os.makedirs(outdir, exist_ok=True)
    g.ASSETS = outdir
    readme = os.path.join(outdir, "README.md")
    shutil.copy(os.path.join(PROF, "README.md"), readme)
    g.README = readme

    g.enrich(all_repos)
    hd = g.hand()
    primary = {(r.get("language") or "").lower() for r in all_repos}
    g.gen_badges(all_repos)
    for nm, fn in (("hero.svg", lambda: g.gen_hero()),
                   ("lines-set.svg", lambda: g.gen_lines(all_repos)),
                   ("catalog.svg", lambda: g.gen_catalog(all_repos, hd)),
                   ("chain.svg", lambda: g.gen_chain(all_repos)),
                   ("measurements.svg", lambda: g.gen_measure(all_repos))):
        g.write_atomic(os.path.join(outdir, nm), fn(), nm)
    g.write_readme(all_repos, hd, primary)

    g.species, g.languages, g.release_state, g.rest = REAL, REAL_LANG, REAL_REL, REAL_REST
    return all_repos, readme


def check(outdir, readme, n):
    bad = []
    for f in sorted(os.listdir(outdir)):
        if not f.endswith(".svg") or f.startswith(("badge-", "rel-", "no-")):
            continue
        s = open(os.path.join(outdir, f), encoding="utf-8").read()
        rows = [html.unescape(re.sub(r"<[^>]+>", "", r))
                for r in re.findall(r"<text[^>]*>(.*?)</text>", s)]
        off = [t for t in rows if len(t) != g.COLS]
        if off:
            bad.append("%s: %d rows off the %d-char grid" % (f, len(off), g.COLS))
        clipped = [t for t in rows if t and not t.rstrip().endswith(("│", "┐", "┘"))]
        if clipped:
            bad.append("%s: %d rows not closing" % (f, len(clipped)))

    md = open(readme, encoding="utf-8").read()
    acc = md.split(g.ACC_OPEN)[1].split(g.ACC_CLOSE)[0].strip(chr(10))
    blocks = [b for b in acc.split("\n\n") if b.strip()]
    if len(blocks) != n:
        bad.append("README: %d accounts, expected %d" % (len(blocks), n))
    longest = max((len(b.split("\n")) for b in blocks), default=0)
    if longest > 3:
        bad.append("README: an account runs to %d lines" % longest)
    for b in blocks:
        for ln in b.split("\n"):
            if ln.strip() and not ln.endswith("  "):
                bad.append("README: line without its load-bearing double space")
                break
    return bad, len(blocks), longest


if __name__ == "__main__":
    for n in (4, 10):
        out = os.path.join(tempfile.gettempdir(), "notebook-grow-%d" % n)
        shutil.rmtree(out, ignore_errors=True)
        repos, readme = run(n, out)
        bad, blocks, longest = check(out, readme, n)
        sizes = {f: os.path.getsize(os.path.join(out, f))
                 for f in os.listdir(out) if f.endswith(".svg")}
        print("\n=== %d entries ===" % n)
        print("  accounts rendered: %d, longest %d lines" % (blocks, longest))
        print("  plates: %d files, %s B total"
              % (len(sizes), format(sum(sizes.values()), ",")))
        for f in ("lines-set.svg", "catalog.svg", "chain.svg", "measurements.svg"):
            print("    %-18s %6s B" % (f, format(sizes.get(f, 0), ",")))
        print("  PROBLEMS:", bad if bad else "none")
        print("  out:", out)
