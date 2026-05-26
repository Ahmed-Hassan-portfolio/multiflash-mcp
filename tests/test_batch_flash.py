"""Batch flash test — multiple PT points in sequence. Requires Multiflash."""
from __future__ import annotations

import pytest


@pytest.mark.requires_multiflash
def test_batch_flash_walks_pipeline_profile(wrapper):
    """Step through a typical CCS pipeline P/T profile; each point should resolve."""
    profile = [
        (150e5, 313.15),  # 150 bar, 40 C - dense liquid
        (120e5, 298.15),  # 120 bar, 25 C - dense liquid
        (90e5,  288.15),  # 90 bar, 15 C - dense liquid
        (80e5,  283.15),  # 80 bar, 10 C - dense liquid
        (10e5,  323.15),  # 10 bar, 50 C - gas
    ]
    results = []
    for P_Pa, T_K in profile:
        res = wrapper.pt_flash(temperature=T_K, pressure=P_Pa)
        assert res.num_phases >= 1
        results.append((P_Pa, T_K, res.phase_names[0]))

    high_pressure_points = [r for r in results if r[0] >= 80e5]
    assert all("LIQUID" in r[2].upper() for r in high_pressure_points), (
        f"expected liquid at high-pressure points, got {high_pressure_points}"
    )

    low_pressure_point = results[-1]
    assert "GAS" in low_pressure_point[2].upper(), (
        f"expected gas at 10 bar / 50 C, got {low_pressure_point[2]}"
    )
