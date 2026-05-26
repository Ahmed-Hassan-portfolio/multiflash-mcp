"""
Unit conversion tests. No DLL or license required.

Exercises mcp_server.utils.units, the boundary layer that converts
user-facing units (bar / C / kJ/mol / ...) to Multiflash SI internals.
"""
from __future__ import annotations

import math

import pytest

from mcp_server.utils.units import (
    convert_enthalpy_to_j_mol,
    convert_pressure_to_pa,
    convert_temperature_to_k,
    normalize_pressure_unit,
    normalize_temperature_unit,
    validate_pressure,
    validate_temperature,
)


@pytest.mark.parametrize(
    "value,unit,expected_pa",
    [
        (1, "Pa", 1.0),
        (1, "kPa", 1e3),
        (1, "MPa", 1e6),
        (1, "bar", 1e5),
        (1, "atm", 101325.0),
        (1, "psi", 6894.757),
    ],
)
def test_convert_pressure_to_pa(value, unit, expected_pa):
    assert math.isclose(convert_pressure_to_pa(value, unit), expected_pa, rel_tol=1e-6)


def test_pressure_unit_is_case_insensitive_and_handles_aliases():
    assert convert_pressure_to_pa(1, "BAR") == 1e5
    assert convert_pressure_to_pa(1, "Bars") == 1e5
    assert convert_pressure_to_pa(1, "megapascal") == 1e6


def test_unknown_pressure_unit_raises():
    with pytest.raises(ValueError, match="Unknown pressure unit"):
        normalize_pressure_unit("xyz")


def test_celsius_to_kelvin():
    assert convert_temperature_to_k(0, "C") == pytest.approx(273.15)
    assert convert_temperature_to_k(25, "C") == pytest.approx(298.15)
    assert convert_temperature_to_k(300, "K") == 300.0


def test_temperature_aliases():
    assert normalize_temperature_unit("Celsius") == "c"
    assert normalize_temperature_unit("Kelvin") == "k"
    assert normalize_temperature_unit("degC") == "c"


def test_validate_pressure_rejects_non_positive():
    validate_pressure(50, "bar")
    with pytest.raises(ValueError):
        validate_pressure(0, "bar")
    with pytest.raises(ValueError):
        validate_pressure(-1, "bar")


def test_validate_temperature_rejects_below_absolute_zero():
    validate_temperature(0, "K")
    validate_temperature(-273.14, "C")
    with pytest.raises(ValueError):
        validate_temperature(-300, "K")
    with pytest.raises(ValueError):
        validate_temperature(-273.16, "C")


def test_enthalpy_molar_conversion():
    assert convert_enthalpy_to_j_mol(1, "J/mol") == 1.0
    assert convert_enthalpy_to_j_mol(1, "kJ/mol") == 1000.0


def test_enthalpy_mass_unit_requires_molecular_weight():
    with pytest.raises(ValueError, match="Molecular weight required"):
        convert_enthalpy_to_j_mol(1000, "J/kg")
    # CO2 MW = 0.04401 kg/mol -> 1000 J/kg -> 44.01 J/mol
    assert convert_enthalpy_to_j_mol(1000, "J/kg", 0.04401) == pytest.approx(44.01)
