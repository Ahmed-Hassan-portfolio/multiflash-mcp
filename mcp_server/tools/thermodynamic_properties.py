"""
Thermodynamic Property Tools - Advanced thermodynamic calculations.

Provides MCP tools for derived thermodynamic properties:
- get_joule_thomson_coefficient: JT coefficient for isenthalpic expansion

These properties are derived from fundamental AYMIX results (V, dV/dT, Cp).
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


def register_thermodynamic_tools(mcp_server, get_wrapper_fn, logger):
    """Register thermodynamic property tools with the MCP server."""

    @mcp_server.tool()
    def get_joule_thomson_coefficient(
        pressure: float,
        temperature: float,
        pressure_unit: str = "bar",
        temperature_unit: str = "C"
    ) -> dict:
        """
        Calculate the Joule-Thomson coefficient at given conditions.

        The JT coefficient describes temperature change during isenthalpic throttling:
            mu_JT = (dT/dP)_H = (V/Cp) * (T*beta - 1)

        where:
            V = molar volume
            beta = (1/V)(dV/dT)_P = thermal expansion coefficient
            Cp = heat capacity at constant pressure

        Interpretation:
            mu_JT > 0: Cooling on expansion (normal for most gases including CO2)
            mu_JT < 0: Heating on expansion (inverse JT effect)
            mu_JT = 0: Inversion point

        Args:
            pressure: Pressure value
            temperature: Temperature value
            pressure_unit: Pressure unit (default: "bar")
                Supported: bar, Pa, kPa, MPa, psi, atm
            temperature_unit: Temperature unit (default: "C")
                Supported: K (Kelvin), C (Celsius)

        Returns:
            Dict with JT coefficient and intermediate values:
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
                "phase_type": str,
                "joule_thomson_coefficient": {
                    "value_K_Pa": float,
                    "value_K_bar": float,
                    "value_C_bar": float
                },
                "interpretation": str,
                "intermediate_values": {
                    "molar_volume_m3_mol": float,
                    "thermal_expansion_1_K": float,
                    "Cp_J_mol_K": float
                }
            }

        Error codes:
            INVALID_INPUT: Bad units
            NO_FLUID_LOADED: No fluid loaded
            MULTI_PHASE: Two-phase region (JT coefficient undefined)
            CALC_FAILED: Property calculation failed

        Examples:
            >>> get_joule_thomson_coefficient(pressure=100, temperature=40)
            # Returns positive JT coefficient for CO2 (cooling on expansion)

            >>> get_joule_thomson_coefficient(pressure=100, temperature=40, pressure_unit="bar", temperature_unit="C")
            # Estimate cooling: ΔT ≈ mu_JT * ΔP
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

        # Execute flash to determine phase state
        try:
            flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
        except RuntimeError as e:
            raise MCPError("FLASH_FAILED", f"Flash calculation failed: {e}")

        # Check for single phase (JT coefficient undefined in two-phase region)
        if flash_result.num_phases > 1:
            raise MCPError(
                "MULTI_PHASE",
                f"JT coefficient undefined in two-phase region. "
                f"Found {flash_result.num_phases} phases: {flash_result.phase_names}"
            )

        # Get phase properties
        phase_lno = flash_result.phases[0]
        phase_name = flash_result.phase_names[0]
        phase_comp = flash_result.compositions[0]

        # Get AYMIX properties with volume and enthalpy derivatives
        try:
            aymix = wrapper.get_aymix_properties(
                phase_lno=phase_lno,
                temperature=T_k,
                pressure=P_pa,
                composition=phase_comp,
                get_volume_derivs=True,
                get_enthalpy_derivs=True  # Need Cp = dH/dT
            )
        except Exception as e:
            raise MCPError(
                "CALC_FAILED",
                f"Failed to get AYMIX properties: {e}"
            )

        # Extract properties
        V_m = aymix.volume           # m3/mol
        dV_dT = aymix.volume_T       # m3/(mol*K)
        Cp = aymix.enthalpy_T        # J/(mol*K)

        # Calculate thermal expansion coefficient
        # beta = (1/V)(dV/dT)_P in 1/K
        beta = dV_dT / V_m

        # Calculate Joule-Thomson coefficient
        # mu_JT = (V/Cp) * (T*beta - 1)
        # Unit: (m3/mol) / (J/(mol*K)) * (K * 1/K - 1) = m3*K/J = K/Pa
        mu_JT_K_Pa = (V_m / Cp) * (T_k * beta - 1)

        # Convert to K/bar (more practical for engineering)
        # 1 bar = 1e5 Pa, so K/Pa * Pa/bar = K/bar
        mu_JT_K_bar = mu_JT_K_Pa * 1e5

        # Determine interpretation
        if mu_JT_K_bar > 0:
            interpretation = "cooling on expansion"
        elif mu_JT_K_bar < 0:
            interpretation = "heating on expansion"
        else:
            interpretation = "inversion point (no temperature change)"

        # Build response
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
            "joule_thomson_coefficient": {
                "value_K_Pa": mu_JT_K_Pa,
                "value_K_bar": mu_JT_K_bar,
                "value_C_bar": mu_JT_K_bar  # Same as K/bar (differences, not absolute)
            },
            "interpretation": interpretation,
            "intermediate_values": {
                "molar_volume_m3_mol": V_m,
                "thermal_expansion_1_K": beta,
                "Cp_J_mol_K": Cp
            }
        }

        # Log and return
        logger.info(
            f"JT coefficient: {pressure} {pressure_unit}, {temperature} {temperature_unit} "
            f"-> {phase_name}: mu_JT={mu_JT_K_bar:.4f} K/bar ({interpretation})"
        )
        return response
