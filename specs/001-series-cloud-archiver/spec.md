# Feature Specification: Series Cloud Archiver

**Feature Branch**: `001-series-cloud-archiver`

**Created**: 2026-06-17

**Status**: Draft

**Input**: User description: "After subscribed TV series finish, transfer or find
the completed series in cloud storage through MV3, generate STRM entries, verify
the cloud library in Emby, keep qBittorrent seeding for 7 days, then delete the
local torrent, local files, torrent file, and hlink files safely."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Identify safe archive candidates (Priority: P1)

As a media library owner, I want the system to identify completed series that are
eligible for cloud archiving, so I can free local series storage without checking
every subscription manually.

**Why this priority**: No later transfer or cleanup step is safe unless the
system first proves which series are actually complete.

**Independent Test**: Provide a mocked library with one ended complete series,
one ongoing series, and one ended incomplete series. Only the ended complete
series becomes a candidate.

**Acceptance Scenarios**:

1. **Given** a series is marked ended by metadata and all expected episodes are
   present in the local/Emby view, **When** the evaluation runs, **Then** the
   series is marked as an archive candidate.
2. **Given** a series is ongoing or has missing expected episodes, **When** the
   evaluation runs, **Then** the series is blocked from archiving with a reason.

---

### User Story 2 - Create and verify cloud STRM coverage (Priority: P1)

As a media library owner, I want completed series to be represented by cloud
STRM entries and verified in Emby, so local files are not removed until the cloud
library can replace them.

**Why this priority**: The core value is freeing local storage only after Emby
has a usable cloud-backed replacement.

**Independent Test**: Provide a mocked candidate and mocked MV3/Emby responses.
The system advances only when STRM generation, Emby episode coverage, and
playback probes succeed.

**Acceptance Scenarios**:

1. **Given** a candidate has a complete cloud version available, **When** STRM
   generation and Emby refresh complete, **Then** every expected episode is
   matched to a cloud-backed STRM entry.
2. **Given** a cloud version is missing episodes or cannot be probed, **When**
   verification runs, **Then** the system keeps the local files and records a
   blocked state.

---

### User Story 3 - Clean up local seeding files safely (Priority: P1)

As a media library owner, I want the system to remove local qBittorrent content
and hlink files only after seeding and cloud verification gates pass, so I can
recover disk space without accidental data loss.

**Why this priority**: Cleanup is the highest-risk action and must be correct
before the workflow can be trusted.

**Independent Test**: Provide mocked qBittorrent seeding history, dry-run output,
and deletion targets. Cleanup is allowed only after the minimum seed duration and
all verification gates pass.

**Acceptance Scenarios**:

1. **Given** a verified STRM replacement, a qBittorrent task seeded for at least
   7 days, and an approved dry-run, **When** cleanup runs, **Then** only the
   matched torrent task content and known hlink paths are removed.
2. **Given** any cleanup gate is missing, stale, or failed, **When** cleanup is
   requested, **Then** no local file deletion occurs.

---

### User Story 4 - Review status and failures (Priority: P2)

As a media library owner, I want readable status and failure reasons for each
series, so I know whether an item is waiting, blocked, verified, or cleaned.

**Why this priority**: The workflow crosses several systems, so clear status is
needed for trust and manual repair.

**Independent Test**: Load sample items in each state and verify the report shows
the current state, last evidence, next action, and blocking reason.

**Acceptance Scenarios**:

1. **Given** an item failed MV3 transfer, **When** I view its status, **Then** I
   see the failing provider, last attempt time, and safe next action.
2. **Given** an item is waiting for seed age, **When** I view its status, **Then**
   I see the earliest cleanup date.

---

### User Story 5 - Trigger from MoviePilot without coupling to it (Priority: P3)

As a media library owner, I may want MoviePilot to trigger or display archiver
status, so the workflow feels integrated without making MoviePilot responsible
for dangerous cleanup decisions.

**Why this priority**: This improves convenience but is not required for the
safe v1 workflow.

**Independent Test**: Send a mock MoviePilot event to the orchestrator. The event
creates or refreshes an evaluation request, but cleanup decisions remain in the
orchestrator.

**Acceptance Scenarios**:

1. **Given** a MoviePilot event says a subscribed series updated, **When** the
   bridge sends the event, **Then** the orchestrator queues evaluation.
2. **Given** MoviePilot is unavailable, **When** scheduled evaluation runs,
   **Then** the orchestrator can still continue using other configured evidence.

