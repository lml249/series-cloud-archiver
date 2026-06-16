# Research Decisions

## Decision: Use an independent orchestrator for v1

**Rationale**: The workflow spans MoviePilot, MV3, Emby, qBittorrent, cloud
storage, and local filesystem cleanup. The safest component is a separate
orchestrator with durable state, testable adapter boundaries, and a cleanup gate
that is not tied to MoviePilot plugin lifecycle.

**Alternatives considered**:

- Pure MoviePilot plugin: convenient, but couples safety-critical deletion to
  plugin compatibility and makes MV3/qB/filesystem recovery harder.
- Pure scripts/cron: simple, but lacks durable state, visibility, and safe
  recovery after partial failures.

## Decision: Treat MoviePilot as signal source, not source of truth

**Rationale**: MoviePilot is useful for subscriptions and metadata signals, but
cleanup safety depends on Emby verification, qBittorrent seed duration, MV3 STRM
results, and exact deletion targets.

**Alternatives considered**:

- Use MoviePilot completion alone: unsafe because a completed subscription does
  not prove cloud playback or cleanup scope.

## Decision: Use MV3 adapter for cloud search/transfer/STRM operations

**Rationale**: The user has large cloud storage and MV3 can transfer completed
series and generate STRM entries. The orchestrator should call or guide MV3
without assuming a fixed API shape in the core logic.

**Alternatives considered**:

- Upload local qB content to cloud: slower, wastes bandwidth/storage, and is not
  necessary when a complete cloud copy exists.
- Manual-only MV3 workflow: safe as a fallback, but does not satisfy the desired
  automation goal.

## Decision: Accept equivalent complete cloud versions

**Rationale**: The goal is freeing local storage while preserving a playable
library. Requiring the cloud copy to match local release group/version would
block many safe archivals without improving the main user outcome.

**Alternatives considered**:

- Exact release matching: safer in a narrow sense, but too brittle and often
  unnecessary for watched-library use.

## Decision: Require metadata and Emby/library completeness

**Rationale**: Metadata can say whether a show ended, while Emby/library
evidence proves the expected episodes are actually represented. Both are needed
because either source can be incomplete or stale by itself.

**Alternatives considered**:

- Metadata only: unsafe when local/cloud files are missing episodes.
- Emby only: unsafe when a currently airing show has all currently released
  episodes but is not actually complete.

## Decision: Keep destructive cleanup manually approved at first

**Rationale**: The first real deployments need human review of dry-run deletion
sets. This protects against provider quirks, bad title matching, and hlink scope
mistakes.

**Alternatives considered**:

- Immediate full automation: higher risk before enough dry-run evidence exists.

## Decision: Make adapters contract-tested

**Rationale**: Provider APIs and local tools may change. Narrow contracts allow
the core state machine to stay stable and make provider breakage visible.

**Alternatives considered**:

- Inline provider calls inside the workflow: faster to prototype, but harder to
  test and recover.

