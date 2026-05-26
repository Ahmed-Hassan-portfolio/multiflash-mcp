"""
Flash Calculation Tools - Execute flash calculations with unit-aware inputs.

Provides MCP tools for thermodynamic flash calculations using Multiflash:
- pt_flash: Pressure-Temperature flash with unit parameters (bar, C)

Accepts common engineering units and converts to Multiflash SI units (Pa, K).
"""

from typing import Optional

# Unit conversion functions - dual import pattern for both invocation methods
try:
    from mcp_server.utils.units import (
        convert_pressure_to_pa,
        convert_temperature_to_k,
        convert_enthalpy_to_j_mol,
        validate_pressure,
        validate_temperature,
        validate_enthalpy
    )
except ImportError:
    from utils.units import (
        convert_pressure_to_pa,
        convert_temperature_to_k,
        convert_enthalpy_to_j_mol,
        validate_pressure,
        validate_temperature,
        validate_enthalpy
    )


class MCPError(Exception):
    """Structured error for MCP responses - local copy to avoid circular import."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


def register_flash_tools(mcp_server, get_wrapper_fn, logger):
    """Register flash calculation tools with the MCP server."""

    @mcp_server.tool()
    def pt_flash(
        pressure: float,
        temperature: float,
        pressure_unit: str = "bar",
        temperature_unit: str = "C"
    ) -> dict:
        """
        Execute a Pressure-Temperature flash calculation.

        Performs a PT flash using the currently loaded fluid and returns phase
        information (number of phases, phase types, mole fractions).

        Args:
            pressure: Pressure value
            temperature: Temperature value
            pressure_unit: Pressure unit (default: "bar")
                Supported: bar, Pa, kPa, MPa, psi, atm
            temperature_unit: Temperature unit (default: "C")
                Supported: K (Kelvin), C (Celsius)

        Returns:
            Dict with flash results:
            {
                "input": {
                    "pressure": float,
                    "pressure_unit": str,
                    "temperature": float,
                    "temperature_unit": str
                },
                "conditions_si": {
                    "pressure_Pa": float,
                    "temperature_K": float
                },
                "num_phases": int,
                "phases": [
                    {
                        "name": str,           # Phase type (GAS, LIQUID1, etc.)
                        "mole_fraction": float,  # Mole fraction of this phase
                        "moles": float         # Absolute moles in this phase
                    },
                    ...
                ]
            }

        Error codes:
            INVALID_INPUT: Bad unit, negative pressure, or T < 0K
            NO_FLUID_LOADED: No fluid loaded via load_mfl_file or load_mfl_text
            FLASH_FAILED: Multiflash flash calculation failed

        Examples:
            >>> pt_flash(pressure=50, temperature=4, pressure_unit="bar", temperature_unit="C")
            {"num_phases": 1, "phases": [{"name": "LIQUID1", "mole_fraction": 1.0, ...}]}

            >>> pt_flash(pressure=5000, temperature=300, pressure_unit="kPa", temperature_unit="K")
            {"num_phases": 2, "phases": [...]}
        """
        # Validate and convert units
        try:
            validate_pressure(pressure, pressure_unit)
            validate_temperature(temperature, temperature_unit)
            P_pa = convert_pressure_to_pa(pressure, pressure_unit)
            T_k = convert_temperature_to_k(temperature, temperature_unit)
        except ValueError as e:
            raise MCPError("INVALID_INPUT", str(e))

        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise  # Re-raise DLL connection errors as-is

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file or load_mfl_text first."
            )

        # Execute flash
        try:
            result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
        except RuntimeError as e:
            raise MCPError("FLASH_FAILED", f"Flash calculation failed: {e}")

        # Calculate phase fractions
        total_moles = sum(result.moles_per_phase)

        if total_moles == 0:
            raise MCPError(
                "FLASH_FAILED",
                "Flash returned zero total moles - invalid result"
            )

        phases = []
        for phase_name, moles in zip(result.phase_names, result.moles_per_phase):
            mole_fraction = moles / total_moles
            phases.append({
                "name": phase_name,
                "mole_fraction": mole_fraction,
                "moles": moles
            })

        # Build response structure
        response = {
            "input": {
                "pressure": pressure,
                "pressure_unit": pressure_unit,
                "temperature": temperature,
                "temperature_unit": temperature_unit
            },
            "conditions_si": {
                "pressure_Pa": P_pa,
                "temperature_K": T_k
            },
            "num_phases": result.num_phases,
            "phases": phases
        }

        # Log and return
        logger.info(
            f"PT flash: {pressure} {pressure_unit}, {temperature} {temperature_unit} "
            f"-> {result.num_phases} phase(s): {result.phase_names}"
        )
        return response

    @mcp_server.tool()
    def ph_flash(
        pressure: float,
        enthalpy: float,
        pressure_unit: str = "bar",
        enthalpy_unit: str = "J/mol"
    ) -> dict:
        """
        Execute a Pressure-Enthalpy flash calculation.

        Calculates equilibrium temperature and phase state for an isenthalpic
        process (constant enthalpy). Essential for:
        - Valve/choke expansion modeling
        - Joule-Thomson cooling prediction
        - Heat exchanger outlet conditions

        Args:
            pressure: Target pressure after expansion/process
            enthalpy: Molar enthalpy (conserved in isenthalpic process)
            pressure_unit: Pressure unit (default: "bar")
                Supported: bar, Pa, kPa, MPa, psi, atm
            enthalpy_unit: Enthalpy unit (default: "J/mol")
                Supported: J/mol, kJ/mol, J/kg, kJ/kg
                Note: kg-based units require loaded fluid for MW

        Returns:
            Dict with flash results:
            {
                "input": {...},
                "conditions_si": {
                    "pressure_Pa": float,
                    "enthalpy_J_mol": float
                },
                "result": {
                    "temperature_K": float,
                    "temperature_C": float
                },
                "num_phases": int,
                "phases": [...]
            }

        Error codes:
            INVALID_INPUT: Bad unit, negative pressure
            NO_FLUID_LOADED: No fluid loaded
            FLASH_FAILED: Flash calculation failed
            SOLID_FORMED: Conditions lead to solid phase
        """
        # Validate and convert pressure
        try:
            validate_pressure(pressure, pressure_unit)
            P_pa = convert_pressure_to_pa(pressure, pressure_unit)
        except ValueError as e:
            raise MCPError("INVALID_INPUT", str(e))

        # Get wrapper first (needed for MW if using mass units)
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file or load_mfl_text first."
            )

        # Convert enthalpy - need MW for mass-based units
        try:
            validate_enthalpy(enthalpy, enthalpy_unit)
            unit_lower = enthalpy_unit.lower().replace('_', '/').replace(' ', '')

            if '/kg' in unit_lower:
                # Mass-based unit - get MW from wrapper
                mw = wrapper.get_molecular_weight()  # kg/mol
                H_j_mol = convert_enthalpy_to_j_mol(enthalpy, enthalpy_unit, mw)
            else:
                # Molar unit - direct conversion
                H_j_mol = convert_enthalpy_to_j_mol(enthalpy, enthalpy_unit)
        except ValueError as e:
            raise MCPError("INVALID_INPUT", str(e))

        # Execute flash
        try:
            result = wrapper.ph_flash(pressure=P_pa, enthalpy=H_j_mol)
        except RuntimeError as e:
            error_msg = str(e)
            if "SOLID_FORMED" in error_msg:
                raise MCPError("SOLID_FORMED", error_msg)
            raise MCPError("FLASH_FAILED", f"PH flash calculation failed: {e}")

        # Calculate phase fractions
        total_moles = sum(result.moles_per_phase)
        if total_moles == 0:
            raise MCPError(
                "FLASH_FAILED",
                "Flash returned zero total moles - invalid result"
            )

        phases = []
        for phase_name, moles in zip(result.phase_names, result.moles_per_phase):
            mole_fraction = moles / total_moles
            phases.append({
                "name": phase_name,
                "mole_fraction": mole_fraction,
                "moles": moles
            })

        # Build response
        response = {
            "input": {
                "pressure": pressure,
                "pressure_unit": pressure_unit,
                "enthalpy": enthalpy,
                "enthalpy_unit": enthalpy_unit
            },
            "conditions_si": {
                "pressure_Pa": P_pa,
                "enthalpy_J_mol": H_j_mol
            },
            "result": {
                "temperature_K": result.temperature,
                "temperature_C": result.temperature - 273.15
            },
            "num_phases": result.num_phases,
            "phases": phases
        }

        logger.info(
            f"PH flash: {pressure} {pressure_unit}, {enthalpy} {enthalpy_unit} "
            f"-> T={result.temperature:.2f} K, {result.num_phases} phase(s)"
        )
        return response
