"""PH flash tests. Requires Multiflash.

PH flash takes a target pressure and a molar enthalpy and returns the
equilibrium state. The enthalpy reference frame depends on the MFL file's
datum settings; here we just confirm the tool returns a sane state at lower
pressure rather than asserting a specific temperature, because the AYMIX
enthalpy and PHFlash enthalpy do not always share a reference in every MFL
configuration.
"""
from __future__ import annotations

import pytest


@pytest.mark.requires_multiflash
def test_ph_flash_at_lower_pressure_returns_valid_state(wrapper):
    """Read inlet enthalpy from AYMIX, then PH flash at lower P; result must be sane."""
    T_K, P_Pa = 313.15, 100e5
    inlet = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)
    aymix = wrapper.get_aymix_properties(
        phase_lno=inlet.phases[0],
        temperature=T_K,
        pressure=P_Pa,
        composition=inlet.compositions[0],
        get_volume_derivs=False,
        get_enthalpy_derivs=True,
    )
    res = wrapper.ph_flash(pressure=30e5, enthalpy=aymix.enthalpy)
    assert res.temperature > 200.0  # safely above CO2 triple point
    assert res.temperature < 600.0
    assert res.num_phases >= 1
    assert res.phase_names  # non-empty


@pytest.mark.requires_multiflash
def test_ph_flash_handles_a_range_of_enthalpies(wrapper):
    """Sweep enthalpies at fixed P and confirm each returns a valid state."""
    P_Pa = 50e5
    for H in (-500.0, 0.0, 500.0, 2000.0):
        res = wrapper.ph_flash(pressure=P_Pa, enthalpy=H)
        assert res.num_phases >= 1
        assert 150.0 < res.temperature < 800.0
