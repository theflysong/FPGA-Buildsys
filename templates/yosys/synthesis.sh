$(header)
yosys_script=$(yosys_script)
[[ -f "$yosys_script" ]] || { printf "Missing %s; run the Python auxiliary command first.\n" "$yosys_script" >&2; exit 2; }
command -v yosys >/dev/null || { printf "Missing tool: yosys\n" >&2; exit 127; }
mkdir -p -- $(output_directory)
$(tmpfs_check)
log_dir=$(mktemp -d -- $(log_directory))
synth_log="$log_dir/$(program_id).synthesis.log"
printf "Synthesis log: %s\n" "$synth_log" >&2
json_compactor=$(json_compactor)
if ! yosys -Q -q -l "$synth_log" -s "$yosys_script" | python3 "$json_compactor" $(synthesis); then
  rm -f -- $(synthesis)
  exit 1
fi
$(report)
