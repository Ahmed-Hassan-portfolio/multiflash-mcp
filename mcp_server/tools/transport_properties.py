"""
Transport Properties Tool - Retrieve viscosity and thermal conductivity.

Provides MCP tools for getting transport properties from Multiflash:
- get_transport_properties: Returns viscosity and thermal conductivity

Handles both single-phase and multi-phase systems.
Accepts P/T with units and returns all properties with self-documenting unit strings.
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


def register_transport_properties_tools(mcp_server, get_wrapper_fn, logger):
    """Register transport properties tools with the MCP server."""

    @mcp_server.tool()
    def get_transport_properties(
        pressure: float,
        temperature: float,
        pressure_unit: str = "bar",
        temperature_unit: str = "C"
    ) -> dict:
        """
        Get transport properties (viscosity, thermal conductivity) at given P, T.

        Returns viscosity (in Pa.s and cP) and thermal conductivity (in W/(m.K))
        for both single-phase and multi-phase systems.

        For single-phase: Returns flat response with transport properties.
        For multi-phase: Returns per-phase properties plus volume-weighted bulk averages.

        Args:
            pressure: Pressure value
            temperature: Temperature value
            pressure_unit: Pressure unit (default: "bar")
                Supported: bar, Pa, kPa, MPa, psi, atm
            temperature_unit: Temperature unit (default: "C")
                Supported: K (Kelvin), C (Celsius)

        Returns:
            Dict with transport properties.

            Single-phase response:
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
                "viscosity_Pa_s": {"value": float, "unit": "Pa.s"},
                "viscosity_cP": {"value": float, "unit": "cP"},
                "thermal_conductivity": {"value": float, "unit": "W/(m.K)"}
            }

            Multi-phase response:
            {
                "input": {...},
                "conditions_si": {...},
                "phases": {
                    "GAS": {
                        "mole_fraction": float,
                        "volume_fraction": float,
                        "viscosity_Pa_s": {"value": float, "unit": "Pa.s"},
                        "viscosity_cP": {"value": float, "unit": "cP"},
                        "thermal_conductivity": {"value": float, "unit": "W/(m.K)"}
                    },
                    "LIQUID1": {...}  # Same structure for each phase
                },
                "bulk": {
                    "viscosity_Pa_s": {"value": float, "unit": "Pa.s"},  # Volume-weighted
                    "viscosity_cP": {"value": float, "unit": "cP"},
                    "thermal_conductivity": {"value": float, "unit": "W/(m.K)"}  # Volume-weighted
                }
            }

        Error codes:
            INVALID_INPUT: Bad unit, negative pressure, or T < 0K
            NO_FLUID_LOADED: No fluid loaded via load_mfl_file or load_mfl_text
            FLASH_FAILED: Flash calculation failed
            TRANSPORT_CALC_FAILED: AYVISC or AYTCND calculation failed

        Examples:
            >>> # Liquid CO2 transport properties
            >>> get_transport_properties(pressure=50, temperature=4)
            # Returns viscosity ~0.1 cP and thermal conductivity

            >>> # Gas CO2 transport properties
            >>> get_transport_properties(pressure=10, temperature=50)
            # Returns gas phase transport properties

            >>> # Two-phase system (VLE)
            >>> get_transport_properties(pressure=34.85, temperature=0)
            # Returns per-phase and bulk transport properties
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

        # Handle single-phase system
        if flash_result.num_phases == 1:
            phase_lno = flash_result.phases[0]
            phase_name = flash_result.phase_names[0]
            composition = flash_result.compositions[0]

            # Get transport properties
            try:
                visc_result = wrapper.get_viscosity(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=composition,
                    get_derivatives=False
                )
                cond_result = wrapper.get_thermal_conductivity(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=composition,
                    get_derivatives=False
                )
            except Exception as e:
                raise MCPError(
                    "TRANSPORT_CALC_FAILED",
                    f"Failed to get transport properties: {e}"
                )

            # Convert viscosity to cP (1 Pa.s = 1000 cP)
            mu_pa_s = visc_result.value
            mu_cP = mu_pa_s * 1000.0

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
                "viscosity_Pa_s": {"value": mu_pa_s, "unit": "Pa.s"},
                "viscosity_cP": {"value": mu_cP, "unit": "cP"},
                "thermal_conductivity": {"value": cond_result.value, "unit": "W/(m.K)"}
            }

            logger.info(
                f"Transport properties (single-phase): {pressure} {pressure_unit}, "
                f"{temperature} {temperature_unit} -> {phase_name}: "
                f"mu={mu_cP:.4f} cP, k={cond_result.value:.4f} W/(m.K)"
            )
            return response

        # Handle multi-phase system
        total_moles = sum(flash_result.moles_per_phase)
        if total_moles <= 0:
            raise MCPError(
                "FLASH_FAILED",
                "Flash returned zero or negative total moles - invalid result"
            )

        # Process each phase
        phases_data = {}
        phase_volumes = []

        for i, (phase_lno, phase_name, n_i, comp_i) in enumerate(zip(
            flash_result.phases,
            flash_result.phase_names,
            flash_result.moles_per_phase,
            flash_result.compositions
        )):
            # Get transport properties
            try:
                visc_result = wrapper.get_viscosity(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=comp_i,
                    get_derivatives=False
                )
                cond_result = wrapper.get_thermal_conductivity(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=comp_i,
                    get_derivatives=False
                )
            except Exception as e:
                raise MCPError(
                    "TRANSPORT_CALC_FAILED",
                    f"Failed to get transport properties for phase {phase_name}: {e}"
                )

            # Get molar volume for volume fraction calculation
            try:
                aymix = wrapper.get_aymix_properties(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=comp_i,
                    get_volume_derivs=False
                )
                V_m = aymix.volume
            except Exception as e:
                raise MCPError(
                    "TRANSPORT_CALC_FAILED",
                    f"Failed to get molar volume for phase {phase_name}: {e}"
                )

            # Calculate phase fractions
            mole_fraction = n_i / total_moles
            volume_i = n_i * V_m
            phase_volumes.append(volume_i)

            # Convert viscosity to cP
            mu_pa_s = visc_result.value
            mu_cP = mu_pa_s * 1000.0

            # Store phase data
            phases_data[phase_name] = {
                "mole_fraction": mole_fraction,
                "volume_fraction": None,  # Will calculate after all phases processed
                "viscosity_Pa_s": {"value": mu_pa_s, "unit": "Pa.s"},
                "viscosity_cP": {"value": mu_cP, "unit": "cP"},
                "thermal_conductivity": {"value": cond_result.value, "unit": "W/(m.K)"}
            }

        # Calculate volume fractions
        total_volume = sum(phase_volumes)
        vol_fractions = [v / total_volume for v in phase_volumes]

        for i, phase_name in enumerate(phases_data.keys()):
            phases_data[phase_name]["volume_fraction"] = vol_fractions[i]

        # Calculate bulk properties (volume-weighted)
        bulk_mu_pa_s = sum(
            vol_fractions[i] * list(phases_data.values())[i]["viscosity_Pa_s"]["value"]
            for i in range(len(vol_fractions))
        )
        bulk_k = sum(
            vol_fractions[i] * list(phases_data.values())[i]["thermal_conductivity"]["value"]
            for i in range(len(vol_fractions))
        )

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
            "phases": phases_data,
            "bulk": {
                "viscosity_Pa_s": {"value": bulk_mu_pa_s, "unit": "Pa.s"},
                "viscosity_cP": {"value": bulk_mu_pa_s * 1000.0, "unit": "cP"},
                "thermal_conductivity": {"value": bulk_k, "unit": "W/(m.K)"}
            }
        }

        logger.info(
            f"Transport properties (multi-phase): {pressure} {pressure_unit}, "
            f"{temperature} {temperature_unit} -> {len(phases_data)} phases: "
            f"{list(phases_data.keys())}"
        )
        return response
