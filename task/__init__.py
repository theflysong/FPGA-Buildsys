"""Command workflows registered by the CLI and scheduled by the planner."""

from . import (auxiliary, build, clean, cleandist, completion, init, init_venv,
               install, model, script, simulate, toolchain, vivado, yosys)


COMMANDS = {module.__name__.rsplit(".", 1)[-1]: module for module in (
    model, auxiliary, script, build, simulate, clean, cleandist,
    init, install, completion, toolchain,
)}
COMMANDS["init-venv"] = init_venv
COMMANDS.update(yosys.COMMANDS)
COMMANDS.update(vivado.COMMANDS)
