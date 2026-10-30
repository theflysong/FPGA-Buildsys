[[ -d /dev/shm && "$(stat -f -c %T /dev/shm 2>/dev/null)" == tmpfs ]] || { printf "A tmpfs mount at /dev/shm is required for build logs.\n" >&2; exit 2; }
