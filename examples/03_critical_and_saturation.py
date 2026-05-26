"""
Example 03: Critical point + saturation curve for pure CO2.

Calls AXCRIT to compute the critical point, then walks the saturation
curve from -40 C up toward the critical temperature and prints the
saturation pressure at each step.

Exercises the same operations the MCP server exposes as `get_critical_point`
and `get_saturation_pressure`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.multiflash_wrapper import MultiflashWrapper


def saturation_pressure_bar(wrapper: MultiflashWrapper, T_K: float) -> float | None:
    """Bisect saturation pressure by finding the GAS<->LIQUID transition."""
    P_low_Pa, P_high_Pa = 1e5, 80e5
    for _ in range(40):
        P_mid_Pa = 0.5 * (P_low_Pa + P_high_Pa)
        try:
            res = wrapper.pt_flash(temperature=T_K, pressure=P_mid_Pa)
        except RuntimeError:
            return None
        if "GAS" in res.phase_names[0].upper():
            P_low_Pa = P_mid_Pa
        else:
            P_high_Pa = P_mid_Pa
        if (P_high_Pa - P_low_Pa) < 1e3:
            break
    return 0.5 * (P_low_Pa + P_high_Pa) / 1e5


def main() -> int:
    mfl_path = Path(__file__).parent / "data" / "Pure_CO2.mfl"

    try:
        wrapper = MultiflashWrapper()
        wrapper.load_mfl(str(mfl_path))
    except (FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Critical point
    Tc_K, Pc_Pa, Vc = wrapper.get_critical_point()
    print(f"Critical point for {wrapper.fluid_name}:")
    print(f"  Tc = {Tc_K:.2f} K  ({Tc_K - 273.15:.2f} C)   reference: 304.13 K")
    print(f"  Pc = {Pc_Pa/1e5:.2f} bar                     reference: 73.77 bar")
    print(f"  Vc = {Vc:.4e} m3/mol")
    print()

    # Saturation curve
    print(f"{'T (C)':>8}  {'P_sat (bar)':>12}")
    print("-" * 22)
    for T_C in [-40, -30, -20, -10, 0, 5, 10, 15, 20, 25, 28, 30]:
        T_K = T_C + 273.15
        if T_K >= Tc_K:
            print(f"{T_C:>8}  {'(above Tc)':>12}")
            continue
        P_sat = saturation_pressure_bar(wrapper, T_K)
        if P_sat is None:
            print(f"{T_C:>8}  {'failed':>12}")
        else:
            print(f"{T_C:>8}  {P_sat:>12.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
