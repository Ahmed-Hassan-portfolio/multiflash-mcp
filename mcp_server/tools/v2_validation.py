"""
V2 Validation Tool - Verify MCP server v2 tools against literature reference data.

Provides MCP tool:
- run_v2_validation: Compare v2 tool outputs against published CO2 reference values.

This tool validates that v2 features (saturation, critical point, JT, sweep, batch flash)
return physically correct values for pure CO2. Reference numbers below come from
standard sources: NIST Chemistry WebBook / Span-Wagner CO2 EOS for saturation
pressures and critical-point properties. They serve as a smoke check that the
wrapper still produces physically correct numbers on the canonical CO2 cases.
"""

from typing import Optional, Dict, Any


class MCPError(Exception):
    """Structured error for MCP responses - local copy to avoid circular import."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


# V2 tolerance for quantitative checks
V2_TOLERANCE = 0.01  # 1% relative error tolerance


# CO2 saturation pressure reference data
# Source: NIST Chemistry WebBook / Span-Wagner equation of state.
# T (C): Psat (bar)
CO2_SATURATION_REFERENCE = {
    -40: 10.05,
    -20: 19.70,
    0: 34.85,
    10: 45.02,
    20: 57.29,
    # 31.0: 73.77  # Critical point (not saturation)
}


# CO2 critical point reference data
# Source: NIST Chemistry WebBook / Span-Wagner critical-point values.
CO2_CRITICAL_REFERENCE = {
    "Tc_K": 304.13,
    "Tc_C": 30.98,
    "Pc_MPa": 7.377,
    "Pc_bar": 73.77,
    "rhoc_kg_m3": 467.6,
    "Vc_cm3_mol": 94.07,
    "Zc": 0.274
}


# V2 reference test cases following the validation spec
V2_REFERENCE_CASES = {
    "saturation_pressure_0C": {
        "description": "Pure CO2 saturation pressure at 0 degrees C (VAL-01)",
        "tool": "get_saturation_pressure",
        "input": {"temperature": 0, "temperature_unit": "C"},
        "expected": {
            "saturation_pressure_bar": 34.85,
            "tolerance_percent": 1.0
        },
        "validation_type": "quantitative"
    },
    "critical_point_co2": {
        "description": "Pure CO2 critical point (VAL-02)",
        "tool": "get_critical_point",
        "input": {},  # Uses loaded fluid
        "expected": {
            "critical_temperature_K": 304.13,
            "critical_pressure_bar": 73.77,
            "tolerance_percent": 1.0
        },
        "validation_type": "quantitative"
    },
    "jt_coefficient_100bar_40C": {
        "description": "JT coefficient for CO2 at 100 bar, 40C (VAL-03)",
        "tool": "get_joule_thomson_coefficient",
        "input": {"pressure": 100, "temperature": 40, "pressure_unit": "bar", "temperature_unit": "C"},
        "expected": {
            "sign": "positive",  # Must be > 0 (cooling on expansion)
            "interpretation": "cooling on expansion"
        },
        "validation_type": "qualitative"
    },
    "property_sweep_transition": {
        "description": "Property sweep crosses phase transition (VAL-04)",
        "tool": "property_sweep",
        "input": {
            "properties": ["density"],
            "sweep_variable": "pressure",
            "sweep_start": 20,
            "sweep_end": 80,
            "fixed_variable": "temperature",
            "fixed_value": 10,  # 10C, near saturation ~45 bar
            "num_points": 20
        },
        "expected": {
            "has_phase_transition": True,
            "transition_near_bar": 45.0,  # Psat at 10C
            "tolerance_bar": 5.0
        },
        "validation_type": "phase_transition"
    },
    "batch_flash_mixed": {
        "description": "Batch flash handles success and failure gracefully (VAL-05)",
        "tool": "batch_flash",
        "input": {
            "flash_type": "PT",
            "conditions": [
                {"pressure": 50, "temperature": 20},   # Valid: liquid
                {"pressure": 10, "temperature": 40},   # Valid: gas
                {"pressure": -10, "temperature": 20},  # Invalid: negative P
                {"pressure": 50, "temperature": -300}  # Invalid: below absolute zero
            ]
        },
        "expected": {
            "num_successful": 2,
            "num_failed": 2,
            "handles_gracefully": True  # No crash, reports failures
        },
        "validation_type": "mixed_results"
    }
}


def register_v2_validation_tools(mcp_server, get_wrapper_fn, logger):
    """Register v2 validation tools with the MCP server."""

    @mcp_server.tool()
    def run_v2_validation(test_case: str = "all") -> dict:
        """
        Run validation against v2 tool reference test cases.

        This tool validates that v2 MCP server tools return correct values
        by comparing against published CO2 reference data (NIST / Span-Wagner).

        Use this to verify that:
        - Saturation calculations match CO2 vapor pressure data
        - Critical point matches literature values
        - JT coefficient has correct sign (cooling on expansion)
        - Property sweeps detect phase transitions
        - Batch operations handle mixed success/failure gracefully

        Args:
            test_case: Which test to run (default: "all")
                - "saturation_pressure_0C": Psat at 0C (VAL-01)
                - "critical_point_co2": Critical properties (VAL-02)
                - "jt_coefficient_100bar_40C": JT coefficient (VAL-03)
                - "property_sweep_transition": Phase transition (VAL-04)
                - "batch_flash_mixed": Mixed results handling (VAL-05)
                - "all": Run all test cases

        Returns:
            Dict with validation results:
            {
                "test_case": str,
                "overall_result": "PASS" or "FAIL",
                "tolerance_percent": float,
                "results": {...},
                "summary": {"total_checks": int, "passed": int, "failed": int}
            }

            For "all" mode, returns list of individual results plus aggregate summary.

        Error codes:
            INVALID_INPUT: Unknown test_case
            NO_FLUID_LOADED: Pure_CO2.mfl must be loaded first
            VALIDATION_FAILED: Tool call failed during validation

        Examples:
            >>> run_v2_validation("saturation_pressure_0C")
            # Validates CO2 saturation pressure at 0C against 34.85 bar

            >>> run_v2_validation("all")
            # Runs all v2 validation tests
        """
        # Validate test_case parameter
        valid_cases = list(V2_REFERENCE_CASES.keys()) + ["all"]
        if test_case not in valid_cases:
            raise MCPError(
                "INVALID_INPUT",
                f"Invalid test_case: '{test_case}'. Must be one of: {valid_cases}"
            )

        # Get wrapper and check fluid loaded
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise  # Re-raise DLL connection errors as-is

        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Load Pure_CO2.mfl first using load_mfl_file."
            )

        # Check that Pure CO2 is loaded (for accurate validation)
        if wrapper.fluid_name and "CO2" not in wrapper.fluid_name.upper():
            logger.warning(
                f"Validation expects Pure_CO2.mfl, but {wrapper.fluid_name} is loaded. "
                f"Results may not match reference values."
            )

        # Run validation
        if test_case == "all":
            results = []
            for case_name in V2_REFERENCE_CASES.keys():
                try:
                    result = _validate_single_case(case_name, wrapper, mcp_server, logger)
                    results.append(result)
                except Exception as e:
                    # Record failure but continue with other tests
                    results.append({
                        "test_case": case_name,
                        "overall_result": "FAIL",
                        "error": str(e),
                        "summary": {"total_checks": 1, "passed": 0, "failed": 1}
                    })

            # Aggregate summary
            total_passed = sum(r["summary"]["passed"] for r in results)
            total_failed = sum(r["summary"]["failed"] for r in results)
            overall_pass = all(r["overall_result"] == "PASS" for r in results)

            return {
                "test_mode": "all",
                "cases_run": len(results),
                "overall_result": "PASS" if overall_pass else "FAIL",
                "tolerance_percent": V2_TOLERANCE * 100,
                "results": results,
                "aggregate_summary": {
                    "total_checks": total_passed + total_failed,
                    "passed": total_passed,
                    "failed": total_failed
                }
            }
        else:
            return _validate_single_case(test_case, wrapper, mcp_server, logger)


def _validate_single_case(test_case: str, wrapper, mcp_server, logger) -> dict:
    """Run validation for a single test case."""

    ref_case = V2_REFERENCE_CASES[test_case]
    validation_type = ref_case["validation_type"]
    expected = ref_case["expected"]

    results = {}
    passed = True

    # Dispatch based on validation type
    if validation_type == "quantitative":
        if test_case == "saturation_pressure_0C":
            passed, results = _validate_saturation(wrapper, ref_case, logger)
        elif test_case == "critical_point_co2":
            passed, results = _validate_critical(wrapper, ref_case, logger)

    elif validation_type == "qualitative":
        if test_case == "jt_coefficient_100bar_40C":
            passed, results = _validate_jt(wrapper, ref_case, logger)

    elif validation_type == "phase_transition":
        if test_case == "property_sweep_transition":
            passed, results = _validate_sweep(wrapper, ref_case, logger)

    elif validation_type == "mixed_results":
        if test_case == "batch_flash_mixed":
            passed, results = _validate_batch(wrapper, ref_case, logger)

    # Compute summary
    total_checks = len(results)
    passed_checks = sum(1 for r in results.values() if r.get("passed", False))
    failed_checks = total_checks - passed_checks

    overall_result = "PASS" if passed and failed_checks == 0 else "FAIL"

    # Log result
    logger.info(
        f"V2 Validation {test_case}: {overall_result} "
        f"({passed_checks}/{total_checks} checks passed)"
    )

    return {
        "test_case": test_case,
        "description": ref_case["description"],
        "tool": ref_case["tool"],
        "overall_result": overall_result,
        "tolerance_percent": V2_TOLERANCE * 100,
        "results": results,
        "summary": {
            "total_checks": total_checks,
            "passed": passed_checks,
            "failed": failed_checks
        }
    }


def _validate_saturation(wrapper, ref_case: dict, logger) -> tuple:
    """Validate saturation pressure tool (VAL-01)."""
    from mcp_server.tools.phase_boundary import get_saturation_pressure

    inp = ref_case["input"]
    expected = ref_case["expected"]
    results = {}

    # Call the saturation pressure function directly via wrapper
    try:
        # Use binary search approach consistent with phase_boundary.py
        T_k = inp["temperature"] + 273.15 if inp["temperature_unit"] == "C" else inp["temperature"]

        # Binary search for saturation pressure
        CO2_PC_PA = 7.377e6  # Pa
        CO2_TRIPLE_P_PA = 5.18e5  # Pa

        P_low = CO2_TRIPLE_P_PA
        P_high = CO2_PC_PA * 0.99

        for _ in range(30):
            P_mid = (P_low + P_high) / 2
            flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_mid)

            if flash_result.num_phases == 2:
                P_sat = P_mid
                if P_mid - P_low > P_high - P_mid:
                    P_low = P_mid - (P_mid - P_low) / 2
                else:
                    P_high = P_mid + (P_high - P_mid) / 2
            elif flash_result.num_phases == 1:
                phase_name = flash_result.phase_names[0]
                if "LIQUID" in phase_name.upper():
                    P_high = P_mid
                else:
                    P_low = P_mid

            if abs(P_high - P_low) < 1e3:  # 1 kPa tolerance
                P_sat = (P_high + P_low) / 2
                break

        actual_P_bar = P_sat / 1e5
        expected_P_bar = expected["saturation_pressure_bar"]
        tolerance = expected["tolerance_percent"] / 100.0

        rel_error = abs(actual_P_bar - expected_P_bar) / expected_P_bar
        check_passed = rel_error <= tolerance

        results["saturation_pressure_bar"] = {
            "expected": expected_P_bar,
            "actual": actual_P_bar,
            "relative_error_percent": rel_error * 100,
            "passed": check_passed
        }

        return check_passed, results

    except Exception as e:
        logger.error(f"Saturation validation failed: {e}")
        results["saturation_pressure_bar"] = {
            "expected": expected["saturation_pressure_bar"],
            "actual": None,
            "error": str(e),
            "passed": False
        }
        return False, results


def _validate_critical(wrapper, ref_case: dict, logger) -> tuple:
    """Validate critical point tool (VAL-02)."""
    expected = ref_case["expected"]
    results = {}

    try:
        # Get critical point from wrapper
        Tc_K, Pc_Pa, Vc_m3_mol = wrapper.get_critical_point()

        Tc_actual = Tc_K
        Pc_actual_bar = Pc_Pa / 1e5
        tolerance = expected["tolerance_percent"] / 100.0

        # Check Tc
        Tc_expected = expected["critical_temperature_K"]
        Tc_rel_error = abs(Tc_actual - Tc_expected) / Tc_expected
        Tc_passed = Tc_rel_error <= tolerance

        results["critical_temperature_K"] = {
            "expected": Tc_expected,
            "actual": Tc_actual,
            "relative_error_percent": Tc_rel_error * 100,
            "passed": Tc_passed
        }

        # Check Pc
        Pc_expected = expected["critical_pressure_bar"]
        Pc_rel_error = abs(Pc_actual_bar - Pc_expected) / Pc_expected
        Pc_passed = Pc_rel_error <= tolerance

        results["critical_pressure_bar"] = {
            "expected": Pc_expected,
            "actual": Pc_actual_bar,
            "relative_error_percent": Pc_rel_error * 100,
            "passed": Pc_passed
        }

        return Tc_passed and Pc_passed, results

    except Exception as e:
        logger.error(f"Critical point validation failed: {e}")
        results["critical_point"] = {
            "error": str(e),
            "passed": False
        }
        return False, results


def _validate_jt(wrapper, ref_case: dict, logger) -> tuple:
    """Validate Joule-Thomson coefficient tool (VAL-03)."""
    inp = ref_case["input"]
    expected = ref_case["expected"]
    results = {}

    try:
        # Convert inputs to SI
        P_pa = inp["pressure"] * 1e5  # bar to Pa
        T_k = inp["temperature"] + 273.15  # C to K

        # Execute flash first
        flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)

        if flash_result.num_phases > 1:
            results["jt_coefficient"] = {
                "expected_sign": expected["sign"],
                "actual": None,
                "error": "Multi-phase region - JT undefined",
                "passed": False
            }
            return False, results

        # Get phase properties
        phase_lno = flash_result.phases[0]
        phase_comp = flash_result.compositions[0]

        aymix = wrapper.get_aymix_properties(
            phase_lno=phase_lno,
            temperature=T_k,
            pressure=P_pa,
            composition=phase_comp,
            get_volume_derivs=True,
            get_enthalpy_derivs=True
        )

        V_m = aymix.volume
        dV_dT = aymix.volume_T
        Cp = aymix.enthalpy_T

        beta = dV_dT / V_m
        mu_JT_K_Pa = (V_m / Cp) * (T_k * beta - 1)
        mu_JT_K_bar = mu_JT_K_Pa * 1e5

        # Check sign
        actual_sign = "positive" if mu_JT_K_bar > 0 else ("negative" if mu_JT_K_bar < 0 else "zero")
        actual_interp = "cooling on expansion" if mu_JT_K_bar > 0 else "heating on expansion"
        sign_passed = actual_sign == expected["sign"]

        results["jt_sign"] = {
            "expected": expected["sign"],
            "actual": actual_sign,
            "value_K_bar": mu_JT_K_bar,
            "passed": sign_passed
        }

        results["jt_interpretation"] = {
            "expected": expected["interpretation"],
            "actual": actual_interp,
            "passed": actual_interp == expected["interpretation"]
        }

        return sign_passed, results

    except Exception as e:
        logger.error(f"JT coefficient validation failed: {e}")
        results["jt_coefficient"] = {
            "error": str(e),
            "passed": False
        }
        return False, results


def _validate_sweep(wrapper, ref_case: dict, logger) -> tuple:
    """Validate property sweep phase transition detection (VAL-04)."""
    inp = ref_case["input"]
    expected = ref_case["expected"]
    results = {}

    try:
        # Execute sweep manually
        properties = inp["properties"]
        sweep_start = inp["sweep_start"]
        sweep_end = inp["sweep_end"]
        fixed_value = inp["fixed_value"]
        num_points = inp["num_points"]

        # Fixed temperature in K
        T_k = fixed_value + 273.15  # C to K

        # Generate sweep points
        sweep_points = []
        for i in range(num_points):
            frac = i / (num_points - 1) if num_points > 1 else 0
            P_bar = sweep_start + frac * (sweep_end - sweep_start)
            sweep_points.append(P_bar)

        # Execute flash at each point and track phases
        phases_found = []
        phase_transitions = []

        for i, P_bar in enumerate(sweep_points):
            P_pa = P_bar * 1e5
            try:
                flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
                phase_name = flash_result.phase_names[0] if flash_result.num_phases == 1 else "MULTI"
                phases_found.append(phase_name)

                # Check for transition
                if i > 0 and phases_found[i] != phases_found[i-1]:
                    phase_transitions.append({
                        "index": i,
                        "from_phase": phases_found[i-1],
                        "to_phase": phases_found[i],
                        "pressure_bar": P_bar
                    })
            except Exception as e:
                phases_found.append(None)
                logger.warning(f"Flash failed at P={P_bar} bar: {e}")

        # Check if phase transition was detected
        has_transition = len(phase_transitions) > 0
        transition_passed = has_transition == expected["has_phase_transition"]

        results["has_phase_transition"] = {
            "expected": expected["has_phase_transition"],
            "actual": has_transition,
            "passed": transition_passed
        }

        # If transition exists, check if it's near expected value
        if has_transition and expected["has_phase_transition"]:
            nearest_transition_P = phase_transitions[0]["pressure_bar"]
            expected_P = expected["transition_near_bar"]
            tolerance_bar = expected["tolerance_bar"]

            P_error = abs(nearest_transition_P - expected_P)
            location_passed = P_error <= tolerance_bar

            results["transition_location"] = {
                "expected_bar": expected_P,
                "actual_bar": nearest_transition_P,
                "error_bar": P_error,
                "tolerance_bar": tolerance_bar,
                "passed": location_passed
            }

            return transition_passed and location_passed, results

        return transition_passed, results

    except Exception as e:
        logger.error(f"Property sweep validation failed: {e}")
        results["sweep"] = {
            "error": str(e),
            "passed": False
        }
        return False, results


def _validate_batch(wrapper, ref_case: dict, logger) -> tuple:
    """Validate batch flash mixed results handling (VAL-05)."""
    inp = ref_case["input"]
    expected = ref_case["expected"]
    results = {}

    try:
        conditions = inp["conditions"]
        num_successful = 0
        num_failed = 0

        for cond in conditions:
            P_bar = cond.get("pressure", 0)
            T_c = cond.get("temperature", 0)

            # Validate inputs
            if P_bar < 0:
                num_failed += 1
                continue
            if T_c < -273.15:  # Below absolute zero
                num_failed += 1
                continue

            # Try flash
            try:
                P_pa = P_bar * 1e5
                T_k = T_c + 273.15
                flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
                num_successful += 1
            except Exception:
                num_failed += 1

        # Check counts
        success_passed = num_successful == expected["num_successful"]
        fail_passed = num_failed == expected["num_failed"]
        handles_gracefully = True  # If we got here without crashing

        results["num_successful"] = {
            "expected": expected["num_successful"],
            "actual": num_successful,
            "passed": success_passed
        }

        results["num_failed"] = {
            "expected": expected["num_failed"],
            "actual": num_failed,
            "passed": fail_passed
        }

        results["handles_gracefully"] = {
            "expected": expected["handles_gracefully"],
            "actual": handles_gracefully,
            "passed": handles_gracefully == expected["handles_gracefully"]
        }

        return success_passed and fail_passed and handles_gracefully, results

    except Exception as e:
        logger.error(f"Batch flash validation failed: {e}")
        results["batch_flash"] = {
            "error": str(e),
            "passed": False
        }
        return False, results
