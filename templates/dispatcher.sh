#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"
usage() {
  printf '%s\n' 'Usage: jobs.sh <build|simulate|xpr-simulation> <simulation-id>' '       jobs.sh [yosys-|xpr-]<synthesis|implementation|bitstream|program> <project-id> [options]' '       jobs.sh xpr' '       jobs.sh <clean|cleandist> [id]' 'FPGA stages use the selected toolchain; program options match buildsys program --help.' >&2
  exit 2
}
[[ "$#" -ge 1 ]] || usage
command=$1
shift
case "$command" in
  synthesis|implementation|bitstream|program)
    command=$(python3 $(toolchains) . --resolve "$command")
    ;;
esac
case "$command" in
  xpr)
    [[ "$#" -eq 0 ]] || usage
    exec python3 $(main) --project . xpr
    ;;
  clean|cleandist)
    exec python3 $(main) --project . "$command" "$@"
    ;;
  xpr-simulation|xpr-synthesis|xpr-implementation|xpr-bitstream|xpr-program)
    exec python3 $(main) --project . "$command" "$@"
    ;;
  yosys-synthesis|yosys-implementation|yosys-bitstream|yosys-program) command=${command#yosys-} ;;
esac
case "$command" in
  build|simulate)
    [[ "$#" -eq 1 ]] || usage
    target=$1
    shift
    case "$target" in
$(simulation_cases)
      *) printf "Unknown simulation: %s\n" "$target" >&2; exit 2 ;;
    esac
    ;;
  synthesis|implementation|bitstream|program)
    [[ "$#" -ge 1 ]] || usage
    target=$1
    shift
    [[ "$command" == program || "$#" -eq 0 ]] || usage
    case "$target" in
$(program_cases)
      *) printf "Unknown project: %s\n" "$target" >&2; exit 2 ;;
    esac
    ;;
  *) usage ;;
esac
job_script="$PROJECT_ROOT/build/jobs/$target/$command.sh"
[[ -x "$job_script" ]] || { printf "Missing task script: %s; run buildsys script or the corresponding buildsys target command to regenerate it.\n" "$job_script" >&2; exit 2; }
exec "$job_script" "$@"
