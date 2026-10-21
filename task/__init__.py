"""Command workflows registered by the CLI and scheduled by the planner."""

from . import (auxiliary, bitstream, build, clean, cleandist, completion, implementation, init,
               install, program, script, simulate, synthesis, xpr)


COMMANDS = {module.__name__.rsplit(".", 1)[-1]: module for module in (
    auxiliary, script, build, simulate, synthesis, implementation, bitstream,
    clean, cleandist, program, xpr, init, install, completion,
)}
