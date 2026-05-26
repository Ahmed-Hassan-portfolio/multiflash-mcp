"""Transport property sanity tests (viscosity, thermal conductivity). Requires Multiflash."""
from __future__ import annotations

import pytest


@pytest.mark.requires_multiflash
def test_liquid_co2_viscosity_in_expected_range(wrapper):
    """Liquid CO2 at 50 bar / 4 C should have viscosity in the 0.05-0.20 cP band."""
    T_K, P_Pa = 277.15, 50e5
    flash = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)
    mu_pa_s = wrapper.get_viscosity(
        phase_lno=flash.phases[0],
        temperature=T_K,
        pressure=P_Pa,
        composition=flash.compositions[0],
    ).value
    mu_cP = mu_pa_s * 1000.0
    assert 0.05 < mu_cP < 0.20, f"liquid CO2 viscosity {mu_cP:.4f} cP outside expected band"


@pytest.mark.requires_multiflash
def test_gas_co2_viscosity_lower_than_liquid(wrapper):
    """Gas viscosity at 5 bar / 25 C should be much smaller than liquid viscosity."""
    T_K, P_Pa = 298.15, 5e5
    flash = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)
    mu_pa_s = wrapper.get_viscosity(
        phase_lno=flash.phases[0],
        temperature=T_K,
        pressure=P_Pa,
        composition=flash.compositions[0],
    ).value
    mu_cP = mu_pa_s * 1000.0
    assert mu_cP < 0.05, f"gas CO2 viscosity {mu_cP:.4f} cP unexpectedly high"


@pytest.mark.requires_multiflash
def test_liquid_co2_thermal_conductivity(wrapper):
    """Liquid CO2 thermal conductivity at 50 bar / 4 C should be ~0.1-0.15 W/(m K)."""
    T_K, P_Pa = 277.15, 50e5
    flash = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)
    k = wrapper.get_thermal_conductivity(
        phase_lno=flash.phases[0],
        temperature=T_K,
        pressure=P_Pa,
        composition=flash.compositions[0],
    ).value
    assert 0.08 < k < 0.18, f"liquid CO2 thermal conductivity {k:.4f} W/(m K) outside expected band"