### Edge Cases

- Metadata says a show ended, but Emby or the local inventory is missing one or
  more regular episodes.
- Specials, alternate numbering, split seasons, or anime-style absolute episode
  numbering create ambiguous expected episode lists.
- MV3 finds a cloud version with the same title but a different year, region, or
  episode mapping.
- STRM files exist but Emby has not refreshed them yet.
- Emby lists episodes but playback probes fail.
- qBittorrent reports a task but the content path is no longer present.
- hlink paths overlap with other series or seasons.
- Provider APIs time out, return partial data, or change response shape.
- The same item is evaluated twice while a previous transfer is still running.
- A manual repair replaces an episode after a previous verification failed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST maintain a durable record for each tracked series
  and its current archive state.
- **FR-002**: The system MUST identify archive candidates only when metadata says
  the series ended and the expected episode set is complete.
- **FR-003**: The system MUST record a blocking reason when a series is ongoing,
  incomplete, ambiguous, or missing reliable metadata.
- **FR-004**: The system MUST request or verify a cloud-backed version through an
  MV3-compatible workflow.
- **FR-005**: The system MUST accept cloud versions that differ from local
  release groups when the episode set is complete and playable.
- **FR-006**: The system MUST generate or verify STRM entries before local
  cleanup can be considered.
- **FR-007**: The system MUST verify that Emby recognizes every expected episode
  from STRM-backed media before cleanup.
- **FR-008**: The system MUST perform playback probes according to a documented
  policy before cleanup.
- **FR-009**: The system MUST require qBittorrent evidence that the matched task
  has seeded for at least the configured minimum duration, defaulting to 7 days.
- **FR-010**: The system MUST produce a dry-run cleanup report before any
  destructive cleanup action.
- **FR-011**: The system MUST require manual approval for destructive cleanup in
  the first milestone.
- **FR-012**: The system MUST limit deletion to the matched qBittorrent task
  content, torrent task, torrent metadata when available, and known hlink paths
  for the exact series item.
- **FR-013**: The system MUST preserve local data if any verification evidence is
  missing, stale, weak, failed, or contradictory.
- **FR-014**: The system MUST record an audit event for every state transition,
  provider call result, dry-run, approval, and cleanup attempt.
- **FR-015**: The system MUST be able to resume safely after interruption without
  duplicating transfers or repeating destructive actions incorrectly.
- **FR-016**: The system SHOULD provide a MoviePilot bridge for trigger/status
  convenience after the independent orchestrator is functional.
- **FR-017**: The system MUST avoid storing real secrets in project files and
  MUST read deployment secrets from local configuration or secret storage.
- **FR-018**: The system MUST expose enough status for a user to understand why
  each item is pending, blocked, verified, failed, or cleaned.

### Key Entities

- **SeriesItem**: A tracked TV series or season group being evaluated for cloud
  archiving.
- **EpisodeExpectation**: The expected season and episode list derived from
  metadata and library evidence.
- **CloudCandidate**: A possible cloud-backed version found or transferred by an
  MV3-compatible workflow.
- **StrmSet**: The generated STRM files and their mapping to expected episodes.
- **VerificationEvidence**: Time-stamped proof from metadata, Emby, playback
  probes, qBittorrent, and MV3.
- **CleanupPlan**: The dry-run deletion set and approval status for one item.
- **AuditEvent**: Immutable record of decisions, provider responses, and actions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a mocked library with complete, incomplete, and ongoing series,
  100% of incomplete or ongoing series are blocked from cleanup.
- **SC-002**: Cleanup cannot be executed unless every required gate has passing
  evidence and a dry-run report.
- **SC-003**: The system can recover from interrupted transfer, verification, and
  cleanup-wait states without losing the current item state.
- **SC-004**: A user can read a status report for any item and identify the next
  required action or blocking reason in under one minute.
- **SC-005**: In dry-run mode, the system produces the exact deletion target list
  without deleting files.
- **SC-006**: Public repository checks find no real private deployment details.

## Assumptions

- The first milestone is a plan/specification repository, not production runtime
  code.
- The v1 product is an independent orchestrator.
- MoviePilot integration is optional and thin.
- MV3 can be integrated through an adapter; if no stable API exists, manual
  checkpoints can be used while preserving the same cleanup gates.
- Emby is the playback/library verification source.
- qBittorrent is the local seeding source.
- The default minimum seed duration is 7 days.
- Real deployment configuration lives outside the public repository.

