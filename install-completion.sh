#!/usr/bin/env bash
# Copy the completion adapters; Bash loads them by command name.
set -euo pipefail

destination=$1
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -d $destination ]]; then
    printf 'error: %s: install directory does not exist\n' "$destination" >&2
    exit 1
fi
for command in buildsys buildsys.sh; do
    install -m 0644 -- "$script_dir/bash-completion/buildsys.bash" "$destination/$command"
done
printf 'installed %s and %s\n' "$destination/buildsys" "$destination/buildsys.sh"
