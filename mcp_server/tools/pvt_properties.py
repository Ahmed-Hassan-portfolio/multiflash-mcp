"""
PVT Properties Tool - Retrieve thermodynamic properties for single-phase systems.

Provides MCP tools for getting core PVT properties from Multiflash:
- get_pvt_properties: Returns density, MW, Z, compressibility, thermal expansion, molar volume

Accepts P/T with units and returns all properties with self-documenting unit strings.
Single-phase only (two-phase systems rejected with clear error).
"""

from typing import Optional

# Unit conversion functions - dual import pattern for both invocation methods
try:
    from mcp_server.utils.units import (
        convert_pressure_to_pa,
        convert_temperature_to_k,
        validate_pressure,
        validate_temperature
    )
except ImportError:
    from utils.units import (
        convert_pressure_to_pa,
        convert_temperature_to_k,
        validate_pressure,
        validate_temperature
    )


class MCPError(Exception):
    """Structured error for MCP responses - local copy to avoid circular import."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


# Universal gas constant
R_GAS = 8.314462618  # J/(mol·K)


def register_pvt_properties_tools(mcp_server, get_wrapper_fn, logger):
    """Register PVT properties tools with the MCP server."""

    @mcp_server.tool()
    def get_pvt_properties(
        pressure: float,
        temperature: float,
        pressure_unit: str = "bar",
        temperature_unit: str = "C"
    ) -> dict:
        """
        Get PVT properties for a single-phase system at given P, T.

        Returns core thermodynamic properties: density, molecular weight,
        compressibility factor, isothermal compressibility, thermal expansion,
        and molar volume. All properties include value and unit strings.

        IMPORTANT: This tool is for SINGLE-PHASE systems only. Two-phase
        systems will return an error directing you to use get_multiphase_properties
        (Phase 5).

        Args:
            pressure: Pressure value
            temperature: Temperature value
            pressure_unit: Pressure unit (default: "bar")
                Supported: bar, Pa, kPa, MPa, psi, atm
            temperature_unit: Temperature unit (default: "C")
                Supported: K (Kelvin), C (Celsius)

        Returns:
            Dict with PVT properties:
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
                "phase_type": str,  # "GAS", "LIQUID1", etc.
                "density": {"value": float, "unit": "kg/m3"},
                "molecular_weight_kg_mol": {"value": float, "unit": "kg/mol"},
                "molecular_weight_g_mol": {"value": float, "unit": "g/mol"},
                "compressibility_factor": {"value": float, "unit": "dimensionless"},
                "isothermal_compressibility_1_Pa": {"value": float, "unit": "1/Pa"},
                "isothermal_compressibility_1_bar": {"value": float, "unit": "1/bar"},
                "thermal_expansion": {"value": float, "unit": "1/K"},
                "molar_volume": {"value": float, "unit": "m3/mol"}
            }

        Error codes:
            INVALID_INPUT: Bad unit, negative pressure, or T < 0K
            NO_FLUID_LOADED: No fluid loaded via load_mfl_file or load_mfl_text
            MULTI_PHASE_SYSTEM: Two or more phases detected
            PROPERTY_CALC_FAILED: AYMIX or MW calculation failed

        Examples:
            >>> get_pvt_properties(pressure=50, temperature=4)
            # Returns liquid CO2 properties at 50 bar, 4°C

            >>> get_pvt_properties(pressure=10, temperature=50, pressure_unit="bar", temperature_unit="C")
            # Returns gas CO2 properties at 10 bar, 50°C
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

        # Execute flash internally
        try:
            flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
        except RuntimeError as e:
            raise MCPError("FLASH_FAILED", f"Flash calculation failed: {e}")

        # Check for single phase
        if flash_result.num_phases > 1:
            raise MCPError(
                "MULTI_PHASE_SYSTEM",
                f"Two phases detected at {pressure} {pressure_unit}, {temperature} {temperature_unit}. "
                f"This tool is for single-phase systems only. "
                f"Use get_multiphase_properties (Phase 5) for multi-phase systems."
            )

        # Get phase info
        phase_lno = flash_result.phases[0]
        phase_name = flash_result.phase_names[0]
        composition = flash_result.compositions[0]

        # Get AYMIX properties with volume derivatives
        try:
            aymix = wrapper.get_aymix_properties(
                phase_lno=phase_lno,
                temperature=T_k,
                pressure=P_pa,
                composition=composition,
                get_volume_derivs=True
            )
        except Exception as e:
            raise MCPError(
                "PROPERTY_CALC_FAILED",
                f"Failed to get AYMIX properties: {e}"
            )

        # Get molecular weight
        try:
            mw = wrapper.get_molecular_weight(composition=composition)
        except Exception as e:
            raise MCPError(
                "PROPERTY_CALC_FAILED",
                f"Failed to calculate molecular weight: {e}"
            )

        # Calculate derived properties
        V_m = aymix.volume          # m³/mol
        dV_dT = aymix.volume_T      # m³/(mol·K)
        dV_dP = aymix.volume_P      # m³/(mol·Pa)

        # Density: ρ = MW / V_m
        rho = mw / V_m  # kg/m³

        # Compressibility factor: Z = P·V_m / (R·T)
        Z = (P_pa * V_m) / (R_GAS * T_k)

        # Isothermal compressibility: Cv = -(1/V_m) * (dV/dP)_T
        # Note: dV/dP is negative, so -dV/dP/V_m is positive
        Cv_Pa = -dV_dP / V_m  # 1/Pa
        Cv_bar = Cv_Pa * 1e5  # 1/bar (1 bar = 1e5 Pa)

        # Thermal expansion: β = (1/V_m) * (dV/dT)_P
        beta = dV_dT / V_m  # 1/K

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
            "phase_type": phase_name,
            "density": {"value": rho, "unit": "kg/m3"},
            "molecular_weight_kg_mol": {"value": mw, "unit": "kg/mol"},
            "molecular_weight_g_mol": {"value": mw * 1000, "unit": "g/mol"},
            "compressibility_factor": {"value": Z, "unit": "dimensionless"},
            "isothermal_compressibility_1_Pa": {"value": Cv_Pa, "unit": "1/Pa"},
            "isothermal_compressibility_1_bar": {"value": Cv_bar, "unit": "1/bar"},
            "thermal_expansion": {"value": beta, "unit": "1/K"},
            "molar_volume": {"value": V_m, "unit": "m3/mol"}
        }

        # Log and return
        logger.info(
            f"PVT properties: {pressure} {pressure_unit}, {temperature} {temperature_unit} "
            f"-> {phase_name}: rho={rho:.2f} kg/m3, Z={Z:.4f}"
        )
        return response
