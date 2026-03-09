#!/usr/bin/env bash
set -euo pipefail

workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while IFS= read -r repo; do
  [[ -z "$repo" ]] && continue
  repo_dir="$workspace_dir/$repo"
  if [[ ! -d "$repo_dir" ]]; then
    echo "skip (missing): $repo"
    continue
  fi
  if [[ -d "$repo_dir/.git" ]]; then
    echo "already git-initialized: $repo"
    continue
  fi
  (
    cd "$repo_dir"
    git init -q
    git add .
    git commit -q -m "Initialize $repo mock repository"
  )
  echo "initialized: $repo"
done < "$workspace_dir/repos.txt"
