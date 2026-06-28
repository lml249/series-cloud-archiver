# Security and Privacy Policy

This repository is public-safe by design. It must never contain real deployment
details from a private media library.

## Never commit

- API tokens, cookies, passwords, session IDs, or refresh tokens
- Cloud drive pickcodes, share passwords, or direct STRM redirect URLs
- Real LAN addresses from private address ranges
- Real NAS mount paths, volume names, download paths, hlink paths, or library
  paths
- Real media inventory exports, qBittorrent lists, Emby library dumps, or MV3
  transfer logs
- Runtime databases, dry-run reports from a real deployment, or cleanup logs

## Allowed examples

Use placeholders and `.local` hostnames:

- `http://moviepilot.local:3000`
- `http://mediavault.local:7811`
- `http://emby.local:8096`
- `http://qbittorrent.local:8080`
- `/media/local-series`
- `/media/cloud-strm`

## Redaction checklist before publishing

Run these checks before every public push. They are intentionally conservative;
review any hit before publishing:

```bash
rg -n "[0-9]{1,3}(\\.[0-9]{1,3}){3}" .
rg -n -i "(token|cookie|password|passwd|api[_-]?key|secret)\\s*[:=]" .
rg -n "/volume[0-9]+|/mnt/|/downloads/|/media/" .
```

Findings in documentation examples are acceptable only when they are obvious
placeholders and do not identify a real deployment.

## Destructive operation policy

Cleanup can be implemented only when all of these are true:

1. The target item has a completed cloud-backed STRM set.
2. Emby recognizes every expected episode.
3. A playback probe succeeds for at least one representative episode per season,
   plus every episode that was previously missing or repaired.
4. qBittorrent proves the task has seeded for at least the configured minimum
   number of days.
5. The local deletion set is limited to the qBittorrent task content and known
   hlink paths for that exact item.
6. A dry-run report was generated and approved.

If any condition is missing, weak, stale, or contradictory, the orchestrator
must preserve local data.

When MoviePilot history and qBittorrent tasks are already gone, orphan cleanup
is allowed only through explicit per-season preview/execute reports. Those
reports must recheck STRM coverage, cloud-media sidecar absence, qB current task
file lists and source paths, and a narrow hlink or source root before deleting
that one root. This path must never be used for a normal seeded qB task.

## Cloud media scraping boundary

Cloud media directories are transfer and STRM-generation sources only. Scraping
must happen against STRM-backed library paths, not beside the cloud media files.

- MV3 organize transfer requests should submit media files only and should not
  copy non-media metadata sidecars into the cloud media directory.
- Browse reports must be reclassified by filename extension before organize
  transfer so unmarked `.nfo`, `.jpg`, `.jpeg`, `.png`, or `.webp` files cannot
  be submitted as media files.
- `.nfo`, `.jpg`, `.jpeg`, `.png`, and `.webp` files found beside cloud media are
  treated as metadata sidecars, not cleanup evidence.
- STRM NFO language or scraping-quality audits must run against STRM-backed
  library paths only. Passing cloud media paths such as `/已整理` or `/未整理`
  is blocked because cloud media metadata is not the source of truth. Bare
  `/series/...` paths are also rejected; STRM-side paths must live under a
  clear STRM root such as `/strm`, `.../mv3/strm`, or `cloud-strm`.
- Local cleanup must stay blocked while cloud media metadata sidecars are
  present.
- Removing cloud media metadata sidecars requires a dry-run report, an explicit
  approval flag, and an expected delete count. Video files and subtitle sidecars
  must not be selected by that cleanup path.
- Standalone MV3 STRM generation is STRM-only. Its `organize` parameter is
  always blocked, even when an old command passes the compatibility
  `allow-organize` flag, so cloud media organization remains confined to the
  audited organize-transfer flow. Its target directory must be STRM-side, never
  a cloud media or bare category directory.
