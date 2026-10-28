"""Vivado project export and existing-project workflows."""

from . import xpr, xpr_bitstream, xpr_implementation, xpr_program, xpr_simulation, xpr_synthesis


COMMANDS = {module.__name__.rsplit(".", 1)[-1].replace("_", "-"): module for module in (
    xpr, xpr_simulation, xpr_synthesis, xpr_implementation, xpr_bitstream, xpr_program,
)}
