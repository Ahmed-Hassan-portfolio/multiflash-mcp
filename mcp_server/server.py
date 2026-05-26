"""
Multiflash MCP Server

Exposes the KBC Multiflash thermodynamic engine to LLM clients (Claude, etc.)
through the Model Context Protocol. Provides tools for flash calculations,
PVT properties, phase boundaries, transport properties, and batch operations.

Configuration via environment variables:
    MULTIFLASH_DLL_PATH  Path to mfpvt64.dll (default: standard install location)
    MULTIFLASH_DB_PATH   Path to Multiflash install directory
"""

import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP

VERSION = "0.1.0"

DEFAULT_DLL_PATH = r"C:\program files\KBC\Multiflash 7.5\x64\mfpvt64.dll"
DEFAULT_DB_PATH = r"C:\program files\KBC\Multiflash 7.5"

DLL_PATH = os.environ.get("MULTIFLASH_DLL_PATH", DEFAULT_DLL_PATH)
DATABANK_PATH = os.environ.get("MULTIFLASH_DB_PATH", DEFAULT_DB_PATH)

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("multiflash-mcp")
logger.setLevel(logging.INFO)

console = logging.StreamHandler()
console.setLevel(logging.WARNING)
console.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

file_handler = logging.FileHandler(LOG_DIR / "mcp.log")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

logger.addHandler(console)
logger.addHandler(file_handler)


class MCPError(Exception):
    """Structured error for MCP responses."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


_wrapper = None


def get_wrapper():
    """Lazily initialize and return the Multiflash wrapper, with structured errors."""
    global _wrapper
    if _wrapper is not None:
        return _wrapper

    if not os.path.exists(DLL_PATH):
        raise MCPError(
            "DLL_NOT_FOUND",
            f"Multiflash DLL not found at: {DLL_PATH}\n"
            f"Set MULTIFLASH_DLL_PATH to override the default install location."
        )

    try:
        try:
            from mcp_server.multiflash_wrapper import MultiflashWrapper
        except ImportError:
            from multiflash_wrapper import MultiflashWrapper
        _wrapper = MultiflashWrapper(
            dll_path=DLL_PATH,
            db_path=DATABANK_PATH,
            auto_connect=True
        )
        logger.info("Multiflash DLL connected successfully")
        return _wrapper
    except Exception as e:
        error_msg = str(e)
        if "license" in error_msg.lower():
            logger.warning("Multiflash error: LICENSE_FAILED")
            raise MCPError(
                "LICENSE_FAILED",
                f"Multiflash license check failed: {error_msg}\n"
                f"Please verify your Multiflash license is valid and active."
            )
        logger.warning("Multiflash error: DLL_INIT_FAILED")
        raise MCPError(
            "DLL_INIT_FAILED",
            f"Failed to initialize Multiflash DLL: {error_msg}"
        )


mcp = FastMCP(name="multiflash")

# Register tools. Each module exposes a register_*_tools(mcp, get_wrapper, logger) function.
# The dual import pattern supports both `python -m mcp_server` and direct execution.
_TOOL_REGISTRARS = [
    ("ping", "register_ping_tool"),
    ("fluid_loader", "register_fluid_loader_tools"),
    ("fluid_query", "register_fluid_query_tools"),
    ("flash", "register_flash_tools"),
    ("pvt_properties", "register_pvt_properties_tools"),
    ("multiphase_properties", "register_multiphase_properties_tools"),
    ("transport_properties", "register_transport_properties_tools"),
    ("unit_info", "register_unit_info_tools"),
    ("eos_reference", "register_eos_reference_tools"),
    ("validation", "register_validation_tools"),
    ("phase_boundary", "register_phase_boundary_tools"),
    ("thermodynamic_properties", "register_thermodynamic_tools"),
    ("batch_operations", "register_batch_operations_tools"),
    ("component_database", "register_component_database_tools"),
    ("v2_validation", "register_v2_validation_tools"),
]

for module_name, func_name in _TOOL_REGISTRARS:
    try:
        module = __import__(f"mcp_server.tools.{module_name}", fromlist=[func_name])
    except ImportError:
        module = __import__(f"tools.{module_name}", fromlist=[func_name])
    getattr(module, func_name)(mcp, get_wrapper, logger)


def main():
    """Run the MCP server."""
    logger.info(f"Multiflash MCP server v{VERSION} starting")

    try:
        get_wrapper()
    except MCPError as e:
        logger.warning(f"DLL pre-connection failed: {e.code} (tools will report this on call)")

    mcp.run()


if __name__ == "__main__":
    main()
