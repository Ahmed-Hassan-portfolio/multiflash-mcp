"""Phase boundary detection (saturation pressure). Requires Multiflash."""
from __future__ import annotations

import pytest


def _bisect_saturation_bar(wrapper, T_K: float) -> float:
    """Bisection on PT flash to bracket the saturation pressure (bar).

    At given T below Tc:
      - P < P_sat -> single GAS phase
      - P > P_sat -> single LIQUID phase
    """
    P_low, P_high = 1e5, 80e5
    for _ in range(40):
        P_mid = 0.5 * (P_low + P_high)
        res = wrapper.pt_flash(temperature=T_K, pressure=P_mid)
        if "GAS" in res.phase_names[0].upper():
            P_low = P_mid   # gas means we're below P_sat; raise the floor
        else:
            P_high = P_mid  # liquid means we're above P_sat; lower the ceiling
        if (P_high - P_low) < 100.0:
            break
    return 0.5 * (P_low + P_high) / 1e5


@pytest.mark.requires_multiflash
@pytest.mark.parametrize(
    "T_C, P_sat_expected_bar, tol_bar",
    [
        (0, 34.85, 2.5),
        (10, 45.02, 2.5),
        (20, 57.29, 2.5),
    ],
)
def test_co2_saturation_pressure(wrapper, T_C, P_sat_expected_bar, tol_bar):
    """Compare detected saturation pressure against published reference values.

    Reference: standard CO2 P-T tables (e.g., Span-Wagner EOS).
    Tolerance is loose to accommodate the simple bisection approach and PR78 EOS.
    """
    P_sat = _bisect_saturation_bar(wrapper, T_C + 273.15)
    assert abs(P_sat - P_sat_expected_bar) < tol_bar, (
        f"P_sat at {T_C} C: got {P_sat:.2f} bar, expected ~{P_sat_expected_bar} +/- {tol_bar} bar"
    )
