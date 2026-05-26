"""Critical point reproduction for pure CO2. Requires Multiflash."""
from __future__ import annotations

import pytest


@pytest.mark.requires_multiflash
def test_co2_critical_point_reproduction(wrapper):
    """AXCRIT on pure CO2 should reproduce Tc and Pc within ~1% of accepted values.

    Accepted values (Span-Wagner reference equation of state):
        Tc = 304.13 K
        Pc = 73.77 bar
    """
    Tc_K, Pc_Pa, _Vc = wrapper.get_critical_point()
    assert Tc_K == pytest.approx(304.13, rel=0.01), f"Tc = {Tc_K:.2f} K, expected ~304.13"
    assert Pc_Pa / 1e5 == pytest.approx(73.77, rel=0.01), f"Pc = {Pc_Pa/1e5:.2f} bar, expected ~73.77"
