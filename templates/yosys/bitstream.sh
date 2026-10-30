$(header)
"$PROJECT_ROOT/"$(implementation_script)
command -v fasm2frames >/dev/null || { printf "Missing tool: fasm2frames\n" >&2; exit 127; }
command -v xc7frames2bit >/dev/null || { printf "Missing tool: xc7frames2bit\n" >&2; exit 127; }
[[ -f "$XRAY_DATABASE/$FPGA_PART/part.yaml" ]] || { printf "Missing FPGA part database: %s\n" "$XRAY_DATABASE/$FPGA_PART/part.yaml" >&2; exit 2; }
mkdir -p -- $(output_directory)
fasm2frames --db-root "$XRAY_DATABASE" --part "$FPGA_PART" $(implementation) $(frames)
xc7frames2bit --part_file "$XRAY_DATABASE/$FPGA_PART/part.yaml" --part_name "$FPGA_PART" --frm_file $(frames) --output_file $(bitstream)
