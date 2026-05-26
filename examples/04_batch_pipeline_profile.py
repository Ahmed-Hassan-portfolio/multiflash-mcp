"""
Example 04: Pipeline operating-envelope check via batch flash.

For a CCS-style impure CO2 pipeline, walks a series of (P, T) points along
the pipeline and confirms that each point is single-phase (dense liquid).
Reports the bulk density and viscosity at each point so an engineer can see
how those properties shift along the line.

Same operation as the MCP server's `batch_flash` tool.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.multiflash_wrapper import MultiflashWrapper


PROFILE = [
    # (label, pressure_bar, temperature_C)
    ("Inlet (compressor)",   150, 40),
    ("After cooling",        145, 20),
    ("Midpoint",             120, 15),
    ("Approach to terminal",  90, 10),
    ("Terminal (injection)",  70,  8),
]


def main() -> int:
    mfl_path = Path(__file__).parent / "data" / "Impure_CO2_Pipeline.mfl"

    try:
        wrapper = MultiflashWrapper()
        wrapper.load_mfl(str(mfl_path))
    except (FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Fluid: {wrapper.fluid_name} ({len(wrapper.composition)} components)\n")
    print(f"{'Point':<25}  {'P (bar)':>8}  {'T (C)':>6}  {'#phases':>8}  "
          f"{'rho (kg/m3)':>12}  {'mu (cP)':>9}")
    print("-" * 82)

    any_multiphase = False
    for label, P_bar, T_C in PROFILE:
        T_K = T_C + 273.15
        P_Pa = P_bar * 1e5
        res = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)

        if res.num_phases > 1:
            any_multiphase = True
            print(f"{label:<25}  {P_bar:>8}  {T_C:>6}  {res.num_phases:>8}  "
                  f"{'TWO-PHASE!':>12}  {'-':>9}")
            continue

        phase_lno = res.phases[0]
        comp = res.compositions[0]
        aymix = wrapper.get_aymix_properties(
            phase_lno=phase_lno, temperature=T_K, pressure=P_Pa,
            composition=comp, get_volume_derivs=False,
        )
        mw = wrapper.get_molecular_weight(composition=comp)
        rho = mw / aymix.volume

        try:
            mu = wrapper.get_viscosity(
                phase_lno=phase_lno, temperature=T_K, pressure=P_Pa,
                composition=comp,
            ).value * 1000  # Pa.s -> cP
            mu_str = f"{mu:>9.3f}"
        except RuntimeError:
            mu_str = f"{'n/a':>9}"

        print(f"{label:<25}  {P_bar:>8}  {T_C:>6}  {res.num_phases:>8}  "
              f"{rho:>12.2f}  {mu_str}")

    print()
    if any_multiphase:
        print("WARNING: at least one point on the profile is two-phase.")
        return 2
    print("All points single-phase: profile is safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
