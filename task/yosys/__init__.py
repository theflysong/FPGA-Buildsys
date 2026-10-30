"""Yosys, nextpnr, Project X-Ray, and openFPGALoader workflows."""

from . import bitstream, implementation, program, synthesis


COMMANDS = {"yosys-" + module.__name__.rsplit(".", 1)[-1]: module for module in (
    synthesis, implementation, bitstream, program,
)}
