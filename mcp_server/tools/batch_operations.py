"""
Batch Operations Tools - Execute multiple calculations efficiently in single calls.

Provides MCP tools for batch operations:
- batch_flash: Execute multiple PT or PH flash calculations with optional properties
- property_sweep: Calculate properties over a range (from Plan 11-01)

Reduces round-trip overhead for pipeline profiles, operating envelopes, and Monte Carlo studies.
"""

from typing import Optional, List, Dict, Any

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


# Universal gas constant
R_GAS = 8.314462618  # J/(mol·K)


# Property mapping: user-friendly names to calculation functions
PROPERTY_DEFINITIONS = {
    "density": {
        "calc": "single",
        "description": "Density (kg/m³)"
    },
    "Z": {
        "calc": "single",
        "description": "Compressibility factor (dimensionless)"
    },
    "compressibility": {
        "calc": "single",
        "description": "Isothermal compressibility (1/bar)"
    },
    "thermal_expansion": {
        "calc": "single",
        "description": "Thermal expansion coefficient (1/K)"
    },
    "viscosity": {
        "calc": "single",
        "description": "Viscosity (cP)"
    },
    "thermal_conductivity": {
        "calc": "single",
        "description": "Thermal conductivity (W/(m·K))"
    },
    "enthalpy": {
        "calc": "single",
        "description": "Molar enthalpy (J/mol)"
    },
    "entropy": {
        "calc": "single",
        "description": "Molar entropy (J/(mol·K))"
    },
    "heat_capacity": {
        "calc": "single",
        "description": "Isobaric heat capacity (J/(mol·K))"
    },
    "molar_volume": {
        "calc": "single",
        "description": "Molar volume (m³/mol)"
    },
    "molecular_weight": {
        "calc": "single",
        "description": "Molecular weight (kg/mol)"
    },
}


def calculate_properties_at_point(wrapper, P_pa, T_k, property_names, logger):
    """
    Calculate requested properties at a single P,T point.

    Returns dict with:
    - phase: Phase name (GAS, LIQUID1, etc.)
    - properties: Dict of property_name -> value
    - error: Error message if calculation failed (None if success)
    """
    try:
        # Execute flash
        flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
    except RuntimeError as e:
        return {
            "phase": None,
            "properties": {},
            "error": f"Flash failed: {e}"
        }

    # Check for single phase (batch operations only support single-phase for now)
    if flash_result.num_phases > 1:
        return {
            "phase": "MULTI_PHASE",
            "properties": {},
            "error": f"Multi-phase system ({flash_result.num_phases} phases). Batch operations support single-phase only."
        }

    phase_lno = flash_result.phases[0]
    phase_name = flash_result.phase_names[0]
    composition = flash_result.compositions[0]

    properties = {}

    # Get AYMIX properties (needed for most properties)
    try:
        aymix = wrapper.get_aymix_properties(
            phase_lno=phase_lno,
            temperature=T_k,
            pressure=P_pa,
            composition=composition,
            get_volume_derivs=True
        )
    except Exception as e:
        return {
            "phase": phase_name,
            "properties": {},
            "error": f"AYMIX calculation failed: {e}"
        }

    # Get molecular weight (used by multiple properties)
    try:
        mw = wrapper.get_molecular_weight(composition=composition)
    except Exception as e:
        return {
            "phase": phase_name,
            "properties": {},
            "error": f"MW calculation failed: {e}"
        }

    # Calculate each requested property
    for prop_name in property_names:
        try:
            if prop_name == "density":
                V_m = aymix.volume
                properties["density"] = mw / V_m

            elif prop_name == "Z":
                V_m = aymix.volume
                properties["Z"] = (P_pa * V_m) / (R_GAS * T_k)

            elif prop_name == "compressibility":
                V_m = aymix.volume
                dV_dP = aymix.volume_P
                Cv_Pa = -dV_dP / V_m
                properties["compressibility"] = Cv_Pa * 1e5  # Convert to 1/bar

            elif prop_name == "thermal_expansion":
                V_m = aymix.volume
                dV_dT = aymix.volume_T
                properties["thermal_expansion"] = dV_dT / V_m

            elif prop_name == "molar_volume":
                properties["molar_volume"] = aymix.volume

            elif prop_name == "molecular_weight":
                properties["molecular_weight"] = mw

            elif prop_name == "viscosity":
                visc_result = wrapper.get_viscosity(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=composition,
                    get_derivatives=False
                )
                properties["viscosity"] = visc_result.value * 1000.0  # Convert Pa.s to cP

            elif prop_name == "thermal_conductivity":
                cond_result = wrapper.get_thermal_conductivity(
                    phase_lno=phase_lno,
                    temperature=T_k,
                    pressure=P_pa,
                    composition=composition,
                    get_derivatives=False
                )
                properties["thermal_conductivity"] = cond_result.value

            elif prop_name == "enthalpy":
                properties["enthalpy"] = aymix.enthalpy

            elif prop_name == "entropy":
                properties["entropy"] = aymix.entropy

            elif prop_name == "heat_capacity":
                properties["heat_capacity"] = aymix.cp

            else:
                properties[prop_name] = None

        except Exception as e:
            logger.warning(f"Failed to calculate {prop_name} at P={P_pa} Pa, T={T_k} K: {e}")
            properties[prop_name] = None

    return {
        "phase": phase_name,
        "properties": properties,
        "error": None
    }


