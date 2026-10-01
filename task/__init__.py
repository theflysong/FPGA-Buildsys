"""Command workflows registered by the CLI and scheduled by the planner."""

from . import (aux, bitstream, build, clean, cleandist, completion, implementation,
               install, program, script, simulate, synthesis)


COMMANDS = {module.__name__.rsplit(".", 1)[-1]: module for module in (
    aux, script, build, simulate, synthesis, implementation, bitstream,
    clean, cleandist, program, install, completion,
)}
