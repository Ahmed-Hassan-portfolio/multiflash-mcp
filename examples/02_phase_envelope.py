"""
Example 02: Pure CO2 phase envelope.

Traces saturation pressure across a range of temperatures to build the
two-phase envelope, then plots it if matplotlib is available. Otherwise
prints a table.

This is a simplified version of what the MCP server's `get_phase_envelope`
tool returns.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.multiflash_wrapper import MultiflashWrapper


def saturation_pressure_at(wrapper: MultiflashWrapper, T_K: float) -> float | None:
    """Bracket-search the saturation pressure by detecting the phase transition.

    Crude but illustrative: we bisect on pressure looking for the boundary
    between single-phase and two-phase. A real implementation would use
    the AXBUBP/AXDEWP family of Multiflash routines.
    """
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
    return 0.5 * (P_low_Pa + P_high_Pa) / 1e5  # bar


def main() -> int:
    mfl_path = Path(__file__).parent / "data" / "Pure_CO2.mfl"

    try:
        wrapper = MultiflashWrapper()
        wrapper.load_mfl(str(mfl_path))
    except (FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    temperatures_C = [-40, -30, -20, -10, 0, 5, 10, 15, 20, 25, 30]
    rows = []
    for T_C in temperatures_C:
        P_sat_bar = saturation_pressure_at(wrapper, T_C + 273.15)
        rows.append((T_C, P_sat_bar))

    print(f"{'T (C)':>8}  {'P_sat (bar)':>12}")
    print("-" * 22)
    for T_C, P_sat in rows:
        if P_sat is None:
            print(f"{T_C:>8}  {'n/a':>12}")
        else:
            print(f"{T_C:>8}  {P_sat:>12.2f}")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(install matplotlib to see the plot)")
        return 0

    xs = [r[0] for r in rows if r[1] is not None]
    ys = [r[1] for r in rows if r[1] is not None]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(xs, ys, "o-")
    ax.set_xlabel("Temperature (C)")
    ax.set_ylabel("Saturation pressure (bar)")
    ax.set_title("Pure CO2 phase envelope")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out = Path(__file__).parent / "phase_envelope.png"
    fig.savefig(out, dpi=120)
    print(f"\nPlot saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
