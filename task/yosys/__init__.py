"""Yosys, nextpnr, Project X-Ray, and openFPGALoader workflows."""

from . import bitstream, implementation, program, synthesis


COMMANDS = {module.__name__.rsplit(".", 1)[-1]: module for module in (
    synthesis, implementation, bitstream, program,
)}
