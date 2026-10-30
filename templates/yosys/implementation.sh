$(header)
"$PROJECT_ROOT/"$(synthesis_script)
command -v nextpnr-himbaechel >/dev/null || { printf "Missing tool: nextpnr-himbaechel\n" >&2; exit 127; }
mkdir -p -- $(output_directory)
$(tmpfs_check)
log_dir=$(mktemp -d -- $(log_directory))
impl_log="$log_dir/$(program_id).implementation.log"
printf "Implementation log: %s\n" "$impl_log" >&2
nextpnr-himbaechel --device "$FPGA_PART" --json $(synthesis) -o $(constraints_option) -o $(implementation_option) --log "$impl_log"