def detect_phase_transitions(results):
    """
    Detect phase transitions in sweep results.

    Returns list of transition dicts with:
    - from_phase: Phase before transition
    - to_phase: Phase after transition
    - index: Index where transition occurs
    """
    transitions = []

    for i in range(1, len(results)):
        prev_phase = results[i-1].get("phase")
        curr_phase = results[i].get("phase")

        if prev_phase and curr_phase and prev_phase != curr_phase:
            transitions.append({
                "from_phase": prev_phase,
                "to_phase": curr_phase,
                "index": i
            })

    return transitions


def register_batch_operations_tools(mcp_server, get_wrapper_fn, logger):
    """Register batch operations tools with the MCP server."""

    @mcp_server.tool()
    def batch_flash(
        flash_type: str,
        conditions: List[Dict[str, Any]],
        include_properties: Optional[List[str]] = None
    ) -> dict:
        """
        Execute multiple flash calculations (PT or PH) in a single call.

        Performs batch flash calculations at multiple conditions with optional
        property retrieval. Mixed success/failure handling allows partial results.
        Essential for:
        - Pipeline profile analysis (P, T at multiple locations)
        - Operating envelope mapping
        - Monte Carlo studies with varying conditions

        Args:
            flash_type: Flash type - "PT" (pressure-temperature) or "PH" (pressure-enthalpy)
            conditions: List of condition dictionaries (max 100)
                For PT flash:
                    {"pressure": float, "temperature": float,
                     "pressure_unit": "bar", "temperature_unit": "C"}
                For PH flash:
                    {"pressure": float, "enthalpy": float,
                     "pressure_unit": "bar", "enthalpy_unit": "J/mol"}
                Units are optional; defaults are bar and °C (PT) or J/mol (PH)
            include_properties: Optional list of property names to calculate at each point
                Options: "density", "viscosity", "compressibility_factor", "molar_volume",
                         "isothermal_compressibility", "thermal_expansion"

        Returns:
            Dict with batch results:
            {
                "flash_type": str,
                "num_points": int,
                "num_successful": int,
                "num_failed": int,
                "default_units": {...},
                "results": [
                    {
                        "index": int,
                        "input": {...},
                        "status": "success" | "failed",
                        "conditions_si": {...},
                        "result": {...},  # For PH flash: calculated T
                        "num_phases": int,
                        "phases": [...],
                        "properties": {...}  # if include_properties
                    },
                    ...
                ],
                "summary": {
                    "single_phase_gas": int,
                    "single_phase_liquid": int,
                    "two_phase": int,
                    "failed": int
                },
                "failed_indices": [int, ...]
            }

        Error codes:
            INVALID_INPUT: Bad flash_type, >100 conditions, malformed condition dict
            NO_FLUID_LOADED: No fluid loaded
            PH_FLASH_NOT_AVAILABLE: PH flash requires Phase 10 completion
        """
        # Input validation
        if flash_type not in ["PT", "PH"]:
            raise MCPError(
                "INVALID_INPUT",
                f"flash_type must be 'PT' or 'PH', got '{flash_type}'"
            )

        if not isinstance(conditions, list) or len(conditions) == 0:
            raise MCPError(
                "INVALID_INPUT",
                "conditions must be a non-empty list"
            )

        if len(conditions) > 100:
            raise MCPError(
                "INVALID_INPUT",
                f"Maximum 100 conditions allowed, got {len(conditions)}"
            )

        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file or load_mfl_text first."
            )

        # Check PH flash availability
        if flash_type == "PH" and not hasattr(wrapper, 'ph_flash'):
            raise MCPError(
                "PH_FLASH_NOT_AVAILABLE",
                "PH flash requires Phase 10 (ph_flash tool). "
                "Ensure Phase 10 is complete before using batch PH flash."
            )

        # Default units
        default_units = {
            "pressure": "bar",
            "temperature": "C",
            "enthalpy": "J/mol"
        }

        # Execute flash for each condition
        results = []
        failed_indices = []
        num_failed = 0

        # Summary counters
        single_phase_gas = 0
        single_phase_liquid = 0
        two_phase = 0

        for idx, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                results.append({
                    "index": idx,
                    "status": "failed",
                    "error": "Condition must be a dictionary"
                })
                failed_indices.append(idx)
                num_failed += 1
                continue

            try:
                # Parse condition with defaults
                if flash_type == "PT":
                    pressure = condition.get("pressure")
                    temperature = condition.get("temperature")
                    pressure_unit = condition.get("pressure_unit", default_units["pressure"])
                    temperature_unit = condition.get("temperature_unit", default_units["temperature"])

                    if pressure is None or temperature is None:
                        raise ValueError("PT flash requires 'pressure' and 'temperature' fields")

                    # Validate and convert to SI
                    validate_pressure(pressure, pressure_unit)
                    validate_temperature(temperature, temperature_unit)
                    P_pa = convert_pressure_to_pa(pressure, pressure_unit)
                    T_k = convert_temperature_to_k(temperature, temperature_unit)

                    # Execute PT flash
                    flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)

                    # Build result entry
                    result_entry = {
                        "index": idx,
                        "input": {
                            "pressure": pressure,
                            "pressure_unit": pressure_unit,
                            "temperature": temperature,
                            "temperature_unit": temperature_unit
                        },
                        "status": "success",
                        "conditions_si": {
                            "pressure_Pa": P_pa,
                            "temperature_K": T_k
                        }
                    }

                elif flash_type == "PH":
                    pressure = condition.get("pressure")
                    enthalpy = condition.get("enthalpy")
                    pressure_unit = condition.get("pressure_unit", default_units["pressure"])
                    enthalpy_unit = condition.get("enthalpy_unit", default_units["enthalpy"])

                    if pressure is None or enthalpy is None:
                        raise ValueError("PH flash requires 'pressure' and 'enthalpy' fields")

                    # Validate and convert pressure to SI
                    validate_pressure(pressure, pressure_unit)
                    P_pa = convert_pressure_to_pa(pressure, pressure_unit)

                    # Convert enthalpy - need MW for mass-based units
                    validate_enthalpy(enthalpy, enthalpy_unit)
                    unit_lower = enthalpy_unit.lower().replace('_', '/').replace(' ', '')

                    if '/kg' in unit_lower:
                        # Mass-based unit - get MW from wrapper
                        mw = wrapper.get_molecular_weight()  # kg/mol
                        H_j_mol = convert_enthalpy_to_j_mol(enthalpy, enthalpy_unit, mw)
                    else:
                        # Molar unit - direct conversion
                        H_j_mol = convert_enthalpy_to_j_mol(enthalpy, enthalpy_unit)

                    # Execute PH flash
                    flash_result = wrapper.ph_flash(pressure=P_pa, enthalpy=H_j_mol)

                    # Build result entry
                    result_entry = {
                        "index": idx,
                        "input": {
                            "pressure": pressure,
                            "pressure_unit": pressure_unit,
                            "enthalpy": enthalpy,
                            "enthalpy_unit": enthalpy_unit
                        },
                        "status": "success",
                        "conditions_si": {
                            "pressure_Pa": P_pa,
                            "enthalpy_J_mol": H_j_mol
                        },
                        "result": {
                            "temperature_K": flash_result.temperature,
                            "temperature_C": flash_result.temperature - 273.15
                        }
                    }

                # Calculate phase fractions
                total_moles = sum(flash_result.moles_per_phase)
                if total_moles == 0:
                    raise RuntimeError("Flash returned zero total moles")

                phases = []
                for phase_name, moles in zip(flash_result.phase_names, flash_result.moles_per_phase):
                    mole_fraction = moles / total_moles
                    phases.append({
                        "name": phase_name,
                        "mole_fraction": mole_fraction,
                        "moles": moles
                    })

                result_entry["num_phases"] = flash_result.num_phases
                result_entry["phases"] = phases

                # Update summary counters
                if flash_result.num_phases == 1:
                    phase_name_upper = flash_result.phase_names[0].upper()
                    if "GAS" in phase_name_upper:
                        single_phase_gas += 1
                    elif "LIQUID" in phase_name_upper:
                        single_phase_liquid += 1
                elif flash_result.num_phases > 1:
                    two_phase += 1

                # Get optional properties if requested
                if include_properties:
                    try:
                        # For single-phase only (multi-phase property calculation is complex)
                        if flash_result.num_phases == 1:
                            phase_lno = flash_result.phases[0]
                            composition = flash_result.compositions[0]

                            # Get properties at this condition
                            if flash_type == "PT":
                                props = wrapper.get_aymix_properties(
                                    phase_lno=phase_lno,
                                    temperature=T_k,
                                    pressure=P_pa,
                                    composition=composition,
                                    get_volume_derivs=True
                                )
                            else:
                                # For PH flash, use calculated temperature
                                props = wrapper.get_aymix_properties(
                                    phase_lno=phase_lno,
                                    temperature=flash_result.temperature,
                                    pressure=P_pa,
                                    composition=composition,
                                    get_volume_derivs=True
                                )

                            properties_dict = {}
                            for prop_name in include_properties:
                                prop_lower = prop_name.lower()
                                if prop_lower == "density":
                                    # Calculate density from MW and molar volume
                                    mw = wrapper.get_molecular_weight(composition=composition)
                                    density = mw / props.volume
                                    properties_dict["density"] = {
                                        "value": density,
                                        "unit": "kg/m3"
                                    }
                                elif prop_lower == "viscosity":
                                    visc = wrapper.get_viscosity(
                                        phase_lno=phase_lno,
                                        temperature=T_k if flash_type == "PT" else flash_result.temperature,
                                        pressure=P_pa,
                                        composition=composition,
                                        get_derivatives=False
                                    )
                                    properties_dict["viscosity"] = {
                                        "value": visc.value,
                                        "unit": "Pa.s"
                                    }
                                elif prop_lower == "compressibility_factor":
                                    # Calculate Z = PV/(RT)
                                    R_GAS = 8.314462618  # J/(mol·K)
                                    T_for_calc = T_k if flash_type == "PT" else flash_result.temperature
                                    Z = (P_pa * props.volume) / (R_GAS * T_for_calc)
                                    properties_dict["compressibility_factor"] = {
                                        "value": Z,
                                        "unit": "dimensionless"
                                    }
                                elif prop_lower == "molar_volume":
                                    properties_dict["molar_volume"] = {
                                        "value": props.volume,
                                        "unit": "m3/mol"
                                    }
                                elif prop_lower == "isothermal_compressibility":
                                    # Cv = -1/V * dV/dP
                                    Cv = -props.volume_P / props.volume
                                    properties_dict["isothermal_compressibility"] = {
                                        "value": Cv,
                                        "unit": "1/Pa"
                                    }
                                elif prop_lower == "thermal_expansion":
                                    # beta = 1/V * dV/dT
                                    beta = props.volume_T / props.volume
                                    properties_dict["thermal_expansion"] = {
                                        "value": beta,
                                        "unit": "1/K"
                                    }

                            result_entry["properties"] = properties_dict
                        else:
                            # Multi-phase system - skip properties
                            logger.warning(f"Skipping properties for multi-phase system at index {idx}")
                    except Exception as e:
                        logger.warning(f"Failed to get properties at index {idx}: {e}")
                        # Continue without properties - flash succeeded

                results.append(result_entry)

            except Exception as e:
                # Record failure but continue
                results.append({
                    "index": idx,
                    "input": condition,
                    "status": "failed",
                    "error": str(e)
                })
                failed_indices.append(idx)
                num_failed += 1

        # Build response
        response = {
            "flash_type": flash_type,
            "num_points": len(conditions),
            "num_successful": len(conditions) - num_failed,
            "num_failed": num_failed,
            "default_units": default_units,
            "results": results,
            "summary": {
                "single_phase_gas": single_phase_gas,
                "single_phase_liquid": single_phase_liquid,
                "two_phase": two_phase,
                "failed": num_failed
            },
            "failed_indices": failed_indices
        }

        # Log completion
        logger.info(
            f"Batch {flash_type} flash: {len(conditions)} points, "
            f"{response['num_successful']} successful, {num_failed} failed"
        )

        return response

    @mcp_server.tool()
    def property_sweep(
        properties: List[str],
        sweep_variable: str,
        sweep_start: float,
        sweep_end: float,
        fixed_variable: str,
        fixed_value: float,
        num_points: int = 20,
        sweep_unit: str = "bar",
        fixed_unit: str = "C"
    ) -> dict:
        """
        Calculate multiple properties over a pressure or temperature sweep.

        Performs flash calculations at evenly-spaced points along pressure or
        temperature axis and returns tabular data with phase information and
        requested properties. Automatically detects phase transitions.

        Essential for:
        - PVT table generation
        - Phase envelope visualization
        - Sensitivity analysis
        - Property trend analysis

        Args:
            properties: List of property names to calculate.
                Available: density, Z, compressibility, thermal_expansion,
                viscosity, thermal_conductivity, enthalpy, entropy,
                heat_capacity, molar_volume, molecular_weight
            sweep_variable: Variable to sweep ("pressure" or "temperature")
            sweep_start: Starting value for sweep variable
            sweep_end: Ending value for sweep variable
            fixed_variable: Variable to hold constant ("pressure" or "temperature")
            fixed_value: Value of fixed variable
            num_points: Number of sweep points (default: 20, max: 100)
            sweep_unit: Unit for sweep variable (default: "bar" for P, "C" for T)
            fixed_unit: Unit for fixed variable (default: "bar" for P, "C" for T)

        Returns:
            Dict with sweep results:
            {
                "input": {
                    "properties": List[str],
                    "sweep_variable": str,
                    "sweep_range": {"start": float, "end": float, "unit": str},
                    "fixed_variable": str,
                    "fixed_value": {"value": float, "unit": str},
                    "num_points": int
                },
                "phase_transitions": [
                    {
                        "from_phase": str,
                        "to_phase": str,
                        "sweep_value": float,
                        "approximate_location": str
                    }
                ],
                "data": [
                    {
                        "point": int,
                        "sweep_value": float,
                        "phase": str,
                        "properties": {
                            "density": float,
                            "Z": float,
                            ...
                        }
                    },
                    ...
                ]
            }

        Error codes:
            INVALID_INPUT: Bad unit, negative pressure, T < 0K, invalid property name,
                          invalid sweep/fixed variable combination, or num_points > 100
            NO_FLUID_LOADED: No fluid loaded via load_mfl_file or load_mfl_text

        Examples:
            >>> # Density vs pressure at 40C
            >>> property_sweep(
            ...     properties=["density", "Z"],
            ...     sweep_variable="pressure",
            ...     sweep_start=10,
            ...     sweep_end=150,
            ...     fixed_variable="temperature",
            ...     fixed_value=40,
            ...     num_points=50
            ... )

            >>> # Viscosity vs temperature at 50 bar
            >>> property_sweep(
            ...     properties=["viscosity", "thermal_conductivity"],
            ...     sweep_variable="temperature",
            ...     sweep_start=0,
            ...     sweep_end=100,
            ...     fixed_variable="pressure",
            ...     fixed_value=50,
            ...     num_points=30
            ... )
        """
        # Validate inputs
        sweep_variable = sweep_variable.lower().strip()
        fixed_variable = fixed_variable.lower().strip()

        if sweep_variable not in ["pressure", "temperature"]:
            raise MCPError(
                "INVALID_INPUT",
                f"sweep_variable must be 'pressure' or 'temperature', got '{sweep_variable}'"
            )

        if fixed_variable not in ["pressure", "temperature"]:
            raise MCPError(
                "INVALID_INPUT",
                f"fixed_variable must be 'pressure' or 'temperature', got '{fixed_variable}'"
            )

        if sweep_variable == fixed_variable:
            raise MCPError(
                "INVALID_INPUT",
                "sweep_variable and fixed_variable cannot be the same"
            )

        if num_points < 2:
            raise MCPError(
                "INVALID_INPUT",
                f"num_points must be at least 2, got {num_points}"
            )

        if num_points > 100:
            raise MCPError(
                "INVALID_INPUT",
                f"num_points cannot exceed 100 (got {num_points}). Use multiple sweeps if needed."
            )

        # Validate property names
        invalid_props = [p for p in properties if p not in PROPERTY_DEFINITIONS]
        if invalid_props:
            raise MCPError(
                "INVALID_INPUT",
                f"Unknown properties: {invalid_props}. "
                f"Available: {list(PROPERTY_DEFINITIONS.keys())}"
            )

        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file or load_mfl_text first."
            )

        # Convert fixed variable to SI
        try:
            if fixed_variable == "pressure":
                validate_pressure(fixed_value, fixed_unit)
                fixed_si = convert_pressure_to_pa(fixed_value, fixed_unit)
            else:  # temperature
                validate_temperature(fixed_value, fixed_unit)
                fixed_si = convert_temperature_to_k(fixed_value, fixed_unit)
        except ValueError as e:
            raise MCPError("INVALID_INPUT", f"Fixed variable validation failed: {e}")

        # Generate sweep points
        sweep_points = []
        for i in range(num_points):
            frac = i / (num_points - 1) if num_points > 1 else 0
            sweep_val = sweep_start + frac * (sweep_end - sweep_start)
            sweep_points.append(sweep_val)

        # Convert sweep points to SI and validate
        sweep_points_si = []
        try:
            if sweep_variable == "pressure":
                for p in sweep_points:
                    validate_pressure(p, sweep_unit)
                    sweep_points_si.append(convert_pressure_to_pa(p, sweep_unit))
            else:  # temperature
                for t in sweep_points:
                    validate_temperature(t, sweep_unit)
                    sweep_points_si.append(convert_temperature_to_k(t, sweep_unit))
        except ValueError as e:
            raise MCPError("INVALID_INPUT", f"Sweep point validation failed: {e}")

        # Execute sweep
        results = []
        for i, (sweep_val, sweep_si) in enumerate(zip(sweep_points, sweep_points_si)):
            # Determine P and T for this point
            if sweep_variable == "pressure":
                P_pa = sweep_si
                T_k = fixed_si
            else:  # temperature
                P_pa = fixed_si
                T_k = sweep_si

            # Calculate properties
            result = calculate_properties_at_point(wrapper, P_pa, T_k, properties, logger)

            # Build data point
            data_point = {
                "point": i + 1,
                "sweep_value": sweep_val,
                "phase": result["phase"],
                "properties": result["properties"]
            }

            if result["error"]:
                data_point["error"] = result["error"]

            results.append(data_point)

        # Detect phase transitions
        transitions_raw = detect_phase_transitions(results)
        transitions = []
        for trans in transitions_raw:
            idx = trans["index"]
            sweep_val = results[idx]["sweep_value"]
            transitions.append({
                "from_phase": trans["from_phase"],
                "to_phase": trans["to_phase"],
                "sweep_value": sweep_val,
                "approximate_location": f"Between points {idx} and {idx+1}"
            })

        # Build response
        response = {
            "input": {
                "properties": properties,
                "sweep_variable": sweep_variable,
                "sweep_range": {
                    "start": sweep_start,
                    "end": sweep_end,
                    "unit": sweep_unit
                },
                "fixed_variable": fixed_variable,
                "fixed_value": {
                    "value": fixed_value,
                    "unit": fixed_unit
                },
                "num_points": num_points
            },
            "phase_transitions": transitions,
            "data": results
        }

        logger.info(
            f"Property sweep: {sweep_variable} {sweep_start}->{sweep_end} {sweep_unit} "
            f"at {fixed_variable}={fixed_value} {fixed_unit}, "
            f"{num_points} points, {len(transitions)} transitions detected"
        )

        return response
