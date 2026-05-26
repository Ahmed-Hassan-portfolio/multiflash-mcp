"""
Example 01: PT flash on pure CO2.

Loads Pure_CO2.mfl and runs a flash at 50 bar / 4 C.
Expected result: single liquid phase (we're below the CO2 saturation line at 4 C).

This is the same operation the MCP server exposes as the `pt_flash` tool.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly without `pip install -e .`
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.multiflash_wrapper import MultiflashWrapper


def main() -> int:
    mfl_path = Path(__file__).parent / "data" / "Pure_CO2.mfl"

    try:
        wrapper = MultiflashWrapper()
        wrapper.load_mfl(str(mfl_path))
    except (FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Set MULTIFLASH_DLL_PATH if your install is non-standard.", file=sys.stderr)
        return 1

    T_K = 4 + 273.15
    P_Pa = 50 * 1e5

    result = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)

    print(f"Fluid:       {wrapper.fluid_name}")
    print(f"Conditions:  P = 50 bar, T = 4 C")
    print(f"Num phases:  {result.num_phases}")
    for name, moles in zip(result.phase_names, result.moles_per_phase):
        print(f"  - {name}: {moles:.4f} mol")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
