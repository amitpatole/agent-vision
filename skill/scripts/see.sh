#!/usr/bin/env bash
# Render an artifact, analyze it, and print a concise verdict.
# Usage: see.sh <artifact> [backend]
set -euo pipefail

ARTIFACT="${1:?usage: see.sh <artifact> [backend]}"
BACKEND="${2:-local}"

echo "AgentVision: looking at ${ARTIFACT} (backend=${BACKEND})"
agentvision analyze "${ARTIFACT}" --backend "${BACKEND}" --full-page || {
  code=$?
  echo "Verdict: issues found (exit ${code}). Fix them and re-run."
  exit "${code}"
}
echo "Verdict: looks good."
