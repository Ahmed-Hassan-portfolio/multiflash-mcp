"""
Phase Boundary Tools - Saturation, bubble point, and dew point calculations.

Provides MCP tools for phase boundary queries:
- get_saturation_pressure: Find pressure at which fluid vaporizes at given temperature
- get_saturation_temperature: Find temperature at which fluid vaporizes at given pressure
- bubble_point: Find bubble point pressure or temperature (incipient vaporization)
- dew_point: Find dew point pressure or temperature (incipient condensation)

These tools are fundamental for phase determination, safety relief sizing, and process design.
Essential for understanding where phase transitions occur in CO2 systems.
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

# CO2 critical point constants (for validation)
CO2_TC_K = 304.13  # K
CO2_PC_PA = 7.377e6  # Pa (73.77 bar)
CO2_TRIPLE_T_K = 216.55  # K (~-56.6°C)
CO2_TRIPLE_P_PA = 5.18e5  # Pa (~5.18 bar)


def register_phase_boundary_tools(mcp_server, get_wrapper_fn, logger):
    """Register phase boundary tools with the MCP server."""

    def _estimate_critical_point(wrapper, logger):
        """
        Estimate critical point by finding where bubble and dew pressures converge.

        Uses binary search to find the temperature where the two-phase region disappears.
        This works when AXCRIT fails for certain EOS (GERG/CG).

        Returns:
            Tuple of (Tc_K, Pc_Pa)
        """
        # Start with reasonable bounds for CO2-rich mixtures
        T_low = 250.0  # K (~-23°C)
        T_high = 350.0  # K (~77°C) - well above CO2 critical

        P_search_low = 1e5  # 1 bar
        P_search_high = 150e5  # 150 bar

        tolerance = 0.5  # K
        max_iterations = 30

        def get_envelope_width(T_k):
            """Get pressure difference between bubble and dew at temperature T."""
            try:
                # Find bubble point (high P edge of two-phase)
                P_lo, P_hi = P_search_low, P_search_high
                P_bubble = None
                for _ in range(25):
                    P_mid = (P_lo + P_hi) / 2
                    flash = wrapper.pt_flash(temperature=T_k, pressure=P_mid)
                    if flash.num_phases == 2:
                        total = sum(flash.moles_per_phase)
                        vap = sum(m for n, m in zip(flash.phase_names, flash.moles_per_phase) if "GAS" in n.upper())
                        vf = vap / total if total > 0 else 0
                        if vf > 0.01:
                            P_lo = P_mid
                        else:
                            P_bubble = P_mid
                            P_hi = P_mid
                    elif flash.num_phases == 1:
                        if "LIQUID" in flash.phase_names[0].upper():
                            P_hi = P_mid
                        else:
                            P_lo = P_mid
                    if abs(P_hi - P_lo) < 5e3:
                        break
                if P_bubble is None:
                    P_bubble = (P_hi + P_lo) / 2

                # Find dew point (low P edge of two-phase)
                P_lo, P_hi = P_search_low, P_search_high
                P_dew = None
                for _ in range(25):
                    P_mid = (P_lo + P_hi) / 2
                    flash = wrapper.pt_flash(temperature=T_k, pressure=P_mid)
                    if flash.num_phases == 2:
                        total = sum(flash.moles_per_phase)
                        liq = sum(m for n, m in zip(flash.phase_names, flash.moles_per_phase) if "LIQUID" in n.upper())
                        lf = liq / total if total > 0 else 0
                        if lf > 0.01:
                            P_hi = P_mid
                        else:
                            P_dew = P_mid
                            P_lo = P_mid
                    elif flash.num_phases == 1:
                        if "GAS" in flash.phase_names[0].upper():
                            P_lo = P_mid
                        else:
                            P_hi = P_mid
                    if abs(P_hi - P_lo) < 5e3:
                        break
                if P_dew is None:
                    P_dew = (P_hi + P_lo) / 2

                return P_bubble - P_dew, P_bubble, P_dew
            except:
                return None, None, None

        # Binary search for temperature where envelope width approaches zero
        Tc_estimate = None
        Pc_estimate = None

        for _ in range(max_iterations):
            T_mid = (T_low + T_high) / 2
            width, P_b, P_d = get_envelope_width(T_mid)

            if width is None:
                # Calculation failed, narrow from high side
                T_high = T_mid
                continue

            logger.debug(f"T={T_mid-273.15:.1f}°C: width={width/1e5:.2f} bar, Pb={P_b/1e5:.1f}, Pd={P_d/1e5:.1f}")

            if width < 0.5e5:  # Less than 0.5 bar difference - close to critical
                Tc_estimate = T_mid
                Pc_estimate = (P_b + P_d) / 2
                T_high = T_mid  # Keep searching for more precise value
            elif width > 0:
                T_low = T_mid  # Two-phase exists, critical is higher
            else:
                T_high = T_mid

            if abs(T_high - T_low) < tolerance:
                break

        if Tc_estimate is None:
            # Fallback to CO2 defaults if estimation failed
            logger.warning("Critical point estimation failed, using CO2 defaults")
            return 304.13, 73.77e5

        return Tc_estimate, Pc_estimate

    @mcp_server.tool()
    def get_saturation_pressure(
        temperature: float,
        temperature_unit: str = "C"
    ) -> dict:
        """
        Get saturation pressure at a given temperature.

        Finds the pressure at which liquid and vapor coexist (vapor pressure for pure
        components, bubble point pressure for mixtures). This is the pressure at which
        the first bubble of vapor forms when heating a liquid, or the pressure at which
        vapor fully condenses when cooling.

        Essential for:
        - Phase determination: Is fluid liquid or vapor at given P, T?
        - Safety relief sizing: At what pressure will a liquid tank vent?
        - Process design: Operating margin away from phase transition

        Args:
            temperature: Temperature at which to find saturation pressure
            temperature_unit: Temperature unit (default: "C")
                Supported: K (Kelvin), C (Celsius)

        Returns:
            Dict with saturation pressure in multiple units:
            {
                "input": {
                    "temperature": float,
                    "temperature_unit": str
                },
                "temperature_K": float,
                "saturation_pressure": {
                    "value_Pa": float,
                    "value_bar": float,
                    "value_MPa": float,
                    "value_psi": float
                },
                "is_pure_component": bool,
                "calculation_type": str  # "vapor_pressure" or "bubble_pressure"
            }

        Error codes:
            INVALID_INPUT: Bad unit or T < 0K
            NO_FLUID_LOADED: No fluid loaded via load_mfl_file
            ABOVE_CRITICAL: Temperature exceeds critical temperature
            BELOW_TRIPLE_POINT: Temperature below triple point
            SATURATION_CALC_FAILED: Calculation failed

        Examples:
            >>> get_saturation_pressure(temperature=0, temperature_unit="C")
            # Returns: ~34.85 bar for pure CO2

            >>> get_saturation_pressure(temperature=30, temperature_unit="C")
            # Returns: ~72 bar (approaching critical point at 31°C)

        Reference for Pure CO2:
            T (°C)  | Psat (bar)
            --------|------------
            -40     | 10.05
            -20     | 19.70
            0       | 34.85
            10      | 45.02
            20      | 57.29
            31.0    | 73.77 (critical)
        """
        # Validate and convert units
        try:
            validate_temperature(temperature, temperature_unit)
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
                "No fluid loaded. Use load_mfl_file first."
            )

        # Check if temperature is above critical point
        # For now, use CO2 critical point as reference
        # TODO: Get critical point from wrapper for mixtures
        if T_k > CO2_TC_K:
            raise MCPError(
                "ABOVE_CRITICAL",
                f"Temperature {temperature} {temperature_unit} ({T_k:.2f} K) exceeds "
                f"critical temperature (~{CO2_TC_K:.2f} K for CO2). "
                f"No saturation pressure exists above critical temperature."
            )

        # Check if below triple point
        if T_k < CO2_TRIPLE_T_K:
            raise MCPError(
                "BELOW_TRIPLE_POINT",
                f"Temperature {temperature} {temperature_unit} ({T_k:.2f} K) is below "
                f"triple point (~{CO2_TRIPLE_T_K:.2f} K for CO2). "
                f"Solid phase may form at these conditions."
            )

        # Calculate saturation pressure
        # For now, we need to implement this in the wrapper
        # Use iterative approach: find P where we have two phases at equilibrium
        try:
            # Method: Binary search for pressure where we transition from 1 to 2 phases
            # Start with reasonable bounds for CO2
            P_low = 1e5  # 1 bar
            P_high = min(CO2_PC_PA * 0.99, 1e8)  # Just below critical, max 1000 bar

            # Binary search for saturation pressure
            max_iterations = 30
            tolerance = 1e3  # 1 kPa tolerance in Pa

            for _ in range(max_iterations):
                P_mid = (P_low + P_high) / 2

                # Flash at this pressure
                flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_mid)

                if flash_result.num_phases == 2:
                    # Two-phase: we're at saturation, save and continue narrowing
                    P_sat = P_mid
                    # Narrow the search range but keep exploring
                    if P_mid - P_low > P_high - P_mid:
                        P_low = P_mid - (P_mid - P_low) / 2
                    else:
                        P_high = P_mid + (P_high - P_mid) / 2
                elif flash_result.num_phases == 1:
                    # Single phase - determine if above or below saturation
                    phase_name = flash_result.phase_names[0]
                    if "LIQUID" in phase_name.upper():
                        # Liquid at P_mid: P_mid > P_sat, so P_sat is lower
                        P_high = P_mid
                    else:
                        # Gas at P_mid: P_mid < P_sat, so P_sat is higher
                        P_low = P_mid

                # Check convergence
                if abs(P_high - P_low) < tolerance:
                    P_sat = (P_high + P_low) / 2
                    break
            else:
                raise MCPError(
                    "SATURATION_CALC_FAILED",
                    f"Binary search did not converge after {max_iterations} iterations"
                )

        except MCPError:
            raise  # Re-raise our own errors
        except Exception as e:
            raise MCPError(
                "SATURATION_CALC_FAILED",
                f"Saturation pressure calculation failed: {e}"
            )

        # Determine if pure component (single component in composition)
        is_pure = len([x for x in wrapper.composition if x > 0]) == 1
        calc_type = "vapor_pressure" if is_pure else "bubble_pressure"

        # Convert to multiple pressure units
        P_bar = P_sat / 1e5
        P_MPa = P_sat / 1e6
        P_psi = P_sat / 6894.757

        # Build response structure
        response = {
            "input": {
                "temperature": temperature,
                "temperature_unit": temperature_unit
            },
            "temperature_K": T_k,
            "saturation_pressure": {
                "value_Pa": P_sat,
                "value_bar": P_bar,
                "value_MPa": P_MPa,
                "value_psi": P_psi
            },
            "is_pure_component": is_pure,
            "calculation_type": calc_type
        }

        # Log and return
        logger.info(
            f"Saturation pressure at {temperature} {temperature_unit}: "
            f"{P_bar:.2f} bar ({calc_type})"
        )
        return response

    @mcp_server.tool()
    def get_saturation_temperature(
        pressure: float,
        pressure_unit: str = "bar"
    ) -> dict:
        """
        Get saturation temperature at a given pressure.

        Finds the temperature at which liquid and vapor coexist (boiling point for pure
        components). This is the temperature at which liquid starts to vaporize, or at
        which vapor fully condenses.

        Essential for:
        - Heat exchanger design: Pinch analysis around phase change
        - Vessel design: What temperature corresponds to design pressure?
        - Refrigeration cycles: Evaporator/condenser temperatures

        Args:
            pressure: Pressure at which to find saturation temperature
            pressure_unit: Pressure unit (default: "bar")
                Supported: bar, Pa, kPa, MPa, psi, atm

        Returns:
            Dict with saturation temperature:
            {
                "input": {
                    "pressure": float,
                    "pressure_unit": str
                },
                "pressure_Pa": float,
                "saturation_temperature": {
                    "value_K": float,
                    "value_C": float
                },
                "is_pure_component": bool,
                "calculation_type": str
            }

        Error codes:
            INVALID_INPUT: Bad unit or negative pressure
            NO_FLUID_LOADED: No fluid loaded
            ABOVE_CRITICAL: Pressure exceeds critical pressure
            BELOW_TRIPLE_POINT: Pressure below triple point
            SATURATION_CALC_FAILED: Calculation failed

        Examples:
            >>> get_saturation_temperature(pressure=50, pressure_unit="bar")
            # Returns: ~14°C for pure CO2

            >>> get_saturation_temperature(pressure=1, pressure_unit="atm")
            # Returns: Below triple point for CO2 (sublimation at -78.5°C)
        """
        # Validate and convert units
        try:
            validate_pressure(pressure, pressure_unit)
            P_pa = convert_pressure_to_pa(pressure, pressure_unit)
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
                "No fluid loaded. Use load_mfl_file first."
            )

        # Check if pressure is above critical point
        if P_pa > CO2_PC_PA:
            raise MCPError(
                "ABOVE_CRITICAL",
                f"Pressure {pressure} {pressure_unit} ({P_pa/1e5:.2f} bar) exceeds "
                f"critical pressure (~{CO2_PC_PA/1e5:.2f} bar for CO2). "
                f"No saturation temperature exists above critical pressure."
            )

        # Check if below triple point
        if P_pa < CO2_TRIPLE_P_PA:
            raise MCPError(
                "BELOW_TRIPLE_POINT",
                f"Pressure {pressure} {pressure_unit} ({P_pa/1e5:.2f} bar) is below "
                f"triple point (~{CO2_TRIPLE_P_PA/1e5:.2f} bar for CO2). "
                f"Solid phase may form at these conditions."
            )

        # Calculate saturation temperature
        # Binary search for temperature where we have two phases
        try:
            # Start with reasonable bounds for CO2
            T_low = CO2_TRIPLE_T_K + 5  # Just above triple point
            T_high = CO2_TC_K - 0.5  # Just below critical

            # Binary search for saturation temperature
            max_iterations = 30
            tolerance = 0.01  # 0.01 K tolerance

            for _ in range(max_iterations):
                T_mid = (T_low + T_high) / 2

                # Flash at this temperature
                flash_result = wrapper.pt_flash(temperature=T_mid, pressure=P_pa)

                if flash_result.num_phases == 2:
                    # Two-phase: we're at saturation
                    T_sat = T_mid
                    # Narrow search range but keep exploring
                    if T_mid - T_low > T_high - T_mid:
                        T_low = T_mid - (T_mid - T_low) / 2
                    else:
                        T_high = T_mid + (T_high - T_mid) / 2
                elif flash_result.num_phases == 1:
                    # Single phase - determine if above or below saturation
                    phase_name = flash_result.phase_names[0]
                    if "LIQUID" in phase_name.upper():
                        # Liquid phase at T_mid: T_mid < T_sat, so T_sat is higher
                        T_low = T_mid
                    else:
                        # Gas phase at T_mid: T_mid > T_sat, so T_sat is lower
                        T_high = T_mid

                # Check convergence
                if abs(T_high - T_low) < tolerance:
                    T_sat = (T_high + T_low) / 2
                    break
            else:
                raise MCPError(
                    "SATURATION_CALC_FAILED",
                    f"Binary search did not converge after {max_iterations} iterations"
                )

        except MCPError:
            raise  # Re-raise our own errors
        except Exception as e:
            raise MCPError(
                "SATURATION_CALC_FAILED",
                f"Saturation temperature calculation failed: {e}"
            )

        # Determine if pure component
        is_pure = len([x for x in wrapper.composition if x > 0]) == 1
        calc_type = "vapor_pressure" if is_pure else "bubble_pressure"

        # Convert to Celsius
        T_c = T_sat - 273.15

        # Build response structure
        response = {
            "input": {
                "pressure": pressure,
                "pressure_unit": pressure_unit
            },
            "pressure_Pa": P_pa,
            "saturation_temperature": {
                "value_K": T_sat,
                "value_C": T_c
            },
            "is_pure_component": is_pure,
            "calculation_type": calc_type
        }

        # Log and return
        logger.info(
            f"Saturation temperature at {pressure} {pressure_unit}: "
            f"{T_c:.2f} °C ({calc_type})"
        )
        return response

    @mcp_server.tool()
    def get_critical_point() -> dict:
        """
        Get the critical point properties for the loaded fluid.

        Returns critical temperature, pressure, density, molar volume, and
        compressibility factor for the loaded fluid. Works for both pure
        components and mixtures (mixture critical point calculation).

        The critical point is where liquid and vapor phases become
        indistinguishable. Above Tc and Pc, the fluid is supercritical.
        For CO2, Tc=304.13K (31°C) and Pc=73.77 bar are relatively low,
        often encountered in process conditions.

        Args:
            None (uses loaded fluid)

        Returns:
            Dict with critical properties:
            {
                "fluid_name": str,
                "fluid_type": str,  # "pure" or "mixture"
                "num_components": int,
                "critical_temperature": {
                    "value_K": float,
                    "value_C": float
                },
                "critical_pressure": {
                    "value_Pa": float,
                    "value_bar": float,
                    "value_MPa": float
                },
                "critical_density": {
                    "value_kg_m3": float,
                    "value_mol_m3": float
                },
                "critical_molar_volume": {
                    "value_m3_mol": float,
                    "value_cm3_mol": float
                },
                "critical_compressibility_factor": float  # Zc = Pc*Vc/(R*Tc)
            }

        Error codes:
            NO_FLUID_LOADED: No fluid loaded
            CRITICAL_CALC_FAILED: Could not determine critical point

        Examples:
            >>> get_critical_point()
            # For pure CO2: Tc=304.13K, Pc=73.77bar, rhoc=467.6 kg/m3, Zc=0.274
        """
        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise  # Re-raise DLL connection errors as-is

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file or create_fluid_mixture first."
            )

        # Get fluid info
        num_components = len(wrapper.composition)
        fluid_type = "pure" if num_components == 1 else "mixture"
        fluid_name = wrapper.fluid_name if wrapper.fluid_name else "unknown"

        # Call wrapper critical point method
        try:
            Tc_K, Pc_Pa, Vc_m3_mol = wrapper.get_critical_point()
        except RuntimeError as e:
            raise MCPError(
                "CRITICAL_CALC_FAILED",
                f"Critical point calculation failed: {e}"
            )

        # Get molecular weight for density calculation
        try:
            MW_kg_mol = wrapper.get_molecular_weight()
        except RuntimeError as e:
            raise MCPError(
                "CRITICAL_CALC_FAILED",
                f"Could not get molecular weight: {e}"
            )

        # Calculate derived properties
        # Density: rhoc = MW / Vc
        rhoc_kg_m3 = MW_kg_mol / Vc_m3_mol
        rhoc_mol_m3 = 1.0 / Vc_m3_mol

        # Compressibility factor: Zc = Pc * Vc / (R * Tc)
        Zc = (Pc_Pa * Vc_m3_mol) / (R_GAS * Tc_K)

        # Build response with all units
        result = {
            "fluid_name": fluid_name,
            "fluid_type": fluid_type,
            "num_components": num_components,
            "critical_temperature": {
                "value_K": Tc_K,
                "value_C": Tc_K - 273.15
            },
            "critical_pressure": {
                "value_Pa": Pc_Pa,
                "value_bar": Pc_Pa / 1e5,
                "value_MPa": Pc_Pa / 1e6
            },
            "critical_density": {
                "value_kg_m3": rhoc_kg_m3,
                "value_mol_m3": rhoc_mol_m3
            },
            "critical_molar_volume": {
                "value_m3_mol": Vc_m3_mol,
                "value_cm3_mol": Vc_m3_mol * 1e6
            },
            "critical_compressibility_factor": Zc
        }

        # Log and return
        logger.info(
            f"Critical point for {fluid_name}: "
            f"Tc={Tc_K:.2f} K, Pc={Pc_Pa/1e5:.2f} bar, Zc={Zc:.4f}"
        )
        return result

    @mcp_server.tool()
    def bubble_point(
        specification: str,
        value: float,
        unit: str = None
    ) -> dict:
        """
        Calculate bubble point pressure or temperature.

        Bubble point is the condition at which the first bubble of vapor forms when
        heating a liquid. For pure components, bubble point equals vapor pressure.
        For mixtures, returns the incipient vapor composition (which components
        vaporize first).

        Essential for:
        - Storage tank design: Maximum safe pressure for liquid storage
        - Pump NPSH: Ensure liquid doesn't flash at pump inlet
        - Pipeline design: Prevent two-phase flow in liquid lines
        - Distillation: Understanding light component partitioning

        Args:
            specification: Either "temperature" or "pressure"
            value: The specified value (temperature or pressure)
            unit: Unit for the value (optional)
                - For temperature: "K", "C" (default: "C")
                - For pressure: "bar", "Pa", "kPa", "MPa", "psi", "atm" (default: "bar")

        Returns:
            Dict with bubble point results:
            {
                "input": {
                    "specification": str,
                    "value": float,
                    "unit": str
                },
                "bubble_point_pressure": {
                    "value_Pa": float,
                    "value_bar": float,
                    "value_MPa": float,
                    "value_psi": float
                } (if spec="temperature"),
                "bubble_point_temperature": {
                    "value_K": float,
                    "value_C": float
                } (if spec="pressure"),
                "incipient_vapor_composition": {
                    "component_names": List[str],
                    "mole_fractions": List[float]
                },
                "is_pure_component": bool
            }

        Error codes:
            INVALID_INPUT: Bad specification, unit, or value
            NO_FLUID_LOADED: No fluid loaded
            ABOVE_CRITICAL: Condition exceeds critical point
            BELOW_TRIPLE_POINT: Condition below triple point
            BUBBLE_CALC_FAILED: Calculation failed

        Examples:
            >>> bubble_point(specification="temperature", value=0, unit="C")
            # Returns: ~34.85 bar for pure CO2

            >>> bubble_point(specification="pressure", value=50, unit="bar")
            # Returns: ~14°C for pure CO2

            >>> bubble_point(specification="temperature", value=20, unit="C")
            # For mixture: shows which light components enrich in vapor phase
        """
        # Validate specification
        spec_lower = specification.lower()
        if spec_lower not in ["temperature", "pressure"]:
            raise MCPError(
                "INVALID_INPUT",
                f"Invalid specification '{specification}'. Must be 'temperature' or 'pressure'."
            )

        # Set default units
        if unit is None:
            unit = "C" if spec_lower == "temperature" else "bar"

        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file first."
            )

        # Determine if pure component
        is_pure = len([x for x in wrapper.composition if x > 0]) == 1

        # Calculate bubble point based on specification
        if spec_lower == "temperature":
            # Given T, find bubble point pressure
            try:
                validate_temperature(value, unit)
                T_k = convert_temperature_to_k(value, unit)
            except ValueError as e:
                raise MCPError("INVALID_INPUT", str(e))

            # Check bounds
            if T_k > CO2_TC_K:
                raise MCPError(
                    "ABOVE_CRITICAL",
                    f"Temperature {value} {unit} ({T_k:.2f} K) exceeds critical temperature "
                    f"(~{CO2_TC_K:.2f} K for CO2). No bubble point exists above Tc."
                )
            if T_k < CO2_TRIPLE_T_K:
                raise MCPError(
                    "BELOW_TRIPLE_POINT",
                    f"Temperature {value} {unit} ({T_k:.2f} K) is below triple point "
                    f"(~{CO2_TRIPLE_T_K:.2f} K for CO2). Solid phase may form."
                )

            # Binary search for bubble point pressure
            # Bubble point: HIGHEST pressure where two phases exist (vapor fraction → 0)
            # For mixtures: P_dew < P_bubble at given T
            try:
                P_low = 1e5  # 1 bar
                P_high = min(CO2_PC_PA * 0.99, 1e8)  # Just below critical

                max_iterations = 50
                tolerance = 1e3  # 1 kPa
                vapor_frac_tolerance = 0.001  # Target vapor fraction for bubble point

                incipient_vapor_comp = None
                P_bubble = None

                for _ in range(max_iterations):
                    P_mid = (P_low + P_high) / 2
                    flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_mid)

                    if flash_result.num_phases == 2:
                        # Two-phase: calculate vapor fraction
                        total_moles = sum(flash_result.moles_per_phase)
                        vapor_moles = 0.0
                        for idx, phase_name in enumerate(flash_result.phase_names):
                            if "GAS" in phase_name.upper():
                                vapor_moles = flash_result.moles_per_phase[idx]
                                incipient_vapor_comp = flash_result.compositions[idx]
                                break
                        vapor_fraction = vapor_moles / total_moles if total_moles > 0 else 0

                        # For bubble point: we want vapor_fraction → 0
                        # If vapor_fraction is high, we need HIGHER pressure
                        # If vapor_fraction is low, we need LOWER pressure (approaching single liquid)
                        if vapor_fraction > vapor_frac_tolerance:
                            # Still too much vapor - need higher pressure
                            P_low = P_mid
                        else:
                            # Very little vapor - at or past bubble point
                            P_bubble = P_mid
                            P_high = P_mid
                    elif flash_result.num_phases == 1:
                        phase_name = flash_result.phase_names[0]
                        if "LIQUID" in phase_name.upper():
                            # Single liquid: P > P_bubble, need lower pressure
                            P_high = P_mid
                        else:
                            # Single gas: P < P_dew < P_bubble, need higher pressure
                            P_low = P_mid

                    if abs(P_high - P_low) < tolerance:
                        if P_bubble is None:
                            P_bubble = (P_high + P_low) / 2
                        # Get final flash for composition
                        if incipient_vapor_comp is None:
                            flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_bubble)
                            if flash_result.num_phases == 2:
                                for idx, phase_name in enumerate(flash_result.phase_names):
                                    if "GAS" in phase_name.upper():
                                        incipient_vapor_comp = flash_result.compositions[idx]
                                        break
                        break
                else:
                    if P_bubble is not None:
                        # We found a bubble point, just didn't converge tightly
                        pass
                    else:
                        raise MCPError(
                            "BUBBLE_CALC_FAILED",
                            f"Binary search did not converge after {max_iterations} iterations"
                        )

                # Build response
                response = {
                    "input": {
                        "specification": specification,
                        "value": value,
                        "unit": unit
                    },
                    "bubble_point_pressure": {
                        "value_Pa": P_bubble,
                        "value_bar": P_bubble / 1e5,
                        "value_MPa": P_bubble / 1e6,
                        "value_psi": P_bubble / 6894.757
                    },
                    "is_pure_component": is_pure
                }

                # Add incipient vapor composition if available
                if incipient_vapor_comp:
                    response["incipient_vapor_composition"] = {
                        "component_names": wrapper.component_names if hasattr(wrapper, 'component_names') else [],
                        "mole_fractions": incipient_vapor_comp
                    }

                logger.info(
                    f"Bubble point at {value} {unit}: {P_bubble/1e5:.2f} bar"
                )
                return response

            except MCPError:
                raise
            except Exception as e:
                raise MCPError(
                    "BUBBLE_CALC_FAILED",
                    f"Bubble point pressure calculation failed: {e}"
                )

        else:  # spec_lower == "pressure"
            # Given P, find bubble point temperature
            try:
                validate_pressure(value, unit)
                P_pa = convert_pressure_to_pa(value, unit)
            except ValueError as e:
                raise MCPError("INVALID_INPUT", str(e))

            # Check bounds
            if P_pa > CO2_PC_PA:
                raise MCPError(
                    "ABOVE_CRITICAL",
                    f"Pressure {value} {unit} ({P_pa/1e5:.2f} bar) exceeds critical pressure "
                    f"(~{CO2_PC_PA/1e5:.2f} bar for CO2). No bubble point exists above Pc."
                )
            if P_pa < CO2_TRIPLE_P_PA:
                raise MCPError(
                    "BELOW_TRIPLE_POINT",
                    f"Pressure {value} {unit} ({P_pa/1e5:.2f} bar) is below triple point "
                    f"(~{CO2_TRIPLE_P_PA/1e5:.2f} bar for CO2). Solid phase may form."
                )

            # Binary search for bubble point temperature
            # Bubble point: LOWEST temperature where two phases exist at this P (vapor fraction → 0)
            # For mixtures at given P: T_bubble < T_dew
            try:
                T_low = CO2_TRIPLE_T_K + 5
                T_high = CO2_TC_K - 0.5

                max_iterations = 50
                tolerance = 0.01  # 0.01 K
                vapor_frac_tolerance = 0.001  # Target vapor fraction for bubble point

                incipient_vapor_comp = None
                T_bubble = None

                for _ in range(max_iterations):
                    T_mid = (T_low + T_high) / 2
                    flash_result = wrapper.pt_flash(temperature=T_mid, pressure=P_pa)

                    if flash_result.num_phases == 2:
                        # Two-phase: calculate vapor fraction
                        total_moles = sum(flash_result.moles_per_phase)
                        vapor_moles = 0.0
                        for idx, phase_name in enumerate(flash_result.phase_names):
                            if "GAS" in phase_name.upper():
                                vapor_moles = flash_result.moles_per_phase[idx]
                                incipient_vapor_comp = flash_result.compositions[idx]
                                break
                        vapor_fraction = vapor_moles / total_moles if total_moles > 0 else 0

                        # For bubble point: we want vapor_fraction → 0
                        # If vapor_fraction is high, we need LOWER temperature
                        # If vapor_fraction is low, we need HIGHER temperature (approaching single liquid)
                        if vapor_fraction > vapor_frac_tolerance:
                            # Still too much vapor - need lower temperature
                            T_high = T_mid
                        else:
                            # Very little vapor - at or past bubble point
                            T_bubble = T_mid
                            T_low = T_mid
                    elif flash_result.num_phases == 1:
                        phase_name = flash_result.phase_names[0]
                        if "LIQUID" in phase_name.upper():
                            # Single liquid: T < T_bubble, need higher temperature
                            T_low = T_mid
                        else:
                            # Single gas: T > T_dew > T_bubble, need lower temperature
                            T_high = T_mid

                    if abs(T_high - T_low) < tolerance:
                        if T_bubble is None:
                            T_bubble = (T_high + T_low) / 2
                        # Get final flash for composition
                        if incipient_vapor_comp is None:
                            flash_result = wrapper.pt_flash(temperature=T_bubble, pressure=P_pa)
                            if flash_result.num_phases == 2:
                                for idx, phase_name in enumerate(flash_result.phase_names):
                                    if "GAS" in phase_name.upper():
                                        incipient_vapor_comp = flash_result.compositions[idx]
                                        break
                        break
                else:
                    if T_bubble is not None:
                        pass  # Found a bubble point, just didn't converge tightly
                    else:
                        raise MCPError(
                            "BUBBLE_CALC_FAILED",
                            f"Binary search did not converge after {max_iterations} iterations"
                        )

                # Build response
                response = {
                    "input": {
                        "specification": specification,
                        "value": value,
                        "unit": unit
                    },
                    "bubble_point_temperature": {
                        "value_K": T_bubble,
                        "value_C": T_bubble - 273.15
                    },
                    "is_pure_component": is_pure
                }

                # Add incipient vapor composition if available
                if incipient_vapor_comp:
                    response["incipient_vapor_composition"] = {
                        "component_names": wrapper.component_names if hasattr(wrapper, 'component_names') else [],
                        "mole_fractions": incipient_vapor_comp
                    }

                logger.info(
                    f"Bubble point at {value} {unit}: {T_bubble-273.15:.2f} °C"
                )
                return response

            except MCPError:
                raise
            except Exception as e:
                raise MCPError(
                    "BUBBLE_CALC_FAILED",
                    f"Bubble point temperature calculation failed: {e}"
                )

    @mcp_server.tool()
    def dew_point(
        specification: str,
        value: float,
        unit: str = None
    ) -> dict:
        """
        Calculate dew point pressure or temperature.

        Dew point is the condition at which the first droplet of liquid forms when
        cooling a vapor. For pure components, dew point equals vapor pressure.
        For mixtures, returns the incipient liquid composition (which components
        condense first).

        Essential for:
        - Gas pipeline design: Prevent liquid dropout and slugging
        - Compressor inlet: Ensure no condensation at compressor
        - Heat exchanger design: Account for condensation heat transfer
        - Gas quality: Understanding heavy component condensation

        Args:
            specification: Either "temperature" or "pressure"
            value: The specified value (temperature or pressure)
            unit: Unit for the value (optional)
                - For temperature: "K", "C" (default: "C")
                - For pressure: "bar", "Pa", "kPa", "MPa", "psi", "atm" (default: "bar")

        Returns:
            Dict with dew point results:
            {
                "input": {
                    "specification": str,
                    "value": float,
                    "unit": str
                },
                "dew_point_pressure": {
                    "value_Pa": float,
                    "value_bar": float,
                    "value_MPa": float,
                    "value_psi": float
                } (if spec="temperature"),
                "dew_point_temperature": {
                    "value_K": float,
                    "value_C": float
                } (if spec="pressure"),
                "incipient_liquid_composition": {
                    "component_names": List[str],
                    "mole_fractions": List[float]
                },
                "is_pure_component": bool
            }

        Error codes:
            INVALID_INPUT: Bad specification, unit, or value
            NO_FLUID_LOADED: No fluid loaded
            ABOVE_CRITICAL: Condition exceeds critical point
            BELOW_TRIPLE_POINT: Condition below triple point
            DEW_CALC_FAILED: Calculation failed

        Examples:
            >>> dew_point(specification="temperature", value=0, unit="C")
            # Returns: ~34.85 bar for pure CO2 (same as bubble point)

            >>> dew_point(specification="pressure", value=50, unit="bar")
            # Returns: ~14°C for pure CO2 (same as bubble point)

            >>> dew_point(specification="temperature", value=20, unit="C")
            # For mixture: shows which heavy components enrich in liquid phase
        """
        # Validate specification
        spec_lower = specification.lower()
        if spec_lower not in ["temperature", "pressure"]:
            raise MCPError(
                "INVALID_INPUT",
                f"Invalid specification '{specification}'. Must be 'temperature' or 'pressure'."
            )

        # Set default units
        if unit is None:
            unit = "C" if spec_lower == "temperature" else "bar"

        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file first."
            )

        # Determine if pure component
        is_pure = len([x for x in wrapper.composition if x > 0]) == 1

        # Calculate dew point based on specification
        if spec_lower == "temperature":
            # Given T, find dew point pressure
            try:
                validate_temperature(value, unit)
                T_k = convert_temperature_to_k(value, unit)
            except ValueError as e:
                raise MCPError("INVALID_INPUT", str(e))

            # Check bounds
            if T_k > CO2_TC_K:
                raise MCPError(
                    "ABOVE_CRITICAL",
                    f"Temperature {value} {unit} ({T_k:.2f} K) exceeds critical temperature "
                    f"(~{CO2_TC_K:.2f} K for CO2). No dew point exists above Tc."
                )
            if T_k < CO2_TRIPLE_T_K:
                raise MCPError(
                    "BELOW_TRIPLE_POINT",
                    f"Temperature {value} {unit} ({T_k:.2f} K) is below triple point "
                    f"(~{CO2_TRIPLE_T_K:.2f} K for CO2). Solid phase may form."
                )

            # Binary search for dew point pressure
            # Dew point: LOWEST pressure where two phases exist (vapor fraction → 1)
            # For mixtures: P_dew < P_bubble at given T
            try:
                P_low = 1e5  # 1 bar
                P_high = min(CO2_PC_PA * 0.99, 1e8)  # Just below critical

                max_iterations = 50
                tolerance = 1e3  # 1 kPa
                liquid_frac_tolerance = 0.001  # Target liquid fraction for dew point

                incipient_liquid_comp = None
                P_dew = None

                for _ in range(max_iterations):
                    P_mid = (P_low + P_high) / 2
                    flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_mid)

                    if flash_result.num_phases == 2:
                        # Two-phase: calculate liquid fraction
                        total_moles = sum(flash_result.moles_per_phase)
                        liquid_moles = 0.0
                        for idx, phase_name in enumerate(flash_result.phase_names):
                            if "LIQUID" in phase_name.upper():
                                liquid_moles = flash_result.moles_per_phase[idx]
                                incipient_liquid_comp = flash_result.compositions[idx]
                                break
                        liquid_fraction = liquid_moles / total_moles if total_moles > 0 else 0

                        # For dew point: we want liquid_fraction → 0 (vapor_fraction → 1)
                        # If liquid_fraction is high, we need LOWER pressure
                        # If liquid_fraction is low, we need HIGHER pressure (approaching single gas)
                        if liquid_fraction > liquid_frac_tolerance:
                            # Still too much liquid - need lower pressure
                            P_high = P_mid
                        else:
                            # Very little liquid - at or past dew point
                            P_dew = P_mid
                            P_low = P_mid
                    elif flash_result.num_phases == 1:
                        phase_name = flash_result.phase_names[0]
                        if "GAS" in phase_name.upper():
                            # Single gas: P < P_dew, need higher pressure
                            P_low = P_mid
                        else:
                            # Single liquid: P > P_bubble > P_dew, need lower pressure
                            P_high = P_mid

                    if abs(P_high - P_low) < tolerance:
                        if P_dew is None:
                            P_dew = (P_high + P_low) / 2
                        # Get final flash for composition
                        if incipient_liquid_comp is None:
                            flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_dew)
                            if flash_result.num_phases == 2:
                                for idx, phase_name in enumerate(flash_result.phase_names):
                                    if "LIQUID" in phase_name.upper():
                                        incipient_liquid_comp = flash_result.compositions[idx]
                                        break
                        break
                else:
                    if P_dew is not None:
                        pass  # Found a dew point, just didn't converge tightly
                    else:
                        raise MCPError(
                            "DEW_CALC_FAILED",
                            f"Binary search did not converge after {max_iterations} iterations"
                        )

                # Build response
                response = {
                    "input": {
                        "specification": specification,
                        "value": value,
                        "unit": unit
                    },
                    "dew_point_pressure": {
                        "value_Pa": P_dew,
                        "value_bar": P_dew / 1e5,
                        "value_MPa": P_dew / 1e6,
                        "value_psi": P_dew / 6894.757
                    },
                    "is_pure_component": is_pure
                }

                # Add incipient liquid composition if available
                if incipient_liquid_comp:
                    response["incipient_liquid_composition"] = {
                        "component_names": wrapper.component_names if hasattr(wrapper, 'component_names') else [],
                        "mole_fractions": incipient_liquid_comp
                    }

                logger.info(
                    f"Dew point at {value} {unit}: {P_dew/1e5:.2f} bar"
                )
                return response

            except MCPError:
                raise
            except Exception as e:
                raise MCPError(
                    "DEW_CALC_FAILED",
                    f"Dew point pressure calculation failed: {e}"
                )

        else:  # spec_lower == "pressure"
            # Given P, find dew point temperature
            try:
                validate_pressure(value, unit)
                P_pa = convert_pressure_to_pa(value, unit)
            except ValueError as e:
                raise MCPError("INVALID_INPUT", str(e))

            # Check bounds
            if P_pa > CO2_PC_PA:
                raise MCPError(
                    "ABOVE_CRITICAL",
                    f"Pressure {value} {unit} ({P_pa/1e5:.2f} bar) exceeds critical pressure "
                    f"(~{CO2_PC_PA/1e5:.2f} bar for CO2). No dew point exists above Pc."
                )
            if P_pa < CO2_TRIPLE_P_PA:
                raise MCPError(
                    "BELOW_TRIPLE_POINT",
                    f"Pressure {value} {unit} ({P_pa/1e5:.2f} bar) is below triple point "
                    f"(~{CO2_TRIPLE_P_PA/1e5:.2f} bar for CO2). Solid phase may form."
                )

            # Binary search for dew point temperature
            # Dew point: HIGHEST temperature where two phases exist at this P (vapor fraction → 1)
            # For mixtures at given P: T_bubble < T_dew
            try:
                T_low = CO2_TRIPLE_T_K + 5
                T_high = CO2_TC_K - 0.5

                max_iterations = 50
                tolerance = 0.01  # 0.01 K
                liquid_frac_tolerance = 0.001  # Target liquid fraction for dew point

                incipient_liquid_comp = None
                T_dew = None

                for _ in range(max_iterations):
                    T_mid = (T_low + T_high) / 2
                    flash_result = wrapper.pt_flash(temperature=T_mid, pressure=P_pa)

                    if flash_result.num_phases == 2:
                        # Two-phase: calculate liquid fraction
                        total_moles = sum(flash_result.moles_per_phase)
                        liquid_moles = 0.0
                        for idx, phase_name in enumerate(flash_result.phase_names):
                            if "LIQUID" in phase_name.upper():
                                liquid_moles = flash_result.moles_per_phase[idx]
                                incipient_liquid_comp = flash_result.compositions[idx]
                                break
                        liquid_fraction = liquid_moles / total_moles if total_moles > 0 else 0

                        # For dew point: we want liquid_fraction → 0 (vapor_fraction → 1)
                        # If liquid_fraction is high, we need HIGHER temperature
                        # If liquid_fraction is low, we need LOWER temperature (approaching single gas)
                        if liquid_fraction > liquid_frac_tolerance:
                            # Still too much liquid - need higher temperature
                            T_low = T_mid
                        else:
                            # Very little liquid - at or past dew point
                            T_dew = T_mid
                            T_high = T_mid
                    elif flash_result.num_phases == 1:
                        phase_name = flash_result.phase_names[0]
                        if "GAS" in phase_name.upper():
                            # Single gas: T > T_dew, need lower temperature
                            T_high = T_mid
                        else:
                            # Single liquid: T < T_bubble < T_dew, need higher temperature
                            T_low = T_mid

                    if abs(T_high - T_low) < tolerance:
                        if T_dew is None:
                            T_dew = (T_high + T_low) / 2
                        # Get final flash for composition
                        if incipient_liquid_comp is None:
                            flash_result = wrapper.pt_flash(temperature=T_dew, pressure=P_pa)
                            if flash_result.num_phases == 2:
                                for idx, phase_name in enumerate(flash_result.phase_names):
                                    if "LIQUID" in phase_name.upper():
                                        incipient_liquid_comp = flash_result.compositions[idx]
                                        break
                        break
                else:
                    if T_dew is not None:
                        pass  # Found a dew point, just didn't converge tightly
                    else:
                        raise MCPError(
                            "DEW_CALC_FAILED",
                            f"Binary search did not converge after {max_iterations} iterations"
                        )

                # Build response
                response = {
                    "input": {
                        "specification": specification,
                        "value": value,
                        "unit": unit
                    },
                    "dew_point_temperature": {
                        "value_K": T_dew,
                        "value_C": T_dew - 273.15
                    },
                    "is_pure_component": is_pure
                }

                # Add incipient liquid composition if available
                if incipient_liquid_comp:
                    response["incipient_liquid_composition"] = {
                        "component_names": wrapper.component_names if hasattr(wrapper, 'component_names') else [],
                        "mole_fractions": incipient_liquid_comp
                    }

                logger.info(
                    f"Dew point at {value} {unit}: {T_dew-273.15:.2f} °C"
                )
                return response

            except MCPError:
                raise
            except Exception as e:
                raise MCPError(
                    "DEW_CALC_FAILED",
                    f"Dew point temperature calculation failed: {e}"
                )

    @mcp_server.tool()
    def get_cricondentherm(
        temperature_unit: str = "C",
        pressure_unit: str = "bar"
    ) -> dict:
        """
        Get the cricondentherm - maximum temperature on the phase envelope.

        The cricondentherm is the highest temperature at which liquid can exist.
        Above this temperature, no liquid forms regardless of pressure.

        For pure components: cricondentherm = critical temperature
        For mixtures: cricondentherm >= critical temperature (retrograde region)

        Args:
            temperature_unit: Output temperature unit ("C" or "K", default "C")
            pressure_unit: Output pressure unit ("bar", "Pa", "kPa", "MPa", "psi", default "bar")

        Returns:
            Dict with cricondentherm data:
            {
                "fluid_name": str,
                "is_pure_component": bool,
                "cricondentherm": {
                    "temperature_K": float,
                    "temperature_C": float
                },
                "pressure_at_cricondentherm": {
                    "value_Pa": float,
                    "value_bar": float,
                    "value_MPa": float,
                    "value_psi": float
                },
                "critical_temperature_C": float,
                "exceeds_critical_by_K": float,  # 0 for pure components
                "note": str  # Interpretation
            }

        Error codes:
            NO_FLUID_LOADED: No fluid loaded
            CALC_FAILED: Could not determine cricondentherm
        """
        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file first."
            )

        # Get fluid info
        num_components = len(wrapper.composition)
        is_pure = num_components == 1 or len([x for x in wrapper.composition if x > 0]) == 1
        fluid_name = wrapper.fluid_name if wrapper.fluid_name else "unknown"

        # Get critical point for comparison
        try:
            Tc_K, Pc_Pa, Vc_m3_mol = wrapper.get_critical_point()
        except RuntimeError as e:
            raise MCPError(
                "CALC_FAILED",
                f"Could not get critical point: {e}"
            )

        if is_pure:
            # For pure components, cricondentherm = critical temperature
            cricondentherm_T = Tc_K
            cricondentherm_P = Pc_Pa
            exceeds_K = 0.0
            note = "Pure component: cricondentherm equals critical temperature"
        else:
            # For mixtures, find max T on envelope
            # We need to generate the phase envelope and find max temperature point
            # This will be implemented when we have get_phase_envelope
            # For now, use critical point as approximation
            try:
                # Attempt to find max T by sampling dew curve
                # Use a simple approach: search for max T along dew curve
                # Start at critical point and search nearby

                # Sample temperatures around and above Tc
                T_search_max = Tc_K + 50  # Search up to Tc + 50K
                T_step = 0.5  # K

                max_T_found = Tc_K
                P_at_max_T = Pc_Pa

                # Search for maximum temperature where two phases exist
                T_test = Tc_K
                while T_test <= T_search_max:
                    # Try a range of pressures at this temperature
                    # to see if we can find two-phase region
                    P_low = Pc_Pa * 0.1
                    P_high = Pc_Pa * 2.0

                    found_two_phase = False
                    for P_test in [P_low + (P_high - P_low) * i / 10 for i in range(11)]:
                        try:
                            flash_result = wrapper.pt_flash(temperature=T_test, pressure=P_test)
                            if flash_result.num_phases == 2:
                                # Found two-phase region at this temperature
                                max_T_found = T_test
                                P_at_max_T = P_test
                                found_two_phase = True
                                break
                        except:
                            continue

                    if not found_two_phase and T_test > Tc_K:
                        # No two-phase region found above Tc, stop searching
                        break

                    T_test += T_step

                cricondentherm_T = max_T_found
                cricondentherm_P = P_at_max_T
                exceeds_K = cricondentherm_T - Tc_K

                if exceeds_K > 0.1:
                    note = f"Mixture: cricondentherm exceeds Tc by {exceeds_K:.1f} K (retrograde region exists)"
                else:
                    note = "Mixture: cricondentherm approximately equals critical temperature"

            except Exception as e:
                # Fall back to critical point
                logger.warning(f"Could not determine cricondentherm from envelope, using critical point: {e}")
                cricondentherm_T = Tc_K
                cricondentherm_P = Pc_Pa
                exceeds_K = 0.0
                note = "Mixture: cricondentherm approximated as critical temperature"

        # Convert to requested units
        result = {
            "fluid_name": fluid_name,
            "is_pure_component": is_pure,
            "cricondentherm": {
                "temperature_K": cricondentherm_T,
                "temperature_C": cricondentherm_T - 273.15
            },
            "pressure_at_cricondentherm": {
                "value_Pa": cricondentherm_P,
                "value_bar": cricondentherm_P / 1e5,
                "value_MPa": cricondentherm_P / 1e6,
                "value_psi": cricondentherm_P / 6894.757
            },
            "critical_temperature_C": Tc_K - 273.15,
            "exceeds_critical_by_K": exceeds_K,
            "note": note
        }

        # Log result
        logger.info(
            f"Cricondentherm for {fluid_name}: "
            f"{cricondentherm_T - 273.15:.2f} °C, exceeds Tc by {exceeds_K:.2f} K"
        )

        return result

    @mcp_server.tool()
    def get_cricondenbar(
        temperature_unit: str = "C",
        pressure_unit: str = "bar"
    ) -> dict:
        """
        Get the cricondenbar - maximum pressure on the phase envelope.

        The cricondenbar is the highest pressure at which vapor can exist.
        Above this pressure, no vapor forms regardless of temperature.

        For pure components: cricondenbar = critical pressure
        For mixtures: cricondenbar >= critical pressure

        Args:
            temperature_unit: Output temperature unit ("C" or "K", default "C")
            pressure_unit: Output pressure unit ("bar", "Pa", "kPa", "MPa", "psi", default "bar")

        Returns:
            Dict with cricondenbar data:
            {
                "fluid_name": str,
                "is_pure_component": bool,
                "cricondenbar": {
                    "pressure_Pa": float,
                    "pressure_bar": float,
                    "pressure_MPa": float,
                    "pressure_psi": float
                },
                "temperature_at_cricondenbar": {
                    "value_K": float,
                    "value_C": float
                },
                "critical_pressure_bar": float,
                "exceeds_critical_by_bar": float,  # 0 for pure components
                "note": str
            }

        Error codes:
            NO_FLUID_LOADED: No fluid loaded
            CALC_FAILED: Could not determine cricondenbar
        """
        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file first."
            )

        # Get fluid info
        num_components = len(wrapper.composition)
        is_pure = num_components == 1 or len([x for x in wrapper.composition if x > 0]) == 1
        fluid_name = wrapper.fluid_name if wrapper.fluid_name else "unknown"

        # Get critical point for comparison
        try:
            Tc_K, Pc_Pa, Vc_m3_mol = wrapper.get_critical_point()
        except RuntimeError as e:
            raise MCPError(
                "CALC_FAILED",
                f"Could not get critical point: {e}"
            )

        if is_pure:
            # For pure components, cricondenbar = critical pressure
            cricondenbar_P = Pc_Pa
            cricondenbar_T = Tc_K
            exceeds_bar = 0.0
            note = "Pure component: cricondenbar equals critical pressure"
        else:
            # For mixtures, find max P on envelope
            try:
                # Search for maximum pressure where two phases exist
                # Start at critical point and search nearby

                # Sample pressures around and above Pc
                P_search_max = Pc_Pa * 2.0  # Search up to 2x Pc
                P_step = Pc_Pa * 0.01  # 1% steps

                max_P_found = Pc_Pa
                T_at_max_P = Tc_K

                # Search for maximum pressure where two phases exist
                P_test = Pc_Pa
                while P_test <= P_search_max:
                    # Try a range of temperatures at this pressure
                    T_low = Tc_K * 0.7
                    T_high = Tc_K * 1.2

                    found_two_phase = False
                    for T_test in [T_low + (T_high - T_low) * i / 10 for i in range(11)]:
                        try:
                            flash_result = wrapper.pt_flash(temperature=T_test, pressure=P_test)
                            if flash_result.num_phases == 2:
                                # Found two-phase region at this pressure
                                max_P_found = P_test
                                T_at_max_P = T_test
                                found_two_phase = True
                                break
                        except:
                            continue

                    if not found_two_phase and P_test > Pc_Pa:
                        # No two-phase region found above Pc, stop searching
                        break

                    P_test += P_step

                cricondenbar_P = max_P_found
                cricondenbar_T = T_at_max_P
                exceeds_bar = (cricondenbar_P - Pc_Pa) / 1e5  # in bar

                if exceeds_bar > 0.1:
                    note = f"Mixture: cricondenbar exceeds Pc by {exceeds_bar:.1f} bar"
                else:
                    note = "Mixture: cricondenbar approximately equals critical pressure"

            except Exception as e:
                # Fall back to critical point
                logger.warning(f"Could not determine cricondenbar from envelope, using critical point: {e}")
                cricondenbar_P = Pc_Pa
                cricondenbar_T = Tc_K
                exceeds_bar = 0.0
                note = "Mixture: cricondenbar approximated as critical pressure"

        # Build response
        result = {
            "fluid_name": fluid_name,
            "is_pure_component": is_pure,
            "cricondenbar": {
                "pressure_Pa": cricondenbar_P,
                "pressure_bar": cricondenbar_P / 1e5,
                "pressure_MPa": cricondenbar_P / 1e6,
                "pressure_psi": cricondenbar_P / 6894.757
            },
            "temperature_at_cricondenbar": {
                "value_K": cricondenbar_T,
                "value_C": cricondenbar_T - 273.15
            },
            "critical_pressure_bar": Pc_Pa / 1e5,
            "exceeds_critical_by_bar": exceeds_bar,
            "note": note
        }

        # Log result
        logger.info(
            f"Cricondenbar for {fluid_name}: "
            f"{cricondenbar_P / 1e5:.2f} bar, exceeds Pc by {exceeds_bar:.2f} bar"
        )

        return result

    @mcp_server.tool()
    def get_phase_envelope(
        envelope_type: str = "PT",
        num_points: int = 50,
        temperature_min: float = None,
        temperature_max: float = None,
        critical_temperature: float = None,
        critical_pressure: float = None,
        include_quality_lines: bool = False,
        temperature_unit: str = "C",
        pressure_unit: str = "bar"
    ) -> dict:
        """
        Get the complete phase envelope (bubble and dew curves).

        The phase envelope is the boundary between single-phase and two-phase regions.
        For pure components, bubble and dew curves coincide (single saturation line).
        For mixtures, they form an envelope with cricondentherm (max T) and cricondenbar (max P).

        Essential for:
        - Process design: Visualize safe operating regions
        - Pipeline design: Avoid phase transition regions
        - Compression: Understand phase behavior during compression
        - Storage: Determine liquid/vapor boundaries for tank design

        Args:
            envelope_type: Diagram type (default: "PT")
                - "PT": Pressure-Temperature envelope (only option for now)
            num_points: Points per curve (10-500, default: 50)
            temperature_min: Minimum temperature for envelope (in temperature_unit)
                - Default: ~5K above CO2 triple point (-51.6°C)
                - Must be above triple point (~-56.6°C for CO2)
            temperature_max: Maximum temperature for envelope (in temperature_unit)
                - Default: just below critical temperature
                - Will be capped at critical temperature (no envelope above Tc)
            critical_temperature: Override critical temperature (in temperature_unit)
                - Use this if AXCRIT fails for your EOS (e.g., GERG/CG)
                - If not provided, will be calculated automatically
            critical_pressure: Override critical pressure (in pressure_unit)
                - Use this if AXCRIT fails for your EOS (e.g., GERG/CG)
                - If not provided, will be calculated automatically
            include_quality_lines: Include constant vapor fraction lines (default: False)
                - Quality lines at 0.1, 0.2, ..., 0.9 vapor fraction
            temperature_unit: Temperature unit for min/max and output ("C" or "K", default "C")
            pressure_unit: Output pressure unit ("bar", "Pa", "kPa", "MPa", "psi", default "bar")

        Returns:
            Dict with phase envelope data:
            {
                "envelope_type": str,
                "fluid_name": str,
                "is_pure_component": bool,
                "num_points": int,
                "bubble_curve": [
                    {
                        "temperature": float,
                        "pressure": float,
                        "density_liquid": float  # kg/m³
                    },
                    ...
                ],
                "dew_curve": [
                    {
                        "temperature": float,
                        "pressure": float,
                        "density_vapor": float  # kg/m³
                    },
                    ...
                ],
                "critical_point": {
                    "temperature": float,
                    "pressure": float,
                    "density": float
                },
                "cricondentherm": {
                    "temperature": float,
                    "pressure": float
                },
                "cricondenbar": {
                    "temperature": float,
                    "pressure": float
                },
                "quality_lines": [  # Only if include_quality_lines=True
                    {
                        "quality": float,
                        "points": [{"temperature": float, "pressure": float}, ...]
                    },
                    ...
                ],
                "units": {
                    "temperature": str,
                    "pressure": str,
                    "density": "kg/m3"
                },
                "note": str  # Interpretation for pure components
            }

        Error codes:
            INVALID_INPUT: Invalid envelope_type or num_points out of range
            NO_FLUID_LOADED: No fluid loaded
            ENVELOPE_FAILED: Could not trace envelope

        Examples:
            >>> get_phase_envelope(num_points=100)
            # Returns complete PT envelope with 100 points per curve (default T range)

            >>> get_phase_envelope(temperature_min=-30, temperature_max=30, num_points=120)
            # Returns envelope from -30°C to 30°C with 0.5°C steps (120 points)

            >>> get_phase_envelope(temperature_min=-30, temperature_max=28, num_points=140)
            # Returns envelope with ~0.5°C resolution over specified range

            >>> get_phase_envelope(temperature_min=-30, temperature_max=28, num_points=140,
            ...                    critical_temperature=28, critical_pressure=78)
            # Use manual critical point if AXCRIT fails with your EOS (GERG/CG)
        """
        # Validate inputs
        if envelope_type != "PT":
            raise MCPError(
                "INVALID_INPUT",
                f"Invalid envelope_type '{envelope_type}'. Only 'PT' is supported."
            )

        if not (10 <= num_points <= 500):
            raise MCPError(
                "INVALID_INPUT",
                f"num_points must be between 10 and 500, got {num_points}"
            )

        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file first."
            )

        # Get fluid info
        num_components = len(wrapper.composition)
        is_pure = num_components == 1 or len([x for x in wrapper.composition if x > 0]) == 1
        fluid_name = wrapper.fluid_name if wrapper.fluid_name else "unknown"

        # Get molecular weight first (needed for density calculations)
        try:
            MW_kg_mol = wrapper.get_molecular_weight()
        except RuntimeError:
            MW_kg_mol = 0.04401  # CO2 molecular weight as default

        # Get critical point - use provided values, or try AXCRIT, or estimate from convergence
        critical_point_source = "calculated"
        Vc_m3_mol = 0.0001  # Approximate default

        # Convert provided critical values to SI units if given
        if critical_temperature is not None and critical_pressure is not None:
            # User provided critical point - convert to SI
            if temperature_unit == "C":
                Tc_K = critical_temperature + 273.15
            else:
                Tc_K = critical_temperature

            Pc_Pa = convert_pressure_to_pa(critical_pressure, pressure_unit)
            critical_point_source = "user_provided"
            logger.info(f"Using user-provided critical point: Tc={Tc_K:.2f} K, Pc={Pc_Pa/1e5:.2f} bar")
        else:
            # Try to calculate critical point via AXCRIT
            try:
                Tc_K, Pc_Pa, Vc_m3_mol = wrapper.get_critical_point()
                critical_point_source = "calculated"
                logger.info(f"Calculated critical point (AXCRIT): Tc={Tc_K:.2f} K, Pc={Pc_Pa/1e5:.2f} bar")
            except RuntimeError as e:
                # AXCRIT failed - estimate critical point by finding where phases converge
                logger.warning(f"AXCRIT failed ({e}), estimating critical point from phase convergence...")
                Tc_K, Pc_Pa = _estimate_critical_point(wrapper, logger)
                critical_point_source = "estimated_from_convergence"
                logger.info(f"Estimated critical point: Tc={Tc_K:.2f} K, Pc={Pc_Pa/1e5:.2f} bar")

        # Calculate critical density
        rhoc_kg_m3 = MW_kg_mol / Vc_m3_mol

        # Helper function for unit conversion
        def convert_temp_from_k(T_k):
            if temperature_unit == "K":
                return T_k
            elif temperature_unit == "C":
                return T_k - 273.15
            else:
                raise MCPError("INVALID_INPUT", f"Unknown temperature unit: {temperature_unit}")

        def convert_press_from_pa(P_pa):
            conversions = {
                "Pa": 1.0,
                "kPa": 1e-3,
                "MPa": 1e-6,
                "bar": 1e-5,
                "psi": 1/6894.76,
                "atm": 1/101325
            }
            if pressure_unit not in conversions:
                raise MCPError("INVALID_INPUT", f"Unknown pressure unit: {pressure_unit}")
            return P_pa * conversions[pressure_unit]

        # Helper function to find bubble point pressure at given T
        def find_bubble_pressure(T_k, P_low, P_high, max_iter=30, tol=5e3):
            """Find highest P where vapor_fraction -> 0 (bubble point)."""
            vapor_frac_tol = 0.005  # 0.5% vapor tolerance
            P_bubble = None

            for _ in range(max_iter):
                P_mid = (P_low + P_high) / 2
                flash = wrapper.pt_flash(temperature=T_k, pressure=P_mid)

                if flash.num_phases == 2:
                    total = sum(flash.moles_per_phase)
                    vapor_moles = sum(m for name, m in zip(flash.phase_names, flash.moles_per_phase)
                                     if "GAS" in name.upper())
                    vf = vapor_moles / total if total > 0 else 0

                    if vf > vapor_frac_tol:
                        P_low = P_mid  # Need higher P
                    else:
                        P_bubble = P_mid
                        P_high = P_mid
                elif flash.num_phases == 1:
                    if "LIQUID" in flash.phase_names[0].upper():
                        P_high = P_mid
                    else:
                        P_low = P_mid

                if abs(P_high - P_low) < tol:
                    break

            return P_bubble if P_bubble else (P_high + P_low) / 2

        # Helper function to find dew point pressure at given T
        def find_dew_pressure(T_k, P_low, P_high, max_iter=30, tol=5e3):
            """Find lowest P where liquid_fraction -> 0 (dew point)."""
            liquid_frac_tol = 0.005  # 0.5% liquid tolerance
            P_dew = None

            for _ in range(max_iter):
                P_mid = (P_low + P_high) / 2
                flash = wrapper.pt_flash(temperature=T_k, pressure=P_mid)

                if flash.num_phases == 2:
                    total = sum(flash.moles_per_phase)
                    liquid_moles = sum(m for name, m in zip(flash.phase_names, flash.moles_per_phase)
                                      if "LIQUID" in name.upper())
                    lf = liquid_moles / total if total > 0 else 0

                    if lf > liquid_frac_tol:
                        P_high = P_mid  # Need lower P
                    else:
                        P_dew = P_mid
                        P_low = P_mid
                elif flash.num_phases == 1:
                    if "GAS" in flash.phase_names[0].upper():
                        P_low = P_mid
                    else:
                        P_high = P_mid

                if abs(P_high - P_low) < tol:
                    break

            return P_dew if P_dew else (P_high + P_low) / 2

        # Helper to get density at a point
        def get_density_at_point(T_k, P_pa, phase_type="liquid"):
            """Get density of specified phase at T, P."""
            try:
                flash = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
                for idx, name in enumerate(flash.phase_names):
                    target = "LIQUID" if phase_type == "liquid" else "GAS"
                    if target in name.upper():
                        aymix = wrapper.get_aymix_properties(
                            phase_lno=flash.phases[idx],
                            temperature=T_k,
                            pressure=P_pa,
                            composition=flash.compositions[idx],
                            get_volume_derivs=False
                        )
                        return MW_kg_mol / aymix.volume
            except:
                pass
            return None

        # Generate bubble and dew curves separately
        # For pure components: bubble = dew (single saturation line)
        # For mixtures: bubble != dew (two separate curves)
        try:
            bubble_curve = []
            dew_curve = []

            # Convert temperature_min/max to Kelvin if provided
            if temperature_min is not None:
                if temperature_unit == "C":
                    T_min = temperature_min + 273.15
                elif temperature_unit == "K":
                    T_min = temperature_min
                else:
                    raise MCPError("INVALID_INPUT", f"Unknown temperature unit: {temperature_unit}")
                # Validate T_min is above triple point
                if T_min < CO2_TRIPLE_T_K:
                    raise MCPError(
                        "INVALID_INPUT",
                        f"temperature_min ({temperature_min} {temperature_unit}) is below triple point "
                        f"(~{CO2_TRIPLE_T_K - 273.15:.1f} C). No liquid-vapor envelope exists below triple point."
                    )
            else:
                T_min = CO2_TRIPLE_T_K + 5  # Default: ~5K above triple point

            if temperature_max is not None:
                if temperature_unit == "C":
                    T_max = temperature_max + 273.15
                elif temperature_unit == "K":
                    T_max = temperature_max
                else:
                    raise MCPError("INVALID_INPUT", f"Unknown temperature unit: {temperature_unit}")
                # Cap at critical temperature (no envelope above Tc)
                if T_max > Tc_K:
                    logger.info(
                        f"temperature_max ({temperature_max} {temperature_unit}) exceeds critical temperature "
                        f"({Tc_K - 273.15:.1f} C). Capping at Tc."
                    )
                    T_max = Tc_K - 0.1
            else:
                T_max = Tc_K - 0.1  # Default: just below critical

            # Validate T_min < T_max
            if T_min >= T_max:
                raise MCPError(
                    "INVALID_INPUT",
                    f"temperature_min ({T_min - 273.15:.1f} C) must be less than temperature_max ({T_max - 273.15:.1f} C)"
                )

            # Calculate step size for logging
            step_size_K = (T_max - T_min) / (num_points - 1) if num_points > 1 else 0
            logger.info(
                f"Phase envelope: T range {T_min - 273.15:.1f} to {T_max - 273.15:.1f} C, "
                f"{num_points} points, step ~{step_size_K:.2f} K"
            )

            T_range = [T_min + (T_max - T_min) * i / (num_points - 1) for i in range(num_points)]

            for T_k in T_range:
                try:
                    P_low = CO2_TRIPLE_P_PA
                    P_high = Pc_Pa * 0.99

                    # Find bubble point (highest P where vapor still exists)
                    P_bubble = find_bubble_pressure(T_k, P_low, P_high)

                    # Find dew point (lowest P where liquid still exists)
                    P_dew = find_dew_pressure(T_k, P_low, P_high)

                    # Get densities
                    rho_liquid = get_density_at_point(T_k, P_bubble, "liquid")
                    rho_vapor = get_density_at_point(T_k, P_dew, "vapor")

                    # Add to bubble curve
                    bubble_point = {
                        "temperature": convert_temp_from_k(T_k),
                        "pressure": convert_press_from_pa(P_bubble)
                    }
                    if rho_liquid is not None:
                        bubble_point["density_liquid"] = rho_liquid
                    bubble_curve.append(bubble_point)

                    # Add to dew curve
                    dew_point = {
                        "temperature": convert_temp_from_k(T_k),
                        "pressure": convert_press_from_pa(P_dew)
                    }
                    if rho_vapor is not None:
                        dew_point["density_vapor"] = rho_vapor
                    dew_curve.append(dew_point)

                except Exception as e:
                    # Skip this point if calculation fails
                    logger.debug(f"Skipped envelope point at T={T_k:.2f} K: {e}")
                    continue

            if len(bubble_curve) < 3:
                raise MCPError(
                    "ENVELOPE_FAILED",
                    f"Could not trace envelope - only {len(bubble_curve)} points calculated"
                )

        except MCPError:
            raise
        except Exception as e:
            raise MCPError(
                "ENVELOPE_FAILED",
                f"Envelope calculation failed: {e}"
            )

        # Find cricondentherm and cricondenbar from generated curves
        # For pure components, these equal critical point
        if is_pure:
            cricondentherm_T = convert_temp_from_k(Tc_K)
            cricondentherm_P = convert_press_from_pa(Pc_Pa)
            cricondenbar_T = convert_temp_from_k(Tc_K)
            cricondenbar_P = convert_press_from_pa(Pc_Pa)
            note = "Pure component: bubble and dew curves coincide (saturation line)"
        else:
            # For mixtures, find max T and max P from curves
            max_T_point = max(bubble_curve + dew_curve, key=lambda pt: pt["temperature"])
            max_P_point = max(bubble_curve + dew_curve, key=lambda pt: pt["pressure"])

            cricondentherm_T = max_T_point["temperature"]
            cricondentherm_P = max_T_point["pressure"]
            cricondenbar_T = max_P_point["temperature"]
            cricondenbar_P = max_P_point["pressure"]
            note = "Mixture: bubble and dew curves form phase envelope"

        # Build response
        result = {
            "envelope_type": envelope_type,
            "fluid_name": fluid_name,
            "is_pure_component": is_pure,
            "num_points": len(bubble_curve),
            "bubble_curve": bubble_curve,
            "dew_curve": dew_curve,
            "critical_point": {
                "temperature": convert_temp_from_k(Tc_K),
                "pressure": convert_press_from_pa(Pc_Pa),
                "density": rhoc_kg_m3,
                "source": critical_point_source  # "calculated", "user_provided", or "default_CO2"
            },
            "cricondentherm": {
                "temperature": cricondentherm_T,
                "pressure": cricondentherm_P
            },
            "cricondenbar": {
                "temperature": cricondenbar_T,
                "pressure": cricondenbar_P
            },
            "units": {
                "temperature": temperature_unit,
                "pressure": pressure_unit,
                "density": "kg/m3"
            },
            "note": note
        }

        # Add quality lines if requested
        if include_quality_lines:
            # For now, return empty quality lines list
            # Full implementation requires flash calculations at constant quality
            # which is complex and time-consuming
            result["quality_lines"] = []
            logger.info("Quality lines requested but not yet implemented")

        # Log result
        logger.info(
            f"Phase envelope for {fluid_name}: "
            f"{len(bubble_curve)} points, "
            f"Tc={convert_temp_from_k(Tc_K):.2f} {temperature_unit}, "
            f"Pc={convert_press_from_pa(Pc_Pa):.2f} {pressure_unit}"
        )

        return result
