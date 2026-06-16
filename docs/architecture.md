# Architecture Decision

## Decision

Use an independent orchestrator for v1. Add a MoviePilot plugin later only as a
thin bridge if the user experience needs it.

## Why not a pure MoviePilot plugin?

The core workflow spans systems that MoviePilot does not fully control:

- MV3 transfer/search/STRM behavior
- Emby library verification and playback checks
- qBittorrent seeding age and deletion behavior
- local hlink cleanup
- durable state, audit history, and recovery after partial failure

Putting this logic inside a plugin would couple safety-critical cleanup to
MoviePilot's plugin lifecycle. An independent orchestrator can remain stable
across MoviePilot upgrades and can be tested without a live media stack.

## Optional MoviePilot bridge

A later bridge can provide:

- "evaluate this series" trigger
- status display inside MoviePilot
- notification forwarding
- link to dry-run cleanup reports

The bridge must not be the source of truth and must not execute destructive
cleanup directly.

## High-level flow

```text
MoviePilot / Metadata / Emby / qBittorrent / MV3
                  |
                  v
        Series Cloud Archiver
                  |
     state machine + audit log + safety gates
                  |
                  v
       STRM verified or local data preserved
```

