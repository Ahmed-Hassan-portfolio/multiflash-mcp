"""PT flash sanity tests on pure CO2. Requires Multiflash."""
from __future__ import annotations

import pytest


@pytest.mark.requires_multiflash
def test_pure_co2_below_saturation_is_liquid(wrapper):
    # At 50 bar / 4 C we are above the CO2 saturation pressure at 4 C (~38.5 bar),
    # so the fluid should be a single liquid phase.
    res = wrapper.pt_flash(temperature=277.15, pressure=50e5)
    assert res.num_phases == 1
    assert "LIQUID" in res.phase_names[0].upper()


@pytest.mark.requires_multiflash
def test_pure_co2_low_pressure_is_gas(wrapper):
    # At 5 bar / 25 C we are well above saturation T at 5 bar, so gas phase.
    res = wrapper.pt_flash(temperature=298.15, pressure=5e5)
    assert res.num_phases == 1
    assert "GAS" in res.phase_names[0].upper()


@pytest.mark.requires_multiflash
def test_pure_co2_above_critical_is_single_phase(wrapper):
    # Above Tc (304.13 K) and Pc (73.77 bar) -> supercritical fluid, single phase.
    res = wrapper.pt_flash(temperature=320.0, pressure=100e5)
    assert res.num_phases == 1
