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

## Open / not done by me

- **Pinned repositories cannot be set through any API** (see above). The profile
  repo `techlogist1` is currently pinned alongside the three projects and needs
  **unpinning by hand** in the web UI to reach the intended set.
- **`vysted.com` has no A record**, so it is unlinked in the README. Point the
  domain at its deployment and restore the link.
