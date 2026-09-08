# Progress

A cold context should be able to pick up from this file plus `CLAUDE.md`.
Newest first.

## Done

## Sixth pass — the field notebook. Shipped.

The page is a **naturalist's field notebook kept in the Grinnell system**, in
90s vintage warmth. Chosen over an owner's workshop manual, which scored higher
on polish, on one property: **it grows**. See CLAUDE.md § The conceit.

**It grows by itself. Open-sourcing a project takes no edit to this repo.**
`species()` catalogues it, it takes the next collector's number, its badges are
generated, and its species account, plans line, catalog row, provenance walk and
LINES SET row are all written by the workflow. `data/accounts.toml` holds only
what needs judgement and **is never required** — a repository absent from it
renders a complete account from API data alone.

**Exercised, not assumed.** `tools/growth.py` injects synthetic repositories and
regenerates everything at **4 and at 10** entries: every row still lands on the
61-character grid, every frame closes, no account exceeds three lines, and the
whole page is 112 KB at ten entries against a 400 KB budget.
`tools/degrade.py` runs seven failure paths, all passing.

**Balance test passed.** Six blind readers, no context, one read each: all six
described all three repositories and the local-first thesis, all six answered
"none" to *does a single repository dominate*, all six recalled all six
catalogued things.

**The hero is vernier calipers**, real 3D built headless by `tools/caliper.py`
and `tools/r3d.py` — hidden-line removal in **pure stdlib Python**, because this
repo has no third-party dependency and the workflow has no pip step. 31 slots
drawn from 12 geometries via `<defs>`/`<use>`, which took it from 109 KB to 46 KB
while adding a frame.

**Format chosen on measurement** — animated SVG 46 KB, APNG 752 KB (5x the
per-file cap), GIF-64 124 KB. SVG also wins on density (a raster is 6.0% off at
2x device pixels), on carrying both themes in one file, on keeping text as text,
and on handling reduced motion internally. Full table in CLAUDE.md.

**Oxblood means one thing:** a collector's number. It shipped broken once, with
every measurement value in the accent, which emptied it of meaning. Now the `№`
glyph carries the meaning and the colour only reinforces it.

### Found by looking, not by reasoning

- **The top HTML comment leaked two paragraphs of build notes onto the live
  profile.** It quoted a marker name literally; comments do not nest, so the
  first `-->` ended the block. Invisible in an editor and not reproduced by the
  `/markdown` API. `verify.py` now walks every comment.
- **Rows were letter-spread and content vanished** — `line()` folded padding
  into an *unclassed* cell, which resvg emits as a bare run and loses. Every run
  is wrapped now. `TypeScript` had also shipped as `TypeScrip`, from the same
  helper truncating the value cell.
- **`LH` was wrong.** Measured with an ink profile down the rule column: 100%
  vertical continuity at 16, 98.1% at 17, which is what the page ran at.
- **The panels rendered at half the hero's scale** because only the hero carried
  `width="100%"`. Same natural width, different display size — the exact
  stack-of-widgets look the shared grid exists to prevent.

### Measured on the live site

- `<source media="(prefers-reduced-motion: reduce)">` **survives GitHub's HTML
  sanitizer verbatim**, including compound queries. A raster hero *could* have
  frozen; it lost on other grounds.
- `<table>` with `width`/`valign` survives, if a future layout needs columns.

## Open / not done by me

- **The whisky line in "In camp".** One of the six blind readers — the admissions
  reader — flagged 90 ml of Glenlivet volunteered by a 19-year-old as a reason to
  discount the work above it. It is true, it is his, and it is the best-anchored
  personal line on the page, so it was left in and raised instead of cut.
- **`chain.svg` is the weakest plate.** The adversarial read argues "12 links
  checked, 0 broken" is close to a tautology, since commits name their parents by
  construction. It does detect non-linear history, so it is not empty, but it is
  the plate to cut first if the page ever needs the room.
- **Pinned repositories cannot be set through any API.** `techlogist1` is still
  pinned alongside the three projects and needs **unpinning by hand**.
- **`vysted.com` has no A record**, so it is unlinked. Point the domain at its
  deployment and restore the link.

## Fifth pass and earlier

**No line on this page attributes the work to a tool.** Shipped and live. The hero
animated a pair of sentences splitting credit between the author and his tooling,
the intro named that tooling, and both were repeated in the README alt text and in
the hero's `<desc>`. All removed; the hero's two sentences are now *"It runs on
your own computer"* / *"Your data stays in your files"*, both true of all three
projects, and the intro states the decision instead: where a feature could cost
you something, it ships switched off. The rule and the general principle behind it
are in CLAUDE.md § Never attribute the work to a tool — **read that before writing
any hero**. The scheduled workflow regenerated on the new generator and kept it.

