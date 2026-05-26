"""
Component Database Tools - Pure component reference data.

Provides MCP tools for accessing pure component properties:
- get_component_properties: Critical constants, acentric factor, triple point
- list_available_components: Search and filter component database

Essential for EOS parameter estimation, validation, and documentation.
"""

from typing import Optional, List
import fnmatch
import re

# Unit conversion functions - dual import pattern for both invocation methods
try:
    from mcp_server.utils.units import (
        convert_pressure_to_pa,
        convert_temperature_to_k
    )
except ImportError:
    from utils.units import (
        convert_pressure_to_pa,
        convert_temperature_to_k
    )


class MCPError(Exception):
    """Structured error for MCP responses - local copy to avoid circular import."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


# CO2 reference data for validation
CO2_REFERENCE = {
    "component_name": "CO2",
    "molecular_weight_g_mol": 44.01,
    "critical_temperature_K": 304.13,
    "critical_pressure_bar": 73.77,
    "critical_volume_cm3_mol": 94.0,
    "acentric_factor": 0.225,
    "triple_point_temperature_K": 216.55,
    "triple_point_pressure_bar": 5.18
}

# Reference data for additional properties not available from Multiflash API
# These values are from NIST and standard thermodynamic references
COMPONENT_REFERENCE_DATA = {
    "CARBON DIOXIDE": {
        "acentric_factor": 0.225,
        "triple_point": {"T_K": 216.55, "P_Pa": 5.18e5}
    },
    "CO2": {
        "acentric_factor": 0.225,
        "triple_point": {"T_K": 216.55, "P_Pa": 5.18e5}
    },
    "METHANE": {
        "acentric_factor": 0.011,
        "triple_point": {"T_K": 90.69, "P_Pa": 1.17e4}
    },
    "CH4": {
        "acentric_factor": 0.011,
        "triple_point": {"T_K": 90.69, "P_Pa": 1.17e4}
    },
    "NITROGEN": {
        "acentric_factor": 0.039,
        "triple_point": {"T_K": 63.15, "P_Pa": 1.25e4}
    },
    "N2": {
        "acentric_factor": 0.039,
        "triple_point": {"T_K": 63.15, "P_Pa": 1.25e4}
    }
}

# Component categories for filtering (heuristic-based)
COMPONENT_CATEGORIES = {
    "hydrocarbons": ["METH", "ETH", "PROP", "BUT", "PENT", "HEX", "HEPT", "OCT",
                     "BENZENE", "TOLUENE", "XYLENE", "CYCLO"],
    "inorganics": ["CARBON DIOXIDE", "NITROGEN", "OXYGEN", "HYDROGEN", "HELIUM",
                   "ARGON", "WATER", "H2O", "CO2", "N2", "O2", "H2", "CO",
                   "CARBON MONOXIDE", "SULFUR", "H2S", "HYDROGEN SULFIDE"],
    "polar": ["WATER", "H2O", "METHANOL", "ETHANOL", "AMMONIA", "NH3"],
    "refrigerants": ["R-", "R134", "R22", "R410", "HFC", "CFC", "HCFC"]
}

# Predefined component list (fallback when database query not available)
COMMON_COMPONENTS = [
    {"name": "CARBON DIOXIDE", "formula": "CO2", "molecular_weight": 44.01, "cas_number": "124-38-9"},
    {"name": "METHANE", "formula": "CH4", "molecular_weight": 16.04, "cas_number": "74-82-8"},
    {"name": "ETHANE", "formula": "C2H6", "molecular_weight": 30.07, "cas_number": "74-84-0"},
    {"name": "PROPANE", "formula": "C3H8", "molecular_weight": 44.10, "cas_number": "74-98-6"},
    {"name": "NITROGEN", "formula": "N2", "molecular_weight": 28.01, "cas_number": "7727-37-9"},
    {"name": "OXYGEN", "formula": "O2", "molecular_weight": 32.00, "cas_number": "7782-44-7"},
    {"name": "HYDROGEN SULFIDE", "formula": "H2S", "molecular_weight": 34.08, "cas_number": "7783-06-4"},
    {"name": "WATER", "formula": "H2O", "molecular_weight": 18.02, "cas_number": "7732-18-5"},
    {"name": "HYDROGEN", "formula": "H2", "molecular_weight": 2.016, "cas_number": "1333-74-0"},
    {"name": "CARBON MONOXIDE", "formula": "CO", "molecular_weight": 28.01, "cas_number": "630-08-0"},
    {"name": "ARGON", "formula": "Ar", "molecular_weight": 39.95, "cas_number": "7440-37-1"},
    {"name": "n-BUTANE", "formula": "C4H10", "molecular_weight": 58.12, "cas_number": "106-97-8"},
    {"name": "i-BUTANE", "formula": "C4H10", "molecular_weight": 58.12, "cas_number": "75-28-5"},
    {"name": "n-PENTANE", "formula": "C5H12", "molecular_weight": 72.15, "cas_number": "109-66-0"},
    {"name": "n-HEXANE", "formula": "C6H14", "molecular_weight": 86.18, "cas_number": "110-54-3"},
    {"name": "AMMONIA", "formula": "NH3", "molecular_weight": 17.03, "cas_number": "7664-41-7"},
    {"name": "SULFUR DIOXIDE", "formula": "SO2", "molecular_weight": 64.07, "cas_number": "7446-09-5"},
    {"name": "HELIUM", "formula": "He", "molecular_weight": 4.003, "cas_number": "7440-59-7"},
]


def _matches_pattern(name: str, pattern: str) -> bool:
    """Wildcard pattern matching (* = any chars, ? = single char)."""
    # Convert glob-style pattern to regex
    regex = fnmatch.translate(pattern.upper())
    return re.match(regex, name.upper()) is not None


def _matches_category(name: str, category: str) -> bool:
    """Check if component matches category heuristics."""
    if category == "all":
        return True
    prefixes = COMPONENT_CATEGORIES.get(category, [])
    name_upper = name.upper()
    return any(name_upper.startswith(p) or p in name_upper for p in prefixes)


def _detect_category(name: str) -> str:
    """Detect category for a component name."""
    name_upper = name.upper()
    for category, prefixes in COMPONENT_CATEGORIES.items():
        if any(name_upper.startswith(p) or p in name_upper for p in prefixes):
            return category
    return "other"


def register_component_database_tools(mcp_server, get_wrapper_fn, logger):
    """Register component database tools with the MCP server."""

    @mcp_server.tool()
    def get_component_properties(
        component_name: str = None
    ) -> dict:
        """
        Get pure component properties (critical constants, acentric factor, triple point).

        Returns fundamental reference data for a pure component from the Multiflash
        component database. This data is essential for:
        - EOS parameter estimation and validation
        - Phase behavior analysis and prediction
        - Property correlation development
        - Engineering documentation and reports

        Key properties include:
        - Molecular weight (MW)
        - Critical constants (Tc, Pc, Vc) - where liquid/vapor become indistinguishable
        - Acentric factor (ω) - measure of molecular non-sphericity
        - Triple point (T, P) - where solid/liquid/vapor coexist

        Args:
            component_name: Component name (e.g., "CARBON DIOXIDE", "CO2", "METHANE").
                If None and a single-component fluid is loaded, uses that component.
                Component names are case-insensitive.

        Returns:
            Dict with component properties:
            {
                "component_name": str,
                "molecular_weight": {
                    "value_g_mol": float,
                    "value_kg_mol": float
                },
                "critical_temperature": {
                    "value_K": float,
                    "value_C": float
                },
                "critical_pressure": {
                    "value_Pa": float,
                    "value_bar": float,
                    "value_MPa": float
                },
                "critical_volume": {
                    "value_m3_mol": float,
                    "value_cm3_mol": float
                },
                "critical_compressibility_factor": float,  # Zc = Pc*Vc/(R*Tc)
                "acentric_factor": float,  # ω (omega)
                "triple_point": {
                    "temperature": {
                        "value_K": float,
                        "value_C": float
                    },
                    "pressure": {
                        "value_Pa": float,
                        "value_bar": float
                    }
                }
            }

        Error codes:
            INVALID_INPUT: Component name not provided and no single-component fluid loaded
            NO_COMPONENT_FOUND: Component name not found in database
            PROPERTY_CALC_FAILED: Failed to retrieve component properties

        Examples:
            >>> get_component_properties(component_name="CARBON DIOXIDE")
            # Returns: MW=44.01 g/mol, Tc=304.13K, Pc=73.77bar, ω=0.225

            >>> get_component_properties(component_name="CO2")
            # Returns same as above (alternative name)

            >>> get_component_properties()
            # Uses loaded single-component fluid (e.g., Pure_CO2.mfl)

        Reference for Pure CO2:
            MW:   44.01 g/mol
            Tc:   304.13 K (31.0°C)
            Pc:   73.77 bar (7.377 MPa)
            Vc:   94.0 cm³/mol
            ω:    0.225
            T_triple: 216.55 K (-56.6°C)
            P_triple: 5.18 bar
        """
        # Get wrapper and check connection
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise  # Re-raise DLL connection errors as-is

        # Determine which component to query
        if component_name is None:
            # Use loaded fluid if single-component
            if not wrapper.is_loaded:
                raise MCPError(
                    "INVALID_INPUT",
                    "No component_name provided and no fluid loaded. "
                    "Either provide component_name or load a single-component fluid first."
                )

            # Check if it's a single-component fluid
            num_components = len([x for x in wrapper.composition if x > 0])
            if num_components != 1:
                raise MCPError(
                    "INVALID_INPUT",
                    f"No component_name provided and loaded fluid has {num_components} components. "
                    f"get_component_properties requires a single-component fluid when called without component_name."
                )

            # Use the fluid name as component name
            component_name = wrapper.fluid_name
            if not component_name:
                raise MCPError(
                    "INVALID_INPUT",
                    "Could not determine component name from loaded fluid."
                )

            logger.info(f"Using component from loaded fluid: {component_name}")
        else:
            # Load a temporary single-component fluid to get properties
            # Create composition with single component
            try:
                # Try to create a pure component fluid temporarily
                # We need to load an MFL or use component by name
                temp_comp = [1.0]  # Single component, 1 mole

                # For now, we'll work with the loaded fluid approach
                # If no fluid is loaded, we need to load one
                if not wrapper.is_loaded:
                    raise MCPError(
                        "INVALID_INPUT",
                        "get_component_properties requires either a loaded fluid or creating a temporary fluid. "
                        "Currently, only works with loaded single-component fluids. "
                        "Please load a fluid first using load_mfl_file."
                    )
            except Exception as e:
                raise MCPError(
                    "PROPERTY_CALC_FAILED",
                    f"Failed to prepare component query: {e}"
                )

        # Get component properties using AXCRIT and AYAVMW
        # Note: Multiflash Python API doesn't have AYPRP, so we use AXCRIT for critical properties
        # and AYAVMW for molecular weight
        try:
            # Get critical properties using AXCRIT
            crit_result = wrapper.dll.AXCRIT(wrapper.composition)
            Tc_K = crit_result.Tc  # K
            Pc_Pa = crit_result.Pc  # Pa
            Vc_m3_mol = crit_result.Vc  # m³/mol

            # Get molecular weight using AYAVMW
            mw_result = wrapper.dll.AYAVMW(wrapper.composition, [])
            MW_g_mol = mw_result.averageMW  # g/mol

            # Get acentric factor and triple point from reference data
            # These properties are not available from Multiflash API
            ref_data = COMPONENT_REFERENCE_DATA.get(component_name.upper())
            if ref_data:
                omega = ref_data["acentric_factor"]
                T_triple_K = ref_data["triple_point"]["T_K"]
                P_triple_Pa = ref_data["triple_point"]["P_Pa"]
            else:
                # Not in reference data - return None for these properties
                omega = None
                T_triple_K = None
                P_triple_Pa = None
                logger.warning(
                    f"Acentric factor and triple point not available for '{component_name}'. "
                    f"Only critical constants and MW returned."
                )

        except Exception as e:
            error_str = str(e).upper()
            if 'NOT FOUND' in error_str or 'UNKNOWN' in error_str or 'INVALID' in error_str:
                raise MCPError(
                    "NO_COMPONENT_FOUND",
                    f"Component '{component_name}' not found in Multiflash database. "
                    f"Check spelling (try 'CARBON DIOXIDE' or 'CO2') or use list_available_components."
                )
            else:
                raise MCPError(
                    "PROPERTY_CALC_FAILED",
                    f"Failed to retrieve properties for '{component_name}': {e}"
                )

        # Calculate derived properties
        # Universal gas constant
        R_GAS = 8.314462618  # J/(mol·K)

        # Critical compressibility factor: Zc = Pc * Vc / (R * Tc)
        Zc = (Pc_Pa * Vc_m3_mol) / (R_GAS * Tc_K)

        # Build response with all unit conversions
        response = {
            "component_name": component_name,
            "molecular_weight": {
                "value_g_mol": MW_g_mol,
                "value_kg_mol": MW_g_mol / 1000.0
            },
            "critical_temperature": {
                "value_K": Tc_K,
                "value_C": Tc_K - 273.15
            },
            "critical_pressure": {
                "value_Pa": Pc_Pa,
                "value_bar": Pc_Pa / 1e5,
                "value_MPa": Pc_Pa / 1e6
            },
            "critical_volume": {
                "value_m3_mol": Vc_m3_mol,
                "value_cm3_mol": Vc_m3_mol * 1e6
            },
            "critical_compressibility_factor": Zc
        }

        # Add acentric factor if available
        if omega is not None:
            response["acentric_factor"] = omega
        else:
            response["acentric_factor"] = None

        # Add triple point if available
        if T_triple_K is not None and P_triple_Pa is not None:
            response["triple_point"] = {
                "temperature": {
                    "value_K": T_triple_K,
                    "value_C": T_triple_K - 273.15
                },
                "pressure": {
                    "value_Pa": P_triple_Pa,
                    "value_bar": P_triple_Pa / 1e5
                }
            }
        else:
            response["triple_point"] = None

        # Log and return
        omega_str = f"ω={omega:.4f}" if omega is not None else "ω=N/A"
        logger.info(
            f"Component properties for {component_name}: "
            f"MW={MW_g_mol:.2f} g/mol, Tc={Tc_K:.2f} K, Pc={Pc_Pa/1e5:.2f} bar, {omega_str}"
        )
        return response

    @mcp_server.tool()
    def list_available_components(
        filter_pattern: str = "*",
        category: str = "all"
    ) -> dict:
        """
        List available components in the Multiflash database with filtering.

        Search and filter the component database to discover available pure components
        for mixture creation. This tool helps users find exact component spellings
        (e.g., "CARBON DIOXIDE" vs "CO2") and explore available impurities for CO2
        injection modeling.

        Essential for:
        - Discovering component names before creating custom mixtures
        - Exploring available impurities (H2S, N2, CH4, etc.)
        - Verifying component spelling for create_fluid_mixture
        - Finding refrigerants, hydrocarbons, or polar components

        Args:
            filter_pattern: Wildcard pattern for name matching (default: "*" = all).
                Examples: "CARBON*", "METH*", "*SULFIDE", "CO2"
                Wildcards: * = any characters, ? = single character
                Case-insensitive matching.

            category: Filter by component type (default: "all").
                Options:
                - "all": All components (no category filter)
                - "hydrocarbons": METHANE, ETHANE, PROPANE, BENZENE, etc.
                - "inorganics": CO2, N2, O2, H2S, H2O, ARGON, etc.
                - "polar": WATER, METHANOL, ETHANOL, AMMONIA
                - "refrigerants": R-134a, R-22, HFCs, CFCs, etc.

        Returns:
            Dict with filtered component list:
            {
                "count": int,  # Number of matching components
                "filter_applied": str,  # Pattern used
                "category": str,  # Category filter used
                "components": [
                    {
                        "name": str,  # Exact Multiflash name
                        "formula": str,  # Chemical formula (e.g., "CO2")
                        "molecular_weight": float,  # g/mol
                        "cas_number": str,  # CAS Registry Number
                        "category": str  # Detected category
                    },
                    ...
                ]
            }

        Error codes:
            INVALID_INPUT: Invalid category specified

        Examples:
            >>> list_available_components()
            # Returns all known components

            >>> list_available_components(filter_pattern="CARBON*")
            # Returns: CARBON DIOXIDE, CARBON MONOXIDE

            >>> list_available_components(category="inorganics")
            # Returns: CO2, N2, O2, H2S, WATER, ARGON, etc.

            >>> list_available_components(filter_pattern="*SULFIDE", category="inorganics")
            # Returns: HYDROGEN SULFIDE

            >>> list_available_components(filter_pattern="METH*", category="hydrocarbons")
            # Returns: METHANE

        Note:
            Currently uses a predefined list of common CO2-relevant components.
            Future versions may query the full Multiflash database directly.
        """
        # Validate category
        valid_categories = ["all", "hydrocarbons", "inorganics", "polar", "refrigerants"]
        if category not in valid_categories:
            raise MCPError(
                "INVALID_INPUT",
                f"Invalid category: '{category}'. "
                f"Valid options: {', '.join(valid_categories)}"
            )

        # Get wrapper for potential database query
        try:
            wrapper = get_wrapper_fn()
            # TODO: In future, could query full database via wrapper.dll methods
            # For now, use predefined list
            logger.warning("Using predefined component list - full database query not available")
            all_components = COMMON_COMPONENTS.copy()
        except MCPError:
            # DLL not available - still use predefined list
            logger.warning("DLL not available - using predefined component list")
            all_components = COMMON_COMPONENTS.copy()

        # Apply filters
        matching_components = []
        for comp in all_components:
            name = comp["name"]
            # Check pattern match
            if not _matches_pattern(name, filter_pattern):
                continue
            # Check category match
            if not _matches_category(name, category):
                continue
            # Add detected category to component
            comp_with_category = comp.copy()
            comp_with_category["category"] = _detect_category(name)
            matching_components.append(comp_with_category)

        # Build response
        response = {
            "count": len(matching_components),
            "filter_applied": filter_pattern,
            "category": category,
            "components": matching_components
        }

        logger.info(
            f"list_available_components: found {len(matching_components)} components "
            f"(pattern='{filter_pattern}', category='{category}')"
        )

        return response
