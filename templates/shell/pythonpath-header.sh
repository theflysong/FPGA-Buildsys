fpga_pythonpath=""
for python_path in "${FPGA_PYTHONPATHS[@]}"; do
  [[ -d "$python_path" ]] || { printf "Missing PYTHONPATH directory: %s\n" "$python_path" >&2; exit 2; }
  fpga_pythonpath+="$python_path:"
done
export PYTHONPATH="${fpga_pythonpath%:}${PYTHONPATH:+:$PYTHONPATH}"
