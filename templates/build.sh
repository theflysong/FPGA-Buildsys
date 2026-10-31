$(header)
filelist=$(filelist)
vvp_file=$(vvp_file)
vcd_file=$(vcd_file)
if [[ ! -f "$filelist" ]]; then
  printf "Missing %s; run the Python auxiliary command first.\n" "$filelist" >&2
  exit 2
fi
mkdir -p -- "$(dirname -- "$vvp_file")" "$(dirname -- "$vcd_file")"
iverilog -g2012 -Wall -s $(top) -f "$filelist" "-D__VCD_FILE__=\"$vcd_file\"" -o "$vvp_file"
$(report)
