# Data Model

## SeriesItem

Represents one tracked series or season group.

Fields:

- `id`: Stable internal identifier.
- `external_ids`: Metadata identifiers such as TMDB, TVDB, IMDb, or provider
  IDs when available.
- `title`: Display title.
- `year`: Release year when known.
- `status`: Current state-machine state.
- `expected_episode_count`: Count from the latest trusted expectation set.
- `created_at`, `updated_at`: Audit timestamps.

Validation rules:

- A `SeriesItem` cannot enter cleanup-related states without a resolved identity.
- Title-only identity is not enough for cleanup.

## EpisodeExpectation

Represents the expected episodes for a series.

Fields:

- `series_item_id`
- `season_number`
- `episode_number`
- `episode_title`
- `air_date`
- `is_special`
- `source`
- `confidence`

Validation rules:

- Regular episodes must be complete before archive candidacy.
- Specials must follow an explicit policy before they can affect cleanup.
- Ambiguous numbering blocks cleanup.

## CloudCandidate

Represents a cloud-backed candidate found or transferred through MV3.

Fields:

- `series_item_id`
- `provider`
- `display_name`
- `episode_mapping`
- `transfer_status`
- `strm_status`
- `last_checked_at`

Validation rules:

- The candidate must map to every required regular episode.
- Same title is insufficient without identity and episode mapping evidence.

## StrmSet

Represents STRM files generated for the cloud candidate.

Fields:

- `series_item_id`
- `root_placeholder`
- `episode_paths`
- `generated_at`
- `generator`

Validation rules:

- Public logs must not store real STRM redirect URLs.
- Every expected episode must have one mapped STRM file before Emby
  verification can pass.

## VerificationEvidence

Represents proof used by a gate.

Fields:

- `series_item_id`
- `gate`
- `source`
- `source_record_id`
- `observed_at`
- `result`
- `summary`
- `raw_reference`

Validation rules:

- Evidence has an expiration policy per source.
- Failed, stale, or contradictory evidence blocks cleanup.
- Raw references must be local/private and ignored by git.

## CleanupPlan

Represents a dry-run and optional approved cleanup action.

Fields:

- `series_item_id`
- `seed_days`
- `deletion_targets`
- `hlink_targets`
- `torrent_task_id`
- `dry_run_created_at`
- `approval_status`
- `approved_at`
- `executed_at`
- `execution_result`

Validation rules:

- Deletion targets must be exact, not broad globs.
- Targets must not overlap unrelated series.
- Approval is required before execution in the first milestone.

## AuditEvent

Append-only record of decisions and actions.

Fields:

- `id`
- `series_item_id`
- `event_type`
- `from_state`
- `to_state`
- `actor`
- `message`
- `evidence_ids`
- `created_at`

Validation rules:

- State transitions must create audit events.
- Cleanup attempts must record the exact target set and result.

## State Transitions

```text
candidate
  -> mv3_transfer_started
  -> strm_generated
  -> emby_verified
  -> cleanup_waiting
  -> cleaned
```

Failure transitions:

- `failed_metadata`
- `failed_mv3_search`
- `failed_mv3_transfer`
- `failed_strm_generation`
- `failed_emby_verification`
- `failed_playback_probe`
- `failed_seed_age`
- `failed_cleanup_scope`
- `failed_cleanup_execution`

Recovery rule:

An item may recover from a `failed_*` state only by collecting new evidence for
the failed gate and re-entering the last safe non-destructive state.

