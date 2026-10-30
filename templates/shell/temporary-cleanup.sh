trap 'rm -f -- "$0"' EXIT
[[ "$(stat -f -c %T /dev/shm)" == tmpfs ]] || { printf "Logs and temporary scripts require tmpfs at /dev/shm.\n" >&2; exit 2; }
