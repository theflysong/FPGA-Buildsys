# Appended to the generated program header, which defines PROGRAM_ID and BITSTREAM.
usage() {
  printf '%s\n' 'Usage: program.sh --protocol <cable> [--busdev-num <bus:device> | --ftdi-serial <serial>]' >&2
  exit 2
}
protocol=''
busdev=''
serial=''
while [[ "$#" -gt 0 ]]; do
  [[ "$#" -ge 2 && -n "$2" ]] || usage
  case "$1" in
    --protocol) [[ -z "$protocol" ]] || usage; protocol=$2 ;;
    --busdev-num) [[ -z "$busdev" && -z "$serial" ]] || usage; busdev=$2 ;;
    --ftdi-serial) [[ -z "$serial" && -z "$busdev" ]] || usage; serial=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n "$protocol" && "$protocol" =~ ^[A-Za-z0-9_-]+$ ]] || usage
if [[ -n "$busdev" ]]; then
  [[ "$busdev" =~ ^[0-9]{1,3}:[0-9]{1,3}$ ]] || usage
  bus=${busdev%:*}
  device=${busdev#*:}
  busdev="$((10#$bus)):$((10#$device))"
fi
command -v openFPGALoader >/dev/null || { printf 'Missing tool: openFPGALoader\n' >&2; exit 127; }
[[ -d /dev/shm && "$(stat -f -c %T /dev/shm 2>/dev/null)" == tmpfs ]] || {
  printf 'A tmpfs mount at /dev/shm is required for programming logs.\n' >&2
  exit 2
}
log_dir=$(mktemp -d -- "/dev/shm/buildsys-$PROGRAM_ID-program-XXXXXX")
program_log="$log_dir/$PROGRAM_ID.program.log"
printf 'Programming log: %s\n' "$program_log" >&2

if ! scan=$(openFPGALoader --scan-usb 2>&1); then
  printf '%s\n' "$scan" | tee -a "$program_log" >&2
  exit 1
fi
printf '%s\n' "$scan" | tee -a "$program_log"
if ! cables=$(openFPGALoader --list-cables 2>&1); then
  printf '%s\n' "$cables" | tee -a "$program_log" >&2
  exit 1
fi
printf '%s\n' "$cables" >> "$program_log"
vidpid=$(printf '%s\n' "$cables" | awk -v cable="$protocol" '
  { gsub(/\033\[[0-9;]*[mK]/, "") }
  $1 == cable { value = tolower($2); gsub(/0x/, "", value); print value; exit }
')
[[ "$vidpid" =~ ^[[:xdigit:]]{4}:[[:xdigit:]]{4}$ && "$vidpid" != 0000:0000 ]] || {
  printf 'Unknown or unsupported USB protocol: %s; see openFPGALoader --list-cables.\n' "$protocol" >&2
  exit 2
}
# openFPGALoader 0.12 prints a fixed-width table. The header supplies the serial
# column positions, so manufacturer/product spaces do not split the serial.
# Match the selected cable's VID/PID and deduplicate aliases of one USB device.
if ! candidates=$(printf '%s\n' "$scan" | awk -v id="$vidpid" '
  { gsub(/\033\[[0-9;]*[mK]/, "") }
  tolower($1) == "bus" && tolower($2) == "device" {
    header = tolower($0); serial_start = index(header, "serial");
    product_start = index(header, "product"); found_header = 1; next
  }
  found_header && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {
    value = tolower($3); gsub(/0x/, "", value)
    if (value != id) next
    address = sprintf("%d:%d", $1, $2)
    if (seen[address]++) next
    serial = ""
    if (serial_start > 0 && product_start > serial_start)
      serial = substr($0, serial_start, product_start - serial_start)
    sub(/^[[:space:]]+/, "", serial); sub(/[[:space:]]+$/, "", serial)
    printf "%s\t%s\n", address, serial
  }
  END { if (!found_header) exit 2 }
'); then
  printf 'Cannot parse openFPGALoader USB scan table; see %s.\n' "$program_log" >&2
  exit 2
fi
[[ -n "$candidates" ]] || {
  printf 'No USB device matches protocol %s (%s).\n' "$protocol" "$vidpid" >&2
  exit 2
}

matches=()
while IFS=$'\t' read -r address device_serial; do
  [[ -z "$busdev" || "$address" == "$busdev" ]] || continue
  [[ -z "$serial" || "$device_serial" == "$serial" ]] || continue
  matches+=("$address")
done <<< "$candidates"
if [[ "${#matches[@]}" -ne 1 ]]; then
  if [[ "${#matches[@]}" -eq 0 ]]; then
    printf 'The device selector matches no device for protocol %s.\n' "$protocol" >&2
  else
    printf 'Protocol %s matches multiple devices; specify --busdev-num or --ftdi-serial.\n' "$protocol" >&2
  fi
  printf 'Matching USB devices (bus:device, serial):\n%s\n' "$candidates" >&2
  while IFS=$'\t' read -r address device_serial; do
    printf '  ./buildsys program %q --protocol %q --busdev-num %q\n' "$PROGRAM_ID" "$protocol" "$address" >&2
  done <<< "$candidates"
  exit 2
fi
[[ -s "$BITSTREAM" ]] || {
  printf 'Missing or empty bitstream: %s; run buildsys bitstream %s first.\n' "$BITSTREAM" "$PROGRAM_ID" >&2
  exit 2
}
# Pin the selected physical adapter in both commands, even when it was the
# sole candidate, so detect and SRAM programming use the same USB address.
loader_args=(-c "$protocol" --busdev-num "${matches[0]}")
[[ -z "$serial" ]] || loader_args+=(--ftdi-serial "$serial")
openFPGALoader "${loader_args[@]}" --detect 2>&1 | tee -a "$program_log"
openFPGALoader "${loader_args[@]}" -m "$BITSTREAM" 2>&1 | tee -a "$program_log"
