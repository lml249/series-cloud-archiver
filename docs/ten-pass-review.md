# Ten-Pass Review

Date: 2026-06-17

This review records the planned safety checks for the first public planning
version. Each pass is designed to catch a different class of loophole.

## Pass 1: Public repository hygiene

Result: Passed.

- No real hostnames, LAN IP addresses, NAS paths, pickcodes, tokens, cookies, or
  media inventory data are required in the public plan.
- `.env.example` uses placeholders only.
- `.gitignore` excludes runtime state, reports, databases, logs, secrets, and
  local agent state.

## Pass 2: Architecture boundary

Result: Passed.

- The orchestrator is the source of truth.
- MoviePilot plugin work is explicitly optional and thin.
- Provider adapters are replaceable, so MV3 uncertainty does not leak into core
  cleanup decisions.

## Pass 3: Completion detection

Result: Passed.

- Completion requires metadata saying the series ended and Emby/local inventory
  showing every expected episode.
- Ambiguous specials, split seasons, renumbered episodes, or missing metadata
  block cleanup.

## Pass 4: Cloud copy validation

Result: Passed.

- The cloud copy does not need to be the same release group as the local copy.
- It must be complete, mapped to the same series, visible through STRM, and
  playable enough to satisfy the verification policy.

## Pass 5: Cleanup safety

Result: Passed.

- Cleanup requires STRM generation, Emby verification, playback probes,
  qBittorrent minimum seeding age, and a dry-run report.
- Weak or stale evidence preserves local data.

## Pass 6: Idempotency and recovery

Result: Passed.

- Every transition is state-machine based.
- Re-running a step must either finish the same transition or prove why it is
  blocked.
- Partial failures move items into explicit `failed_*` states.

## Pass 7: MV3 assumptions

Result: Passed with caveat.

- The plan assumes MV3 has some callable interface for search/transfer/STRM
  generation, but the adapter contract is abstract.
- If MV3 lacks a stable API, v1 can use manual import checkpoints while keeping
  cleanup safety gates unchanged.

## Pass 8: qBittorrent and hlink scope

Result: Passed.

- Deletion scope is limited to the matched qBittorrent task content and known
  hlink files for the exact item.
- The plan forbids broad path cleanup, glob-based deletion, and cleanup based on
  title matching alone.

## Pass 9: Observability and auditability

Result: Passed.

- Required evidence includes source, timestamp, input identity, result, and
  decision.
- Dry-run reports explain why an item is safe or blocked.

## Pass 10: Testability and acceptance

Result: Passed.

- The spec has independent user stories.
- The plan includes contract, integration, state-machine, and destructive-action
  safety tests before implementation.
- The quickstart defines validation scenarios that can be run with mocks before
  any real deletion is enabled.

## Remaining caveats

- MV3's exact local interface must be confirmed during implementation.
- Real media-library edge cases should be tested with redacted fixtures only.
- Automatic cleanup should remain disabled until repeated real dry-runs match
  manual expectations.

