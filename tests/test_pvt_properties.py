"""PVT property tests via AYMIX. Requires Multiflash."""
from __future__ import annotations

import pytest

R_GAS = 8.314462618


@pytest.mark.requires_multiflash
def test_liquid_co2_density_in_expected_range(wrapper):
    """Liquid CO2 at 50 bar / 4 C should have density ~900-950 kg/m3.

    NIST reference: liquid CO2 at 50 bar / 4 C ~ 925 kg/m3.
    Allow a generous +/-5% band to accommodate EOS model differences.
    """
    T_K, P_Pa = 277.15, 50e5
    flash = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)
    aymix = wrapper.get_aymix_properties(
        phase_lno=flash.phases[0],
        temperature=T_K,
        pressure=P_Pa,
        composition=flash.compositions[0],
        get_volume_derivs=False,
    )
    mw = wrapper.get_molecular_weight(composition=flash.compositions[0])
    rho = mw / aymix.volume
    # Generous band: PR78 EOS is known to mispredict CO2 liquid density by ~3-5% vs NIST.
    assert 850.0 < rho < 975.0, f"liquid CO2 density {rho:.1f} kg/m3 outside expected band"


@pytest.mark.requires_multiflash
def test_co2_molecular_weight(wrapper):
    """Pure CO2 MW should be 44.01 g/mol within a tight tolerance."""
    mw = wrapper.get_molecular_weight()  # kg/mol
    assert mw == pytest.approx(0.04401, rel=1e-3)


@pytest.mark.requires_multiflash
def test_compressibility_factor_for_low_pressure_gas(wrapper):
    """Gas-phase CO2 at low pressure should have Z near 1.0."""
    T_K, P_Pa = 323.15, 1e5  # 50 C, 1 bar
    flash = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)
    aymix = wrapper.get_aymix_properties(
        phase_lno=flash.phases[0],
        temperature=T_K,
        pressure=P_Pa,
        composition=flash.compositions[0],
        get_volume_derivs=False,
    )
    Z = (P_Pa * aymix.volume) / (R_GAS * T_K)
    assert 0.98 < Z < 1.01, f"low-pressure gas Z = {Z:.4f}, expected ~1.0"
