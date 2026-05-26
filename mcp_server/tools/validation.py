"""
Validation Tool - Verify MCP server against known reference cases.

Provides MCP tool:
- run_validation: Compare server output against published / Multiflash-internal
  reference values for pure CO2.

This tool gives engineers confidence that the Multiflash integration is wired
correctly. The reference numbers below were obtained from a direct Multiflash
calculation on Pure_CO2.mfl at 50 bar / 277 K (liquid) and 10 bar / 350 K (gas).
They sit close to standard CO2 literature values (NIST REFPROP, Span-Wagner
EOS for liquid CO2 ~ 868 kg/m^3 at this state) and serve only as a smoke check
that the wrapper still returns physically reasonable values.
"""

from typing import Optional


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

# Reference values from a direct Multiflash calculation on Pure_CO2.mfl.
# Liquid case is consistent with literature CO2 density at 50 bar / 277 K
# (Span-Wagner / NIST REFPROP give ~868 kg/m^3); see DATA_AND_LICENSE.md for
# the reproducibility note. Gas case uses qualitative bounds (Z>0.9, low rho).
REFERENCE_CASES = {
    "liquid_co2_50bar_277K": {
        "description": "Pure CO2 in liquid phase",
        "conditions": {
            "pressure_bar": 50.0,
            "temperature_K": 277.0,
            "temperature_C": 4.0
        },
        "expected_phase": "LIQUID1",  # Exact phase name from Multiflash
        "expected_values": {
            # Multiflash @ Pure_CO2.mfl, 50 bar / 277 K, single liquid phase.
            "density_kg_m3": 868.35,
            "molecular_weight_g_mol": 44.01,
            "compressibility_factor": 0.1100,
            "isothermal_compressibility_1_bar": 1.689e-3,
            "thermal_expansion_1_K": 1.007e-2,
        }
    },
    "gas_co2_10bar_350K": {
        "description": "Pure CO2 in gas phase",
        "conditions": {
            "pressure_bar": 10.0,
            "temperature_K": 350.0,
            "temperature_C": 77.0
        },
        "expected_phase": "GAS",
        "expected_values": {
            # Gas phase at low pressure - less dense, higher Z
            # For gas at low pressure, we verify qualitative relationships:
            # - Z factor should be > 0.9 (nearly ideal gas)
            # - Density much lower than liquid (<50 kg/m3 vs ~850+ for liquid)
            "density_kg_m3": None,  # Will verify < 50
            "molecular_weight_g_mol": 44.01,  # Same MW
            "compressibility_factor": None,  # Will verify > 0.9
            "isothermal_compressibility_1_bar": None,  # Higher than liquid
            "thermal_expansion_1_K": None  # Different from liquid
        }
    }
}

TOLERANCE = 0.01  # 1% relative error tolerance


def register_validation_tools(mcp_server, get_wrapper_fn, logger):
    """Register validation tools with the MCP server."""

    @mcp_server.tool()
    def run_validation(test_case: str = "all") -> dict:
        """
        Run validation against known test cases to verify MCP server accuracy.

        This tool validates that the MCP server returns physically reasonable
        property values for pure CO2 by comparing against published / Multiflash
        reference values (see module docstring). It is a smoke check, not a
        substitute for engineering validation against the operating composition.

        Use this to verify that:
        - Multiflash integration is working correctly
        - Property calculations match expected values
        - Phase detection is accurate
        - Unit conversions are correct

        Args:
            test_case: Which test to run (default: "all")
                - "liquid_co2_50bar_277K": Liquid CO2 at 50 bar, 4°C
                - "gas_co2_10bar_350K": Gas CO2 at 10 bar, 77°C
                - "all": Run all test cases

        Returns:
            Dict with validation results:
            {
                "test_case": str,
                "conditions": {...},
                "overall_result": "PASS" or "FAIL",
                "tolerance_percent": float,
                "results": {
                    "phase_detection": {"expected": str, "actual": str, "passed": bool},
                    "density_kg_m3": {"expected": float, "actual": float,
                                     "relative_error_percent": float, "passed": bool},
                    ...
                },
                "summary": {"total_checks": int, "passed": int, "failed": int}
            }

            For "all" mode, returns list of individual results plus aggregate summary.

        Error codes:
            INVALID_INPUT: Unknown test_case
            NO_FLUID_LOADED: Pure_CO2.mfl must be loaded first
            VALIDATION_FAILED: Flash or property calculation failed

        Examples:
            >>> run_validation("liquid_co2_50bar_277K")
            # Validates liquid CO2 properties against Excel reference

            >>> run_validation("all")
            # Runs all validation tests
        """
        # Validate test_case parameter
        valid_cases = list(REFERENCE_CASES.keys()) + ["all"]
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

        # Check that Pure CO2 is loaded
        if wrapper.fluid_name and "CO2" not in wrapper.fluid_name.upper():
            logger.warning(
                f"Validation expects Pure_CO2.mfl, but {wrapper.fluid_name} is loaded. "
                f"Results may not match reference values."
            )

        # Run validation
        if test_case == "all":
            results = []
            for case_name in REFERENCE_CASES.keys():
                result = _validate_single_case(case_name, wrapper, logger)
                results.append(result)

            # Aggregate summary
            total_passed = sum(r["summary"]["passed"] for r in results)
            total_failed = sum(r["summary"]["failed"] for r in results)
            overall_pass = all(r["overall_result"] == "PASS" for r in results)

            return {
                "test_mode": "all",
                "cases_run": len(results),
                "overall_result": "PASS" if overall_pass else "FAIL",
                "tolerance_percent": TOLERANCE * 100,
                "results": results,
                "aggregate_summary": {
                    "total_checks": total_passed + total_failed,
                    "passed": total_passed,
                    "failed": total_failed
                }
            }
        else:
            return _validate_single_case(test_case, wrapper, logger)