**Measured on the live site, not assumed** (probe branch, since deleted):

- `<source media="(prefers-reduced-motion: reduce)">` **survives GitHub's HTML
  sanitizer verbatim**, including compound queries such as
  `(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)`. So a raster
  hero *can* freeze for reduced motion via `<picture>`; the format choice is not
  forced by accessibility.
- `<table>` with `width` and `valign` survives, so real multi-column layout is
  available. The page has never used it.
- Images still rewrite to `/techlogist1/techlogist1/raw/...` — the camo finding holds.

**Toolchain present for a rendered hero:** resvg 0.48.1, ffmpeg 8.1, Pillow 12.1
(APNG save), numpy, node. No ImageMagick, gifsicle, oxipng or pngquant.

**Open:** the conceit is chosen but the page is not yet rebuilt in it. `verify.py`
guards `assets/*.svg` only — if a raster asset ships, extend it to cover raster
size and existence too, or the budget stops being enforced.


**Phase 1 — inventory.** 20 repos, 6 public at the time. Findings that corrected
the original brief: this repo had **zero commits** (not a weak README — an empty
repo); all three `ulpf` releases were **drafts** with **empty bodies**, so its
README's "Get it" section pointed at an empty page; and the `gh` token lacked the
`user` scope needed for `PATCH /user`.

**Phase 2 — ulpf release.** Verified before publishing, not after:
- All 3 CLI binaries checksum-matched `SHA256SUMS`; file types correct per target
  (Mach-O arm64, PE32+, ELF static-pie musl).
- Ran the Windows binary through the README's own documented path: `check`,
  `run` (309 events, 15 parsers), `verify` (309 records, chain ok), `attest`,
  `raw`, `pivot`. It does what the README says.
- The 267 MB Windows installers are **deliberate**, not a packaging fault: commit
  `c6400e3` set `webviewInstallMode: offlineInstaller`, embedding the WebView2
  runtime. Magic bytes on all four installers verified via HTTP range requests.
- Added the missing MIT `LICENSE` (`Cargo.toml` declared MIT; the file was
  absent, so it was legally all-rights-reserved with an outside fork already).
- Published `v0.1.0-rc3` as a **pre-release** with real notes. All 8 assets
  verified reachable anonymously at HTTP 200.

**Repo hygiene.** `luminfaber` → private, `study-tracker` → private (deletion
would have needed the `delete_repo` scope, which `repo` does not include; user
chose private, which is equivalent for profile purposes and reversible).

**Phases 3–6 — the profile itself.** Hero + five generated panels + one workflow
+ `CLAUDE.md`. All constraints and the rendering gotchas are documented in
`CLAUDE.md`; do not rediscover them.

**Account metadata.** bio, blog, location, `twitter_username`, and a LinkedIn
social account all set via the API. Repo description, homepage and topics set.

## Measured, not assumed

- **Asset cache staleness for a logged-out visitor: ~262 seconds.** README images
  in the *same repo* are **not** proxied through camo — GitHub rewrites them to
  `/<user>/<repo>/raw/main/...`, a 302 with `Cache-Control: no-cache`, which
  redirects to `raw.githubusercontent.com` where the asset carries
  `max-age=300` behind Fastly. Pushed a change and polled the ETag: it flipped
  after 262 s. **No cache-busting query parameter is needed or useful.**
- **`GITHUB_TOKEN` can read the contribution calendar.** The runner returned
  4,250 contributions against the owner PAT's 4,249 — a difference of exactly the
  one commit made in between, not a visibility gap. No PAT secret required. This
  holds because `restrictedContributionsCount` is 0; it would diverge if private
  contributions were ever counted.
- **Row alignment: 0 px spread** across every row of every panel, pixel-measured
  with Pillow, down from 1142 px before the `line()` refactor.

**Pinned repositories cannot be set through any API.** GraphQL exposes only
`pinIssue`, `pinIssueComment`, `pinEnvironment` — there is no repository-pinning
mutation, and REST has no endpoint.

**Second pass.** The open-source section became an index (one hook per project
plus a generated metadata strip, verified to still scan at eight entries in a
390px viewport). The hero was rebuilt on rule 110 seeded by the real contribution
year, replacing a scanline sweep and fade-in. The palette widened so colour
carries language and release state. Panels were narrowed after the live page
showed them downscaling to ~4px type on a phone.

