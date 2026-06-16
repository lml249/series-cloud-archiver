#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Public safety scans =="

if grep -RInE '[0-9]{1,3}(\.[0-9]{1,3}){3}' . \
  --exclude-dir=.git \
  --exclude-dir=.agents; then
  echo "IP address-like value found. Use .local placeholders instead." >&2
  exit 1
fi

if grep -RInEi '["'\'']?(token|cookie|password|passwd|api[_-]?key|secret|pickcode|authorization)["'\'']?\s*[:=]' . \
  --exclude-dir=.git \
  --exclude-dir=.agents \
  --exclude-dir=src \
  --exclude-dir=tests \
  --exclude=.env.example \
  --exclude=public-safety.yml; then
  echo "Potential secret assignment found. Keep real secrets out of repo." >&2
  exit 1
fi

if grep -RInE '/volume[0-9]+/|/Users/[A-Za-z0-9._-]+|/mnt/[A-Za-z0-9._-]+|/downloads/[A-Za-z0-9._-]+' . \
  --exclude-dir=.git \
  --exclude-dir=.agents; then
  echo "Real-looking local path found. Use placeholders instead." >&2
  exit 1
fi

if grep -RInE '\[NEEDS CLARIFICATION\]|ACTION REQUIRED|REMOVE IF UNUSED|TODO\(' \
  README.md AGENTS.md docs specs .specify/memory \
  --exclude-dir=.git \
  --exclude-dir=.agents \
  --exclude='requirements.md'; then
  echo "Template marker or unresolved clarification found." >&2
  exit 1
fi

echo "== Ten-pass content checks =="

python3 - <<'PY'
from pathlib import Path

root = Path.cwd()
paths = [
    root / "README.md",
    root / ".specify/memory/constitution.md",
    root / "docs/architecture.md",
    root / "docs/security.md",
    root / "docs/ten-pass-review.md",
    root / "specs/001-series-cloud-archiver/spec.md",
    root / "specs/001-series-cloud-archiver/plan.md",
    root / "specs/001-series-cloud-archiver/research.md",
    root / "specs/001-series-cloud-archiver/data-model.md",
    root / "specs/001-series-cloud-archiver/contracts/adapter-contracts.md",
    root / "specs/001-series-cloud-archiver/quickstart.md",
    root / "specs/001-series-cloud-archiver/tasks.md",
]

text = "\n".join(path.read_text() for path in paths)
checks = [
    ("1 public hygiene", [".env.example", ".gitignore", "Public-Safe by Default", "public-safety"]),
    ("2 orchestrator architecture", ["independent orchestrator", "MoviePilot plugin", "thin bridge"]),
    ("3 completion detection", ["metadata says", "series ended", "expected episode", "complete"]),
    ("4 cloud strm validation", ["MV3", "STRM", "Emby", "playback probe"]),
    ("5 cleanup gates", ["dry-run", "manual approval", "seeded for at least", "7 days", "deletion targets"]),
    ("6 idempotency recovery", ["idempotent", "resume", "failed_*", "AuditEvent"]),
    ("7 adapter boundaries", ["adapter", "MoviePilot", "MV3", "qBittorrent", "filesystem"]),
    ("8 hlink/qb scope", ["hlink", "qBittorrent", "exact matched task", "Broad directory deletion is forbidden"]),
    ("9 observability", ["audit", "evidence", "status", "blocking reason"]),
    ("10 testability", ["contract tests", "unit tests", "integration tests", "dry-run acceptance"]),
]

for name, terms in checks:
    missing = [term for term in terms if term not in text]
    if missing:
        raise SystemExit(f"FAIL {name}: missing {missing}")
    print(f"PASS {name}")
PY

echo "All validation checks passed."

if [[ -d src && -d tests ]]; then
  echo "== Runtime tests =="
  PYTHONPATH=src python3 -m unittest discover -s tests -v
fi