def _validate_single_case(test_case: str, wrapper, logger) -> dict:
    """Run validation for a single test case."""

    ref_case = REFERENCE_CASES[test_case]
    conditions = ref_case["conditions"]
    expected_phase = ref_case["expected_phase"]
    expected_values = ref_case["expected_values"]

    # Convert conditions to SI
    P_pa = conditions["pressure_bar"] * 1e5
    T_k = conditions["temperature_K"]

    # Run flash
    try:
        flash_result = wrapper.pt_flash(temperature=T_k, pressure=P_pa)
    except Exception as e:
        raise MCPError(
            "VALIDATION_FAILED",
            f"Flash calculation failed for {test_case}: {e}"
        )

    # Check single phase
    if flash_result.num_phases > 1:
        raise MCPError(
            "VALIDATION_FAILED",
            f"Expected single phase at {conditions}, but got {flash_result.num_phases} phases"
        )

    # Get phase info
    phase_lno = flash_result.phases[0]
    phase_name = flash_result.phase_names[0]
    composition = flash_result.compositions[0]

    # Get AYMIX properties
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
            "VALIDATION_FAILED",
            f"AYMIX calculation failed for {test_case}: {e}"
        )

    # Get molecular weight
    try:
        mw_kg_mol = wrapper.get_molecular_weight(composition=composition)
    except Exception as e:
        raise MCPError(
            "VALIDATION_FAILED",
            f"Molecular weight calculation failed for {test_case}: {e}"
        )

    # Calculate derived properties (same formulas as pvt_properties.py)
    V_m = aymix.volume          # m³/mol
    dV_dT = aymix.volume_T      # m³/(mol·K)
    dV_dP = aymix.volume_P      # m³/(mol·Pa)

    rho = mw_kg_mol / V_m  # kg/m³
    Z = (P_pa * V_m) / (R_GAS * T_k)
    Cv_Pa = -dV_dP / V_m  # 1/Pa
    Cv_bar = Cv_Pa * 1e5  # 1/bar
    beta = dV_dT / V_m  # 1/K
    mw_g_mol = mw_kg_mol * 1000  # g/mol

    # Validate results
    results = {}

    # Phase detection
    results["phase_detection"] = {
        "expected": expected_phase,
        "actual": phase_name,
        "passed": phase_name == expected_phase
    }

    # Property validations
    actual_properties = {
        "density_kg_m3": rho,
        "molecular_weight_g_mol": mw_g_mol,
        "compressibility_factor": Z,
        "isothermal_compressibility_1_bar": Cv_bar,
        "thermal_expansion_1_K": beta
    }

    for prop_name, actual_value in actual_properties.items():
        expected = expected_values[prop_name]

        if expected is None:
            # For gas case - qualitative checks
            if prop_name == "density_kg_m3":
                # Gas density should be much lower than liquid
                passed = actual_value < 50  # kg/m³
                results[prop_name] = {
                    "expected": "< 50 kg/m³ (gas)",
                    "actual": actual_value,
                    "passed": passed,
                    "note": "Qualitative check: gas density << liquid density"
                }
            elif prop_name == "compressibility_factor":
                # Gas at low pressure should have Z close to 1 (ideal gas)
                passed = actual_value > 0.9
                results[prop_name] = {
                    "expected": "> 0.9 (nearly ideal gas)",
                    "actual": actual_value,
                    "passed": passed,
                    "note": "Qualitative check: low pressure gas behaves ideally"
                }
            else:
                # For other properties, just record actual value
                results[prop_name] = {
                    "expected": "Not specified",
                    "actual": actual_value,
                    "passed": True,  # Don't fail on unspecified properties
                    "note": "Reference value not specified for gas phase"
                }
        else:
            # Quantitative check with tolerance
            rel_error = abs(actual_value - expected) / abs(expected) if expected != 0 else abs(actual_value)
            passed = rel_error <= TOLERANCE

            results[prop_name] = {
                "expected": expected,
                "actual": actual_value,
                "relative_error_percent": rel_error * 100,
                "passed": passed
            }

    # Compute summary
    total_checks = len(results)
    passed_checks = sum(1 for r in results.values() if r["passed"])
    failed_checks = total_checks - passed_checks

    overall_result = "PASS" if failed_checks == 0 else "FAIL"

    # Log result
    logger.info(
        f"Validation {test_case}: {overall_result} "
        f"({passed_checks}/{total_checks} checks passed)"
    )

    return {
        "test_case": test_case,
        "description": ref_case["description"],
        "conditions": conditions,
        "overall_result": overall_result,
        "tolerance_percent": TOLERANCE * 100,
        "results": results,
        "summary": {
            "total_checks": total_checks,
            "passed": passed_checks,
            "failed": failed_checks
        }
    }
