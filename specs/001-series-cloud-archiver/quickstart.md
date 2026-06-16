# Validation Quickstart

This repository currently contains the plan and safety specification only. The
steps below define how the future implementation must be validated before real
cleanup is enabled.

## 1. Prepare local-only configuration

Create a local `.env` from `.env.example` and replace placeholders on your own
machine. Never commit the resulting `.env`.

```bash
cp .env.example .env
```

Keep these safety defaults for early validation:

```text
ARCHIVER_MODE=dry-run
REQUIRE_MANUAL_APPROVAL_FOR_CLEANUP=true
MIN_SEED_DAYS=7
```

## 2. Run mocked provider validation

Future implementation must include a fixture suite with:

- one ended complete series
- one ended incomplete series
- one ongoing complete-to-date series
- one ambiguous title/year match
- one STRM set with missing episodes
- one qB task below seed-age threshold
- one hlink overlap case

Expected result:

- Only the ended complete series with verified STRM, playback probe, seed age,
  exact deletion scope, dry-run, and approval can reach cleanup.
- All other fixtures remain blocked with clear reasons.

## 3. Review dry-run output

Before real deletion exists, the implementation must produce a dry-run report
with:

- series identity
- expected episodes
- cloud candidate summary
- STRM coverage
- Emby verification result
- playback probe result
- qB seed duration
- exact deletion targets
- exact hlink targets
- blockers, if any

Expected result:

- The report lists targets but deletes nothing.
- The report is understandable without reading logs.

## 4. Test interruption recovery

Simulate interruption at these states:

- `mv3_transfer_started`
- `strm_generated`
- `emby_verified`
- `cleanup_waiting`

Expected result:

- Re-running evaluation resumes safely.
- No duplicate destructive action occurs.
- Failed gates produce explicit `failed_*` states.

## 5. Public safety scan

Before pushing public changes:

```bash
rg -n "[0-9]{1,3}(\\.[0-9]{1,3}){3}" .
rg -n -i "(token|cookie|password|passwd|api[_-]?key|secret)\\s*[:=]" .
rg -n "/volume[0-9]+|/mnt/|/downloads/|/media/" .
```

Only placeholder examples are allowed.
