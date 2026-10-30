$(task_header)
$(selection)
FPGA_PART=$(part)
XRAY_DATABASE=$(database)
export FPGA_PART XRAY_DATABASE
FPGA_PYTHONPATHS=($(python_paths))
FPGA_CONFIG=$(config)
[[ -n "$XRAY_DATABASE" ]] || { printf "Fill xray-database in %s, then run buildsys script or the target command to regenerate scripts.\n" "$FPGA_CONFIG" >&2; exit 2; }
(( ${#FPGA_PYTHONPATHS[@]} > 0 )) || { printf "Fill PYTHONPATH in %s with Python module directories, then regenerate scripts.\n" "$FPGA_CONFIG" >&2; exit 2; }
$(toolchain_header)
$(pythonpath_header)