Degradation exercised, all four passing: a generator raising, an empty data
source, a bad token, and a banned URL injected into an asset.

**Third pass — monochrome.** Warm phosphor was removed rather than retuned; see
CLAUDE.md for why and for the note that stops it being reintroduced. Every panel
and the hero now share one width (`COLS = 61`) and one font size. The stack row
left the hero SVG and became clickable generated badges in the README, because an
`<img>` cannot hold a clickable region. The commit ticker was cut.

Two defects found by measuring, not by looking:
- the automaton field had no `textLength`, so it stopped at **72.6%** of the
  panel and left a bald right margin behind a hard seam (the vignette hid it);
  now 99.9%
- the hero rendered *smaller* on screen than the panels below it, at 732 units
  against 514-581

**Fourth pass — voice, a live panel, and a transmutation.**

- **Nothing on the page names an absence any more.** The stats footer said "no
  stars, no followers" and its `<desc>` said it a second time for screen readers;
  the vysted-terminal badge said "v0.8.0 tagged, no release" across its pill, its
  `<title>` and the README alt text; the "Currently building" paragraph confessed
  that a benchmark figure was "sitting in the README unpromoted". All gone. The
  account **bio** carried the same slogan as the intro and was changed with it.
  Kept deliberately: real counts (3 repositories, 6 releases) and "0 broken" in
  the chain panel, which is a pass rather than a deficit. See CLAUDE.md § Voice.
- **The activity graph is cut** — it duplicated GitHub's own contribution
  calendar, two screens below it on the same page. Its slot now holds
  `inflight.svg`: commits ahead of each repository's newest tag. The live profile
  page was enumerated first; release and tag state is the one substantial thing
  about these repos that GitHub shows nowhere.
- **The hero is a transmutation**, replacing rule 110, which was a real mechanism
  that never resolved into anything and came out ~5px on a phone. Two rival
  concepts were built, rasterised at the real 847px column and rejected on the
  evidence; see CLAUDE.md.
- The hero now makes **no API call at all**, which removes the last failure
  surface from the one image that must never break.

Three defects found by rasterising and by watching the file in a browser:
- the animated hero rasterised **completely blank** — `frame_css` set `opacity:0`
  in a CSS rule, which outranks the presentation attribute carrying each group's
  base state. Only the per-frame stills had been rasterised, never the animated
  file itself.
- a solid `U+2588` bar is **not** solid inside a row that `lengthAdjust="spacing"`
  is correcting; it comes out as ragged fringed segments. Now a discrete `U+25A0`
  meter, where the gaps are the design.
- `resvg` lays the rows out at natural advance rather than honouring `textLength`,
  so the ASCII frame measures ~88% of the canvas there and 96% in a browser. A
  rasteriser artifact, **not** a defect — confirmed in Chrome before acting.

**Fifth pass — the page had become a page about one repo.**

Counted rather than felt: the hero animated log parsing, the integrity panel
closed by calling a hash chain "the thing ulpf builds for logs", the stats panel
ranked "Rust, bytes" above "TypeScript, bytes", and "Currently building" named
only ulpf. Four elements, each defensible alone; together a stranger would have
said "security logging engineer who also wrote a timer app". See CLAUDE.md
§ Balance for the rule that stops it recurring, including *why* it happened —
log parsing won on being the easiest thing on the account to draw.

- **The hero is now a rearrangement**, not a pipeline, because a generic pipeline
  is the log animation wearing a costume. Two sentences interleaved character by
  character, separating by merge rounds; nothing added, nothing removed. Two
  rivals were built and rasterised at 847px first — a watch escapement and a
  pruned decision tree — and both are recorded in CLAUDE.md with why they lost.
- **INTEGRITY → PROVENANCE**, with the ulpf sentence gone. The mechanism is
  git's; every repository listed is in it equally.
- **Languages are an alphabetical set**, no byte counts, cut at a tenth of all
  bytes. At 4% Shell qualified by 294 bytes out of 5.3 million.
- **"Currently building" covers all three**, one line each, from real recent work.

Found by rasterising the animated file rather than the stills: the first merge
operator was a de-interleave, which is *not* the inverse of an interleave — the
animation resolved into gibberish. `gen_hero()` now asserts the separation and
raises rather than shipping it.

## Open / not done by me

- **Pinned repositories cannot be set through any API** (see above). The profile
  repo `techlogist1` is currently pinned alongside the three projects and needs
  **unpinning by hand** in the web UI to reach the intended set.
- **`vysted.com` has no A record**, so it is unlinked in the README. Point the
  domain at its deployment and restore the link.
