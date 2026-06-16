# Implementation Plan: Series Cloud Archiver

**Branch**: `001-series-cloud-archiver` | **Date**: 2026-06-17 |
**Spec**: [spec.md](spec.md)

**Input**: Feature specification from
`/specs/001-series-cloud-archiver/spec.md`

## Summary

Build an independent orchestration service that watches completed TV series,
coordinates cloud STRM creation through an MV3-compatible adapter, verifies the
replacement in Emby, waits for qBittorrent seeding requirements, and only then
produces or executes a narrowly scoped cleanup plan. MoviePilot is a source of
signals and an optional future UI bridge, not the system of record.

## Technical Context

**Language/Version**: Python 3.12 planned for implementation; this milestone is
documentation only.

**Primary Dependencies**: HTTP client, scheduler/worker, SQLite-compatible
persistence, structured logging, test runner. Exact libraries are deferred until
runtime implementation.

**Storage**: Local SQLite database for orchestrator state and append-only audit
events; runtime databases are ignored by git.

**Testing**: Contract tests for adapters, unit tests for state transitions,
integration tests with mocked MP/MV3/Emby/qB providers, filesystem safety tests,
and dry-run acceptance tests.

**Target Platform**: Self-hosted Linux or NAS-adjacent container with network
access to MoviePilot, MV3, Emby, qBittorrent, and cloud-drive tooling.

**Project Type**: Independent orchestrator/service with CLI or small admin API.
Optional MoviePilot bridge can be added later as a separate package.

**Performance Goals**: Handle typical personal-media-library scale, with
hundreds to low thousands of tracked series and scheduled evaluations that do
not overload provider APIs.

**Constraints**: Dry-run default; manual approval before cleanup; no real
secrets in repository; provider failures must be safe; no broad path deletion.

**Scale/Scope**: Single-user self-hosted media library automation. Multi-user
SaaS, cloud-hosted control planes, and generic media management are out of
scope for v1.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **No Unverified Deletion**: PASS. Cleanup is gated by STRM generation, Emby
  verification, playback probes, seed duration, deletion-scope proof, dry-run,
  and manual approval.
- **Public-Safe by Default**: PASS. All documentation uses placeholders and the
  repository ignores runtime secrets, reports, logs, and agent state.
- **Durable State Machine**: PASS. The data model includes explicit states,
  transitions, evidence, and idempotency rules.
- **Adapter Boundaries**: PASS. MP, MV3, Emby, qBittorrent, metadata, and
  filesystem cleanup are separate adapters.
- **Observable, Testable Operations**: PASS. Tasks require contract,
  state-machine, integration, and dry-run tests before destructive behavior.

## Project Structure

### Documentation (this feature)

```text
specs/001-series-cloud-archiver/
├── plan.md
├── spec.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── checklists/
│   └── requirements.md
└── contracts/
    └── adapter-contracts.md
```

### Planned Source Code (future implementation)

```text
src/series_cloud_archiver/
├── adapters/
│   ├── moviepilot.py
│   ├── mv3.py
│   ├── emby.py
│   ├── qbittorrent.py
│   └── filesystem.py
├── core/
│   ├── state_machine.py
│   ├── gates.py
│   ├── matching.py
│   └── cleanup.py
├── storage/
│   ├── models.py
│   └── repository.py
├── api/
│   └── routes.py
└── cli.py

tests/
├── contract/
├── integration/
├── safety/
└── unit/
```

**Structure Decision**: Keep the orchestrator as a single project until the core
state machine and adapter contracts are stable. Add a separate MoviePilot bridge
package only after v1 safety gates are proven.

## Phase 0: Research Decisions

See [research.md](research.md).

Key decisions:

- Independent orchestrator instead of pure MoviePilot plugin.
- Cloud completion can come from MV3 transfer/search rather than local upload.
- Cleanup requires both metadata completion and Emby STRM verification.
- Local release/version matching is not required when the cloud version is
  complete and playable.
- Manual approval and dry-run remain mandatory for the first milestone.

## Phase 1: Design and Contracts

Design artifacts:

- [data-model.md](data-model.md)
- [contracts/adapter-contracts.md](contracts/adapter-contracts.md)
- [quickstart.md](quickstart.md)

### State Machine

```text
candidate
  -> mv3_transfer_started
  -> strm_generated
  -> emby_verified
  -> cleanup_waiting
  -> cleaned

Any state can move to a specific failed_* state with evidence.
Recovery returns to the last safe non-destructive state.
```

Required failure states:

- `failed_metadata`
- `failed_mv3_search`
- `failed_mv3_transfer`
- `failed_strm_generation`
- `failed_emby_verification`
- `failed_playback_probe`
- `failed_seed_age`
- `failed_cleanup_scope`
- `failed_cleanup_execution`

### Cleanup Gate

Cleanup can be planned only when all evidence is present:

1. Series identity is resolved.
2. Expected episode set is complete.
3. Metadata says the series ended or was manually locked as complete.
4. MV3/cloud candidate maps to the expected episode set.
5. STRM files exist for every expected episode.
6. Emby sees every expected STRM-backed episode.
7. Playback probe policy passes.
8. qBittorrent seed duration is at least the configured minimum.
9. Deletion targets are exact and non-overlapping.
10. Dry-run report is generated and approved.

### Provider Configuration Placeholders

```text
MP_BASE_URL=http://moviepilot.local:3000
MV3_BASE_URL=http://mediavault.local:7811
EMBY_BASE_URL=http://emby.local:8096
QB_BASE_URL=http://qbittorrent.local:8080
```

These are examples only and must not be replaced with real values in the public
repository.

## Phase 2: Implementation Task Plan

See [tasks.md](tasks.md). The first implementation milestone should stop after
mocked providers, dry-run reports, and safety tests are green. Real cleanup
should remain disabled until repeated dry-runs are manually validated.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |

## Post-Design Constitution Check

- **No Unverified Deletion**: PASS. The cleanup gate is explicit and all weak
  evidence blocks cleanup.
- **Public-Safe by Default**: PASS. Redaction rules and `.gitignore` cover known
  private artifacts.
- **Durable State Machine**: PASS. States, failure states, and recovery behavior
  are documented.
- **Adapter Boundaries**: PASS. Contracts define external-provider boundaries.
- **Observable, Testable Operations**: PASS. Quickstart and tasks include mock
  validation before any real deletion.

