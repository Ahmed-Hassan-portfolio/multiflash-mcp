"""
Unit conversion utilities for pressure and temperature.

This module provides unit conversion functions to convert user-friendly units
(bar, C) to Multiflash's native SI units (Pa, K). Supports fuzzy matching of
unit names (case-insensitive, common aliases) and validates physical constraints.
"""

from typing import Callable

# Pressure conversion factors (all to Pa)
PRESSURE_UNITS: dict[str, float] = {
    "pa": 1.0,
    "kpa": 1e3,
    "mpa": 1e6,
    "bar": 1e5,
    "psi": 6894.757,
    "atm": 101325.0,
}

# Pressure unit aliases for fuzzy matching
PRESSURE_ALIASES: dict[str, str] = {
    "bars": "bar",
    "pascal": "pa",
    "pascals": "pa",
    "kilopascal": "kpa",
    "kilopascals": "kpa",
    "megapascal": "mpa",
    "megapascals": "mpa",
    "atmosphere": "atm",
    "atmospheres": "atm",
}

# Temperature conversion functions (all to K)
TEMPERATURE_UNITS: dict[str, Callable[[float], float]] = {
    "k": lambda t: t,  # Identity
    "c": lambda t: t + 273.15,  # Celsius to Kelvin
}

# Temperature unit aliases for fuzzy matching
TEMPERATURE_ALIASES: dict[str, str] = {
    "kelvin": "k",
    "kelvins": "k",
    "celsius": "c",
    "degc": "c",
    "deg_c": "c",
    "°c": "c",
}

# Enthalpy conversion factors (molar units to J/mol)
ENTHALPY_UNITS: dict[str, float] = {
    "j/mol": 1.0,
    "kj/mol": 1e3,
}

# Enthalpy mass-based units (to J/kg, then require MW for conversion to J/mol)
ENTHALPY_MASS_UNITS: dict[str, float] = {
    "j/kg": 1.0,      # Base mass unit
    "kj/kg": 1e3,     # kJ/kg to J/kg
}

# Enthalpy unit aliases for fuzzy matching
ENTHALPY_ALIASES: dict[str, str] = {
    "j_mol": "j/mol",
    "j per mol": "j/mol",
    "joule/mol": "j/mol",
    "joules/mol": "j/mol",
    "kj_mol": "kj/mol",
    "kj per mol": "kj/mol",
    "kilojoule/mol": "kj/mol",
    "kilojoules/mol": "kj/mol",
    "j_kg": "j/kg",
    "j per kg": "j/kg",
    "joule/kg": "j/kg",
    "joules/kg": "j/kg",
    "kj_kg": "kj/kg",
    "kj per kg": "kj/kg",
    "kilojoule/kg": "kj/kg",
    "kilojoules/kg": "kj/kg",
}


def normalize_pressure_unit(unit: str) -> str:
    """
    Normalize a pressure unit string to canonical form.

    Performs case-insensitive matching and resolves common aliases.

    Args:
        unit: Pressure unit string (e.g., "bar", "Bar", "bars", "MPa")

    Returns:
        Normalized unit string (e.g., "bar", "mpa")

    Raises:
        ValueError: If unit is not recognized

    Examples:
        >>> normalize_pressure_unit("BAR")
        'bar'
        >>> normalize_pressure_unit("bars")
        'bar'
        >>> normalize_pressure_unit("MPa")
        'mpa'
    """
    unit_lower = unit.strip().lower()

    # Check aliases first
    if unit_lower in PRESSURE_ALIASES:
        return PRESSURE_ALIASES[unit_lower]

    # Check direct units
    if unit_lower in PRESSURE_UNITS:
        return unit_lower

    # Unknown unit
    raise ValueError(
        f"Unknown pressure unit: '{unit}'. "
        f"Supported units: {', '.join(sorted(set(PRESSURE_UNITS.keys()) | set(PRESSURE_ALIASES.keys())))}"
    )


def normalize_temperature_unit(unit: str) -> str:
    """
    Normalize a temperature unit string to canonical form.

    Performs case-insensitive matching and resolves common aliases.

    Args:
        unit: Temperature unit string (e.g., "K", "C", "celsius")

    Returns:
        Normalized unit string (e.g., "k", "c")

    Raises:
        ValueError: If unit is not recognized

    Examples:
        >>> normalize_temperature_unit("Celsius")
        'c'
        >>> normalize_temperature_unit("K")
        'k'
    """
    unit_lower = unit.strip().lower()

    # Check aliases first
    if unit_lower in TEMPERATURE_ALIASES:
        return TEMPERATURE_ALIASES[unit_lower]

    # Check direct units
    if unit_lower in TEMPERATURE_UNITS:
        return unit_lower

    # Unknown unit
    raise ValueError(
        f"Unknown temperature unit: '{unit}'. "
        f"Supported units: {', '.join(sorted(set(TEMPERATURE_UNITS.keys()) | set(TEMPERATURE_ALIASES.keys())))}"
    )


def convert_pressure_to_pa(value: float, unit: str) -> float:
    """
    Convert pressure from given unit to Pascals (Pa).

    Args:
        value: Pressure value in the given unit
        unit: Unit string (e.g., "bar", "MPa", "psi")

    Returns:
        Pressure in Pascals (Pa)

    Raises:
        ValueError: If unit is not recognized

    Examples:
        >>> convert_pressure_to_pa(1, "bar")
        100000.0
        >>> convert_pressure_to_pa(1, "MPa")
        1000000.0
    """
    normalized = normalize_pressure_unit(unit)
    return value * PRESSURE_UNITS[normalized]


