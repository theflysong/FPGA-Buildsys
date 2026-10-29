#!/usr/bin/env bash
# Compatibility entry point; candidate selection is shared with PowerShell.
set -euo pipefail
project_dir=$1
shift
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$script_dir/main.py" --project "$project_dir" completion "$@"
