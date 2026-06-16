<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- [PRINCIPLE_1_NAME] -> No Unverified Deletion
- [PRINCIPLE_2_NAME] -> Public-Safe by Default
- [PRINCIPLE_3_NAME] -> Durable State Machine
- [PRINCIPLE_4_NAME] -> Adapter Boundaries
- [PRINCIPLE_5_NAME] -> Observable, Testable Operations
Added sections:
- Safety Constraints
- Development Workflow
Removed sections:
- Placeholder template guidance
Templates requiring updates:
- .specify/templates/plan-template.md: checked, feature plan carries the gates
- .specify/templates/spec-template.md: checked, no template change required
- .specify/templates/tasks-template.md: checked, feature tasks carry safety tasks
Follow-up TODOs: none
-->

# Series Cloud Archiver Constitution

## Core Principles

### I. No Unverified Deletion

The system MUST preserve local data unless every cleanup gate has fresh,
consistent evidence. Cleanup requires cloud STRM generation, Emby completeness
verification, playback probes, qBittorrent seed-age proof, deletion-scope proof,
and an approved dry-run report. Missing, stale, weak, or contradictory evidence
MUST block deletion.

### II. Public-Safe by Default

The public project MUST NOT contain real tokens, cookies, pickcodes, STRM
redirect URLs, LAN IP addresses, NAS mount paths, media inventory exports, or
private operational logs. Examples MUST use placeholders and `.local` hostnames.
Runtime state, reports, and secrets MUST be excluded from version control.

### III. Durable State Machine

Each series moves through explicit states with recorded evidence and timestamps.
Operations MUST be idempotent: repeating a step either completes the same
transition, proves it is already complete, or records a blocked/failed state.
Partial failure MUST NOT leave the system guessing whether local data is safe to
delete.

### IV. Adapter Boundaries

MoviePilot, MV3, Emby, qBittorrent, metadata providers, and cloud storage MUST be
accessed through narrow adapters. The orchestrator is the source of truth for
decisions. A MoviePilot plugin, if added later, MUST remain a thin bridge for
triggers or status and MUST NOT own cleanup decisions.

### V. Observable, Testable Operations

Every decision MUST explain which evidence was used, which gate passed or
failed, and what action was taken. Destructive behavior MUST have contract tests,
state-machine tests, dry-run tests, and integration tests with mocked providers
before it can be enabled against a real deployment.

## Safety Constraints

- Dry-run mode is the default.
- Manual approval is required for cleanup until the project has a proven safety
  record.
- Title matching alone is never sufficient for cleanup.
- Glob-based or broad directory deletion is forbidden.
- Cloud versions must be complete and playable, but do not need to match the
  local release group exactly.
- The minimum qBittorrent seed duration defaults to 7 days.

## Development Workflow

1. Update the feature specification before changing scope.
2. Update the implementation plan before changing architecture.
3. Add or update adapter contracts before relying on provider behavior.
4. Add tests before enabling destructive actions.
5. Run the public-safety redaction checks before every public push.
6. Keep real deployment configuration outside the repository.

## Governance

This constitution overrides conflicting implementation preferences. Amendments
require a documented reason, a version bump, and review of the specification,
plan, contracts, quickstart, and tasks for consistency. Versioning follows
semantic versioning: MAJOR for changed safety guarantees, MINOR for new
principles or sections, and PATCH for clarifications.

**Version**: 1.0.0 | **Ratified**: 2026-06-17 | **Last Amended**: 2026-06-17