def convert_temperature_to_k(value: float, unit: str) -> float:
    """
    Convert temperature from given unit to Kelvin (K).

    Args:
        value: Temperature value in the given unit
        unit: Unit string (e.g., "K", "C")

    Returns:
        Temperature in Kelvin (K)

    Raises:
        ValueError: If unit is not recognized

    Examples:
        >>> convert_temperature_to_k(25, "C")
        298.15
        >>> convert_temperature_to_k(300, "K")
        300.0
    """
    normalized = normalize_temperature_unit(unit)
    return TEMPERATURE_UNITS[normalized](value)


def validate_pressure(value: float, unit: str) -> None:
    """
    Validate that a pressure value is physically reasonable.

    Checks that the pressure is positive when converted to Pa.

    Args:
        value: Pressure value in the given unit
        unit: Unit string (e.g., "bar", "MPa")

    Raises:
        ValueError: If pressure is not positive or unit is invalid

    Examples:
        >>> validate_pressure(50, "bar")  # OK
        >>> validate_pressure(-1, "bar")  # Raises ValueError
    """
    p_pa = convert_pressure_to_pa(value, unit)

    if p_pa <= 0:
        raise ValueError(
            f"Pressure must be positive. Got {value} {unit} = {p_pa} Pa"
        )


def validate_temperature(value: float, unit: str) -> None:
    """
    Validate that a temperature value is physically reasonable.

    Checks that the temperature is not below absolute zero (0 K).

    Args:
        value: Temperature value in the given unit
        unit: Unit string (e.g., "K", "C")

    Raises:
        ValueError: If temperature is below 0 K or unit is invalid

    Examples:
        >>> validate_temperature(25, "C")  # OK
        >>> validate_temperature(-300, "K")  # Raises ValueError
    """
    t_k = convert_temperature_to_k(value, unit)

    if t_k < 0:
        raise ValueError(
            f"Temperature cannot be below absolute zero (0 K). "
            f"Got {value} {unit} = {t_k} K"
        )


def normalize_enthalpy_unit(unit: str) -> str:
    """
    Normalize an enthalpy unit string to canonical form.

    Performs case-insensitive matching and resolves common aliases.

    Args:
        unit: Enthalpy unit string (e.g., "J/mol", "kJ/kg", "j_mol")

    Returns:
        Normalized unit string (e.g., "j/mol", "kj/kg")

    Raises:
        ValueError: If unit is not recognized

    Examples:
        >>> normalize_enthalpy_unit("J/MOL")
        'j/mol'
        >>> normalize_enthalpy_unit("kJ_kg")
        'kj/kg'
    """
    unit_lower = unit.strip().lower().replace('_', '/').replace(' ', '')

    # Check aliases first
    if unit_lower in ENTHALPY_ALIASES:
        return ENTHALPY_ALIASES[unit_lower]

    # Check direct units (molar)
    if unit_lower in ENTHALPY_UNITS:
        return unit_lower

    # Check mass-based units
    if unit_lower in ENTHALPY_MASS_UNITS:
        return unit_lower

    # Unknown unit
    all_units = set(ENTHALPY_UNITS.keys()) | set(ENTHALPY_MASS_UNITS.keys()) | set(ENTHALPY_ALIASES.keys())
    raise ValueError(
        f"Unknown enthalpy unit: '{unit}'. "
        f"Supported units: {', '.join(sorted(all_units))}"
    )


def convert_enthalpy_to_j_mol(value: float, unit: str, molecular_weight_kg_mol: float = None) -> float:
    """
    Convert enthalpy from given unit to J/mol.

    For molar units (J/mol, kJ/mol): direct conversion.
    For mass units (J/kg, kJ/kg): requires molecular_weight_kg_mol parameter.

    Args:
        value: Enthalpy value in the given unit
        unit: Unit string (e.g., "J/mol", "kJ/mol", "J/kg", "kJ/kg")
        molecular_weight_kg_mol: Molecular weight in kg/mol (required for mass-based units)

    Returns:
        Enthalpy in J/mol

    Raises:
        ValueError: If unit is not recognized or MW is missing for mass units

    Examples:
        >>> convert_enthalpy_to_j_mol(1, "J/mol")
        1.0
        >>> convert_enthalpy_to_j_mol(1, "kJ/mol")
        1000.0
        >>> convert_enthalpy_to_j_mol(1000, "J/kg", 0.04401)  # CO2
        44.01
    """
    normalized = normalize_enthalpy_unit(unit)

    # Molar units - direct conversion
    if normalized in ENTHALPY_UNITS:
        return value * ENTHALPY_UNITS[normalized]

    # Mass-based units - need molecular weight
    if normalized in ENTHALPY_MASS_UNITS:
        if molecular_weight_kg_mol is None:
            raise ValueError(
                f"Molecular weight required for mass-based enthalpy unit '{unit}'. "
                f"Cannot convert J/kg or kJ/kg to J/mol without knowing the molecular weight."
            )
        # Convert to J/kg first, then to J/mol using MW
        h_j_kg = value * ENTHALPY_MASS_UNITS[normalized]
        h_j_mol = h_j_kg * molecular_weight_kg_mol
        return h_j_mol

    # Should not reach here after normalize_enthalpy_unit
    raise ValueError(f"Unknown enthalpy unit: '{unit}'")


def validate_enthalpy(value: float, unit: str) -> None:
    """
    Validate that an enthalpy unit is recognized.

    Note: Enthalpy can be negative (exothermic reference state),
    so no physical constraint on sign.

    Args:
        value: Enthalpy value in the given unit
        unit: Unit string (e.g., "J/mol", "kJ/kg")

    Raises:
        ValueError: If unit is invalid

    Examples:
        >>> validate_enthalpy(1000, "J/mol")  # OK
        >>> validate_enthalpy(-500, "kJ/mol")  # OK (enthalpy can be negative)
    """
    # Just validate the unit is recognized
    normalize_enthalpy_unit(unit)
