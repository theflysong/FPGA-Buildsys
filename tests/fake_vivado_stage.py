"""A native fake Vivado process evaluating the production batch script in Tcl.

Used by test_xpr_stages; no FPGA tools, GUI, hardware, or Tcl bridge required.
"""

import json
import os
from pathlib import Path
import sys
import tkinter


tcl = tkinter.Tcl()
state = json.loads(os.environ.get("XPR_FAKE_STATE", "{}"))
calls = Path(os.environ["XPR_CALLS"])
script = Path(sys.argv[sys.argv.index("-source") + 1])
log = Path(sys.argv[sys.argv.index("-log") + 1])
log.write_text(state.get("log", ""), encoding="utf-8")
pending = {}
directory = Path(state.get("directory", Path.cwd() / "export.runs/impl_1"))
runs = {
    name: dict(STATUS="Not started", PROGRESS="0%", NEEDS_REFRESH="0", DIRECTORY=str(directory))
    for name in ("synth_1", "impl_1")
}
for name, properties in state.get("runs", {}).items():
    runs[name].update(properties)
devices = state.get("devices", ["xc7a35t_0", "xc7a100t_1"])


def dispatch(name, *args):
    with calls.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps([name, *args]) + "\n")
    if name == state.get("fail"):
        return ("error", f"injected Tcl failure in {name}")
    try:
        if name == "open_project" and not Path(args[0]).is_file():
            return ("error", "missing XPR")
        if name == "get_runs":
            return ("ok", "" if state.get("missing_run") == args[-1] else args[-1])
        if name == "get_filesets":
            return ("ok", "" if state.get("missing_fileset") == args[-1] else args[-1])
        if name == "list_property":
            return ("ok", tuple(runs[args[0]]))
        if name == "get_property":
            prop, obj = args
            if obj in runs:
                return ("ok", runs[obj][prop])
            if prop == "NAME":
                return ("ok", obj)
            if prop == "TOP":
                return ("ok", "top")
            return ("error", f"unknown property {prop} on {obj}")
        if name == "reset_run":
            runs[args[0]].update(STATUS="Not started", PROGRESS="0%", NEEDS_REFRESH="0")
            if args[0] == "synth_1":
                runs["impl_1"].update(STATUS="Not started", PROGRESS="0%", NEEDS_REFRESH="1")
        if name == "launch_runs":
            pending[args[0]] = "write_bitstream" if "-to_step" in args else (
                "synth_design" if args[0] == "synth_1" else "route_design")
        if name == "wait_on_run":
            run = args[0]
            step = pending[run]
            if state.get("fail_run") == run:
                runs[run].update(STATUS=f"{step} ERROR", PROGRESS="42%", NEEDS_REFRESH="0")
            else:
                runs[run].update(STATUS=f"{step} Complete!", PROGRESS="100%", NEEDS_REFRESH="0")
                runs[run].update(state.get("after_wait", {}))
                if step == "write_bitstream" and not state.get("omit_bitstream"):
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "top.bit").write_bytes(b"fake bitstream")
        if name == "get_hw_devices":
            return ("ok", tuple(devices))
        if name == "launch_simulation":
            print("Simulation reached $finish", flush=True)
            if state.get("simulation_fatal"):
                print("Fatal: testbench assertion failed", flush=True)
        return ("ok", "")
    except Exception as exc:
        return ("error", str(exc))


tcl.createcommand("fake_dispatch", dispatch)
for command in (
    "open_project", "close_project", "get_runs", "get_filesets", "list_property",
    "get_property", "set_property", "reset_run", "launch_runs", "wait_on_run",
    "launch_simulation", "close_sim", "open_hw_manager", "connect_hw_server",
    "open_hw_target", "get_hw_devices", "current_hw_device", "program_hw_devices",
    "refresh_hw_device", "close_hw_target", "disconnect_hw_server", "close_hw_manager", "open_hw", "close_hw",
):
    tcl.eval(f"""proc {command} {{args}} {{
        set response [fake_dispatch {command} {{*}}$args]
        if {{[lindex $response 0] eq "error"}} {{ error [lindex $response 1] }}
        return [lindex $response 1]
    }}""")
if state.get("legacy_hw"):
    tcl.eval("rename open_hw_manager {}; rename close_hw_manager {}")
tcl.eval('proc exit {code} {set ::exit_status $code; error BUILDSYS_FAKE_EXIT}')
try:
    tcl.eval(script.read_text(encoding="utf-8"))
except tkinter.TclError as exc:
    if str(exc) != "BUILDSYS_FAKE_EXIT":
        print(f"ERROR: {exc}", flush=True)
        sys.exit(1)
sys.exit(state.get("exit_status", int(tcl.getvar("exit_status"))))
