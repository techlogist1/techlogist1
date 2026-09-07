# Progress

A cold context should be able to pick up from this file plus `CLAUDE.md`.
Newest first.

## Done

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

## Open / not done by me

- **Pinned repositories cannot be set through any API** (see above). The profile
  repo `techlogist1` is currently pinned alongside the three projects and needs
  **unpinning by hand** in the web UI to reach the intended set.
- **`vysted.com` has no A record**, so it is unlinked in the README. Point the
  domain at its deployment and restore the link.
