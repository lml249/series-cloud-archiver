# Adapter Contracts

These contracts describe the behavior the orchestrator expects from external
systems. Exact HTTP endpoints or libraries can change during implementation, but
the core workflow must depend only on these capabilities.

## Common adapter rules

Every adapter method returns:

- `ok`: true or false
- `observed_at`: timestamp
- `source`: provider name and version when available
- `summary`: redacted human-readable summary
- `evidence_ref`: local reference to raw evidence, never committed publicly
- `error`: structured error when `ok` is false

Adapters must redact secrets and direct playback URLs from summaries.

## Metadata / MoviePilot adapter

Capabilities:

- Resolve series identity from known external IDs or title/year.
- Report whether the series is ended, continuing, cancelled, or unknown.
- Provide expected season/episode lists when available.
- Accept optional events from MoviePilot to trigger evaluation.

Safety requirements:

- Unknown status blocks cleanup.
- Title-only matches can trigger evaluation but cannot authorize cleanup.
- MoviePilot events are hints, not final cleanup decisions.

## MV3 adapter

Capabilities:

- Search for a complete cloud candidate.
- Start transfer/save for a selected cloud candidate when needed.
- Report transfer progress.
- Trigger or confirm STRM generation.
- Return a redacted episode-to-STRM mapping.

Safety requirements:

- The adapter must never expose pickcodes, cookies, or direct STRM redirect URLs
  in public logs.
- A candidate with missing or ambiguous episode mapping blocks cleanup.
- If MV3 has no stable API, the adapter may expose manual checkpoint methods
  while preserving the same state transitions.

## Emby adapter

Capabilities:

- Refresh or scan the relevant library path.
- Resolve a series in Emby by external IDs or controlled mapping.
- Return the episode list Emby sees.
- Identify whether episodes are backed by STRM paths.
- Probe playback according to configured policy.

Safety requirements:

- Emby seeing a title is not enough; every expected episode must be mapped.
- Playback probe failures block cleanup.
- Missing refresh completion blocks cleanup until retried or manually resolved.

## qBittorrent adapter

Capabilities:

- Find torrent tasks associated with a series item.
- Return content paths, task hash, completion state, ratio, and seeding time.
- Pause/remove torrent tasks only after cleanup approval.
- Report whether torrent metadata can be removed.

Safety requirements:

- Seed age must be at least the configured minimum, default 7 days.
- Multiple possible torrent matches require manual resolution.
- Deletion must target the exact matched task, not title globs.

## Filesystem / hlink adapter

Capabilities:

- Build a dry-run target list for local content and hlink paths.
- Detect path overlap with unrelated items.
- Execute approved deletions idempotently.
- Record missing paths as already-clean or blocked depending on context.

Safety requirements:

- Broad directory deletion is forbidden.
- Symlink/hardlink/hlink semantics must be identified before deletion.
- If a path cannot be proven owned by the target item, it is preserved.

## Orchestrator admin surface

Planned minimal operations:

- `evaluate(series_ref)`: collect evidence and update state.
- `dry_run_cleanup(series_id)`: produce a cleanup plan without deleting.
- `approve_cleanup(series_id, dry_run_id)`: record manual approval.
- `execute_cleanup(series_id, dry_run_id)`: delete only approved targets.
- `status(series_id)`: return state, evidence, next action, and blockers.

All destructive operations must reject requests when dry-run evidence is stale,
approval is missing, or the item state changed after approval.

