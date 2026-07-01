#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Public safety scans =="

scan_files() {
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files ':!.agents'
  else
    find . \
      -path './.git' -prune -o \
      -path './.agents' -prune -o \
      -path './data' -prune -o \
      -path './logs' -prune -o \
      -path './reports' -prune -o \
      -path './outputs' -prune -o \
      -path './artifacts' -prune -o \
      -path './backups' -prune -o \
      -path './.pytest_cache' -prune -o \
      -path './.ruff_cache' -prune -o \
      -path './.mypy_cache' -prune -o \
      -path './.venv' -prune -o \
      -path './venv' -prune -o \
      -path './node_modules' -prune -o \
      -name '__pycache__' -prune -o \
      -name '._*' -prune -o \
      -name '.env' -prune -o \
      -name '.env.*' -prune -o \
      -type f -print | sed 's#^\./##'
  fi
}

tracked_private_files() {
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files | grep -E '(^|/)\.env(\..*)?$|(^|/)cookies\.txt$|(^|/)manual-(completions|exclusions).*\.json$|^(data|logs|outputs|reports|artifacts|backups|secrets)/|.*\.(sqlite|sqlite3|db|log)$' \
      | grep -Ev '^\.env\.example$|^examples/manual-completions\.example\.json$|^examples/manual-exclusions\.example\.json$' || true
  fi
}

tracked_private="$(tracked_private_files)"
if [[ -n "$tracked_private" ]]; then
  echo "$tracked_private"
  echo "Private runtime files are tracked by git. Remove them from the public repository before pushing." >&2
  exit 1
fi

if scan_files | xargs grep -InE '[0-9]{1,3}(\.[0-9]{1,3}){3}'; then
  echo "IP address-like value found. Use .local placeholders instead." >&2
  exit 1
fi

if scan_files | grep -Ev '^(src|tests)/|^\.env\.example$|^\.github/workflows/public-safety\.yml$|^scripts/validate-plan\.sh$' \
  | xargs grep -InEi '["'\'']?(token|cookie|password|passwd|api[_-]?key|secret|pickcode|authorization)["'\'']?\s*[:=]'; then
  echo "Potential secret assignment found. Keep real secrets out of repo." >&2
  exit 1
fi

python3 - <<'PY'
import ast
import re
from pathlib import Path

root = Path.cwd()
secret_value = re.compile(
    r"(?i)(gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"Bearer\s+[A-Za-z0-9._=-]{20,}|"
    r"(token|cookie|password|passwd|api[_-]?key|secret|pickcode|authorization)\s*[:=]\s*['\"]?(?!replace-with|local-|example|placeholder)[^'\"\s]{8,})"
)
private_ip = re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.\d{1,3}\.\d{1,3}\b")
real_path = re.compile(r"(/volume\d+/|/Users/[A-Za-z0-9._-]+|/mnt/[A-Za-z0-9._-]+|/downloads/[A-Za-z0-9._-]+)")

allowed_files = {
    ".env.example",
    "docs/security.md",
    "docs/ten-pass-review.md",
    "scripts/validate-plan.sh",
}

findings = []
for path in list(root.glob("src/**/*.py")) + list(root.glob("tests/**/*.py")):
    if path.name.startswith("._"):
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if secret_value.search(value) or private_ip.search(value) or real_path.search(value):
                rel = path.relative_to(root)
                if str(rel) not in allowed_files:
                    findings.append(f"{rel}:{getattr(node, 'lineno', '?')}: suspicious literal")

if findings:
    print("\n".join(findings))
    raise SystemExit("Suspicious source literal found.")
PY

if scan_files | grep -Ev '^scripts/validate-plan\.sh$' \
  | xargs grep -InE '/volume[0-9]+/|/Users/[A-Za-z0-9._-]+|/mnt/[A-Za-z0-9._-]+|/downloads/[A-Za-z0-9._-]+'; then
  echo "Real-looking local path found. Use placeholders instead." >&2
  exit 1
fi

if find README.md AGENTS.md docs specs .specify/memory \
  -path 'specs/*/requirements.md' -prune -o \
  -type f -print \
  | xargs grep -InE '\[NEEDS CLARIFICATION\]|ACTION REQUIRED|REMOVE IF UNUSED|TODO\('; then
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
