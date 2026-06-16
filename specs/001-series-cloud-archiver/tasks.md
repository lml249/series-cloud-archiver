# Tasks: Series Cloud Archiver

**Input**: Design documents from `/specs/001-series-cloud-archiver/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required before any destructive operation is enabled.

## Phase 1: Setup

**Purpose**: Initialize the future runtime project without enabling real cleanup.

- [ ] T001 Create package structure under `src/series_cloud_archiver/`
- [ ] T002 Add local configuration loader using `.env.example` placeholders
- [ ] T003 [P] Add structured logging with secret redaction
- [ ] T004 [P] Add test framework and fixture directories
- [ ] T005 Add SQLite persistence scaffolding for state and audit events

---

## Phase 2: Foundational Safety

**Purpose**: Build the pieces that every user story depends on.

- [ ] T006 Implement state machine from `data-model.md`
- [ ] T007 [P] Implement immutable audit event recording
- [ ] T008 [P] Implement evidence freshness and contradiction checks
- [ ] T009 Implement cleanup gate evaluator with all required gates
- [ ] T010 [P] Add unit tests proving missing evidence blocks cleanup
- [ ] T011 [P] Add unit tests proving stale evidence blocks cleanup
- [ ] T012 [P] Add unit tests proving contradictory evidence blocks cleanup

**Checkpoint**: No provider work starts until the cleanup gate fails closed.

---

## Phase 3: User Story 1 - Identify safe archive candidates (Priority: P1)

**Goal**: Detect ended and complete series while blocking ongoing, incomplete,
or ambiguous items.

**Independent Test**: Mock metadata and library evidence for complete,
incomplete, ongoing, and ambiguous series.

### Tests

- [ ] T013 [P] [US1] Add candidate fixture cases in `tests/fixtures/`
- [ ] T014 [P] [US1] Add state-machine tests in `tests/unit/`
- [ ] T015 [P] [US1] Add metadata adapter contract tests in `tests/contract/`

### Implementation

- [ ] T016 [US1] Implement metadata/MoviePilot adapter boundary
- [ ] T017 [US1] Implement expected episode resolver
- [ ] T018 [US1] Implement candidate evaluation workflow
- [ ] T019 [US1] Record blocking reasons for incomplete or ambiguous items

**Checkpoint**: Candidate detection works without MV3 or cleanup.

---

## Phase 4: User Story 2 - Create and verify cloud STRM coverage (Priority: P1)

**Goal**: Verify complete cloud-backed STRM replacement before cleanup is even
considered.

**Independent Test**: Mock MV3 and Emby responses for complete, incomplete, and
unplayable cloud candidates.

### Tests

- [ ] T020 [P] [US2] Add MV3 adapter contract tests
- [ ] T021 [P] [US2] Add Emby adapter contract tests
- [ ] T022 [P] [US2] Add STRM episode mapping tests
- [ ] T023 [P] [US2] Add playback probe failure tests

### Implementation

- [ ] T024 [US2] Implement MV3 search/transfer/STRM adapter boundary
- [ ] T025 [US2] Implement cloud candidate mapping validation
- [ ] T026 [US2] Implement Emby scan and episode verification adapter boundary
- [ ] T027 [US2] Implement playback probe policy
- [ ] T028 [US2] Advance verified items to `emby_verified`

**Checkpoint**: Verified items still cannot be deleted until seed and dry-run
gates pass.

---

## Phase 5: User Story 3 - Clean up local seeding files safely (Priority: P1)

**Goal**: Produce and optionally execute exact cleanup plans after every safety
gate passes.

**Independent Test**: Mock qB seed duration, hlink paths, overlap detection, and
manual approval.

### Tests

- [ ] T029 [P] [US3] Add qBittorrent adapter contract tests
- [ ] T030 [P] [US3] Add filesystem/hlink adapter safety tests
- [ ] T031 [P] [US3] Add dry-run report tests
- [ ] T032 [P] [US3] Add approval freshness tests
- [ ] T033 [P] [US3] Add idempotent cleanup execution tests

### Implementation

- [ ] T034 [US3] Implement qBittorrent task matching and seed-age evidence
- [ ] T035 [US3] Implement exact deletion target builder
- [ ] T036 [US3] Implement hlink ownership and overlap detection
- [ ] T037 [US3] Implement dry-run report generator
- [ ] T038 [US3] Implement manual approval record
- [ ] T039 [US3] Implement cleanup execution behind approval and dry-run gates

**Checkpoint**: Real cleanup remains disabled until dry-run reports are manually
validated in a real deployment.

---

## Phase 6: User Story 4 - Review status and failures (Priority: P2)

**Goal**: Make state, evidence, blockers, and next actions visible.

- [ ] T040 [P] [US4] Add status rendering tests
- [ ] T041 [US4] Implement item status query
- [ ] T042 [US4] Implement failure reason summaries
- [ ] T043 [US4] Implement next-action suggestions

---

## Phase 7: User Story 5 - MoviePilot thin bridge (Priority: P3)

**Goal**: Add optional MoviePilot convenience without moving core decisions into
MoviePilot.

- [ ] T044 [P] [US5] Define bridge event payloads
- [ ] T045 [P] [US5] Add bridge contract tests
- [ ] T046 [US5] Implement event receiver in orchestrator
- [ ] T047 [US5] Document optional MoviePilot plugin scope

---

## Phase 8: Polish and Release Gates

- [ ] T048 [P] Update user documentation in `docs/`
- [ ] T049 [P] Add public redaction scan to CI
- [ ] T050 Run full mocked quickstart validation
- [ ] T051 Run ten-pass review after implementation changes
- [ ] T052 Tag first planning release only after docs and scans pass

