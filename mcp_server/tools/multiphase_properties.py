"""
Multi-Phase Properties Tool - Retrieve thermodynamic properties for multi-phase systems.

Provides MCP tools for getting per-phase and bulk PVT properties from Multiflash:
- get_multiphase_properties: Returns properties for each phase plus bulk/overall values

Handles vapor-liquid equilibrium (VLE) and other two-phase systems.
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


# Universal gas constant
R_GAS = 8.314462618  # J/(mol·K)


def register_multiphase_properties_tools(mcp_server, get_wrapper_fn, logger):
    """Register multi-phase properties tools with the MCP server."""

    @mcp_server.tool()
    def get_multiphase_properties(
        pressure: float,
        temperature: float,
        pressure_unit: str = "bar",
        temperature_unit: str = "C"
    ) -> dict:
        """
        Get PVT properties for a multi-phase system at given P, T.

        Returns per-phase thermodynamic properties (density, MW, Z, Cv, beta, V_m)
        for each phase detected by flash calculation, plus bulk/overall properties.

        IMPORTANT: This tool is for MULTI-PHASE systems only (e.g., vapor-liquid
        equilibrium near CO2 saturation curve). Single-phase systems will return
        an error directing you to use get_pvt_properties instead.

        Per-phase properties are calculated using AYMIX for each individual phase.
        Bulk properties are calculated from per-phase values using thermodynamically
        correct averaging methods.

        Args:
            pressure: Pressure value
            temperature: Temperature value
            pressure_unit: Pressure unit (default: "bar")
                Supported: bar, Pa, kPa, MPa, psi, atm
            temperature_unit: Temperature unit (default: "C")
                Supported: K (Kelvin), C (Celsius)

        Returns:
            Dict with multi-phase PVT properties:
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
                "phases": {
                    "GAS": {
                        "mole_fraction": float,  # Moles of this phase / total moles
                        "volume_fraction": float,  # Volume of this phase / total volume
                        "composition": [float, ...],  # Component mole fractions in this phase
                        "density": {"value": float, "unit": "kg/m3"},
                        "molecular_weight_kg_mol": {"value": float, "unit": "kg/mol"},
                        "molecular_weight_g_mol": {"value": float, "unit": "g/mol"},
                        "compressibility_factor": {"value": float, "unit": "dimensionless"},
                        "isothermal_compressibility_1_Pa": {"value": float, "unit": "1/Pa"},
                        "isothermal_compressibility_1_bar": {"value": float, "unit": "1/bar"},
                        "thermal_expansion": {"value": float, "unit": "1/K"},
                        "molar_volume": {"value": float, "unit": "m3/mol"}
                    },
                    "LIQUID1": {...}  # Same structure for each phase
                },
                "bulk": {
                    "density": {"value": float, "unit": "kg/m3"},  # Volume-weighted
                    "molecular_weight_kg_mol": {"value": float, "unit": "kg/mol"},  # Mole-weighted
                    "molecular_weight_g_mol": {"value": float, "unit": "g/mol"},
                    "compressibility_factor": {"value": null, "reason": "No meaningful bulk Z for two-phase mixture"},
                    "isothermal_compressibility": {"value": null, "reason": "Cv averaging depends on flow regime"},
                    "thermal_expansion": {"value": null, "reason": "Beta averaging depends on flow regime"}
                },
                "warning": str  # Optional: present if phases are near-critical
            }

        Error codes:
            INVALID_INPUT: Bad unit, negative pressure, or T < 0K
            NO_FLUID_LOADED: No fluid loaded via load_mfl_file or load_mfl_text
            SINGLE_PHASE_SYSTEM: Only one phase detected
            PROPERTY_CALC_FAILED: AYMIX or MW calculation failed
            FLASH_FAILED: Flash calculation failed

        Examples:
            >>> # CO2 at saturation conditions (VLE)
            >>> get_multiphase_properties(pressure=34.85, temperature=0)
            # Returns gas and liquid phase properties at CO2 saturation

            >>> # Binary mixture two-phase region
            >>> get_multiphase_properties(pressure=50, temperature=10, pressure_unit="bar")
            # Returns properties for both phases if mixture is in VLE region
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

        # Reject single-phase systems
        if flash_result.num_phases == 1:
            phase_name = flash_result.phase_names[0]
            raise MCPError(
                "SINGLE_PHASE_SYSTEM",
                f"Only one phase detected ({phase_name}) at {pressure} {pressure_unit}, "
                f"{temperature} {temperature_unit}. This tool is for multi-phase systems only. "
                f"Use get_pvt_properties for single-phase systems."
            )

        # Calculate total moles
        total_moles = sum(flash_result.moles_per_phase)
        if total_moles <= 0:
            raise MCPError(
                "FLASH_FAILED",
                "Flash returned zero or negative total moles - invalid result"
            )

        # Process each phase
        phases_data = {}
        phase_volumes = []  # For volume fraction calculation
        phase_densities = []  # For near-critical warning

        for i, (phase_lno, phase_name, n_i, comp_i) in enumerate(zip(
            flash_result.phases,
            flash_result.phase_names,
            flash_result.moles_per_phase,
            flash_result.compositions
        )):
            # Get AYMIX properties with volume derivatives
            try:
                aymix = wrapper.get_aymix_properties(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=comp_i,
                    get_volume_derivs=True
                )
            except Exception as e:
                raise MCPError(
                    "PROPERTY_CALC_FAILED",
                    f"Failed to get AYMIX properties for phase {phase_name}: {e}"
                )

            # Get molecular weight for this phase
            try:
                mw = wrapper.get_molecular_weight(composition=comp_i)
            except Exception as e:
                raise MCPError(
                    "PROPERTY_CALC_FAILED",
                    f"Failed to calculate molecular weight for phase {phase_name}: {e}"
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
            Cv_Pa = -dV_dP / V_m  # 1/Pa
            Cv_bar = Cv_Pa * 1e5  # 1/bar

            # Thermal expansion: β = (1/V_m) * (dV/dT)_P
            beta = dV_dT / V_m  # 1/K

            # Calculate phase fractions
            mole_fraction = n_i / total_moles
            volume_i = n_i * V_m
            phase_volumes.append(volume_i)

            # Store phase data
            phases_data[phase_name] = {
                "mole_fraction": mole_fraction,
                "volume_fraction": None,  # Will calculate after all phases processed
                "composition": list(comp_i),
                "density": {"value": rho, "unit": "kg/m3"},
                "molecular_weight_kg_mol": {"value": mw, "unit": "kg/mol"},
                "molecular_weight_g_mol": {"value": mw * 1000, "unit": "g/mol"},
                "compressibility_factor": {"value": Z, "unit": "dimensionless"},
                "isothermal_compressibility_1_Pa": {"value": Cv_Pa, "unit": "1/Pa"},
                "isothermal_compressibility_1_bar": {"value": Cv_bar, "unit": "1/bar"},
                "thermal_expansion": {"value": beta, "unit": "1/K"},
                "molar_volume": {"value": V_m, "unit": "m3/mol"}
            }

            phase_densities.append(rho)

        # Calculate volume fractions
        total_volume = sum(phase_volumes)
        for i, phase_name in enumerate(phases_data.keys()):
            phases_data[phase_name]["volume_fraction"] = phase_volumes[i] / total_volume

        # Calculate bulk properties
        # Bulk density: volume-weighted average
        bulk_density = sum(
            (phase_volumes[i] / total_volume) * phase_densities[i]
            for i in range(len(phase_volumes))
        )

        # Bulk MW: mole-weighted average
        bulk_mw = sum(
            flash_result.moles_per_phase[i] / total_moles *
            phases_data[name]["molecular_weight_kg_mol"]["value"]
            for i, name in enumerate(phases_data.keys())
        )

        bulk_properties = {
            "density": {"value": bulk_density, "unit": "kg/m3"},
            "molecular_weight_kg_mol": {"value": bulk_mw, "unit": "kg/mol"},
            "molecular_weight_g_mol": {"value": bulk_mw * 1000, "unit": "g/mol"},
            "compressibility_factor": {
                "value": None,
                "reason": "No meaningful bulk Z for two-phase mixture"
            },
            "isothermal_compressibility": {
                "value": None,
                "reason": "Cv averaging depends on flow regime"
            },
            "thermal_expansion": {
                "value": None,
                "reason": "Beta averaging depends on flow regime"
            }
        }

        # Build base response
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
            "bulk": bulk_properties
        }

        # Check for near-critical conditions (within 10% density difference)
        if len(phase_densities) == 2:
            rho_min = min(phase_densities)
            rho_max = max(phase_densities)
            density_diff_pct = (rho_max - rho_min) / rho_max
            if density_diff_pct < 0.1:
                response["warning"] = (
                    f"Near-critical: phase densities within {density_diff_pct*100:.1f}% - "
                    f"phase distinction may be unreliable"
                )

        # Log and return
        logger.info(
            f"Multi-phase properties: {pressure} {pressure_unit}, {temperature} {temperature_unit} "
            f"-> {len(phases_data)} phases: {list(phases_data.keys())}"
        )
        return response
