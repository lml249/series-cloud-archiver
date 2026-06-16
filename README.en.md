# Series Cloud Archiver

Spec-driven plan for safely moving completed TV series from local seeding storage
to cloud-backed STRM library entries.

The project is designed as an independent orchestrator. MoviePilot, Emby,
qBittorrent, MediaVault/MV3, and a cloud drive provider are treated as external
systems. A MoviePilot plugin can be added later as a thin bridge for status,
manual triggers, or notifications, but it is not the v1 source of truth.

## Problem

TV series subscriptions can fill local disks after a show finishes. The desired
workflow is:

1. Detect that a subscribed series is complete.
2. Find or transfer a complete playable copy to cloud storage through MV3.
3. Generate STRM entries and refresh Emby.
4. Verify that Emby sees a complete playable STRM version.
5. Keep the original qBittorrent task seeding for at least 7 days.
6. Remove only the local torrent, local content, and hlink files after every
   safety gate passes.

## Non-goals for the first milestone

- No production runtime code in this repository yet.
- No direct publishing of a private media library, real paths, IP addresses,
  tokens, cookies, pickcodes, or STRM redirect URLs.
- No automatic deletion unless a dry-run result and all verification gates pass.
- No requirement that the cloud copy matches the local release group exactly.

## Current artifacts

- [Constitution](.specify/memory/constitution.md)
- [Feature specification](specs/001-series-cloud-archiver/spec.md)
- [Implementation plan](specs/001-series-cloud-archiver/plan.md)
- [Research decisions](specs/001-series-cloud-archiver/research.md)
- [Data model](specs/001-series-cloud-archiver/data-model.md)
- [Adapter contracts](specs/001-series-cloud-archiver/contracts/adapter-contracts.md)
- [Validation quickstart](specs/001-series-cloud-archiver/quickstart.md)
- [Implementation tasks](specs/001-series-cloud-archiver/tasks.md)
- [Security policy](docs/security.md)
- [Ten-pass review](docs/ten-pass-review.md)

## Validate the plan

```bash
bash scripts/validate-plan.sh
```

## Safety model

The orchestrator is conservative by default:

- Missing evidence blocks cleanup.
- Conflicting evidence blocks cleanup.
- Failed provider calls are retried or escalated, not silently ignored.
- All cleanup actions are idempotent and recorded.
- Dry-run is the default mode.
- Manual approval is required before destructive actions until the project has
  proven safety in real deployments.

## Readonly scan MVP

The repository now includes the first readonly scanner. It identifies candidates
only; it does not transfer, generate STRM files, or delete anything.

```bash
PYTHONPATH=src python3 -m series_cloud_archiver scan \
  --media-root /media/local-series \
  --no-qb \
  --min-age-days 0 \
  --format markdown
```
