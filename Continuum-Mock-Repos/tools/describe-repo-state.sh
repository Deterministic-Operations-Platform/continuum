#!/usr/bin/env bash
set -euo pipefail
repo=${1:-}
if [[ -z "$repo" ]]; then echo "usage: $0 <repo-name>"; exit 1; fi
cat "$(dirname "$0")/../repo-states/${repo}.state"
