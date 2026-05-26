"""Phase envelope sampling. Requires Multiflash."""
from __future__ import annotations

import pytest


@pytest.mark.requires_multiflash
def test_envelope_pressure_increases_monotonically_with_temperature(wrapper):
    """For pure CO2 below Tc, P_sat must increase monotonically with T."""
    temps_K = [243.15, 253.15, 263.15, 273.15, 283.15, 293.15]  # -30 C to 20 C
    saturation_pressures = []
    for T in temps_K:
        P_low, P_high = 1e5, 80e5
        for _ in range(35):
            P_mid = 0.5 * (P_low + P_high)
            res = wrapper.pt_flash(temperature=T, pressure=P_mid)
            if "GAS" in res.phase_names[0].upper():
                P_low = P_mid
            else:
                P_high = P_mid
            if (P_high - P_low) < 1e3:
                break
        saturation_pressures.append(0.5 * (P_low + P_high))

    for i in range(1, len(saturation_pressures)):
        assert saturation_pressures[i] > saturation_pressures[i - 1], (
            f"P_sat not monotonic: T={temps_K[i]} K gave {saturation_pressures[i]:.0f} Pa "
            f"<= prior {saturation_pressures[i-1]:.0f} Pa"
        )


@pytest.mark.requires_multiflash
def test_envelope_terminates_below_critical_pressure(wrapper):
    """Saturation pressure at 30 C (just below Tc) should still be below Pc."""
    P_low, P_high = 1e5, 80e5
    for _ in range(35):
        P_mid = 0.5 * (P_low + P_high)
        res = wrapper.pt_flash(temperature=303.15, pressure=P_mid)
        if "GAS" in res.phase_names[0].upper():
            P_low = P_mid
        else:
            P_high = P_mid
        if (P_high - P_low) < 1e3:
            break
    P_sat_bar = 0.5 * (P_low + P_high) / 1e5
    assert P_sat_bar < 73.77, f"P_sat at 30 C is {P_sat_bar:.2f} bar, exceeds Pc"
    assert P_sat_bar > 65.0, f"P_sat at 30 C is {P_sat_bar:.2f} bar, unrealistically low"
