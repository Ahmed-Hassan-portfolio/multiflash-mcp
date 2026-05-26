"""
Fluid Loader Tools - Load thermodynamic fluid definitions from MFL files and text.

Provides MCP tools:
- load_mfl_file: Load MFL from a file path
- load_mfl_text: Load MFL from text content (creates temporary file)
- create_fluid_mixture: Create mixture from component list with mole fractions
"""
from typing import Optional, List
from pathlib import Path
import os
import tempfile


# Valid EOS models for create_fluid_mixture
EOS_MODELS = {
    "SRK": "Soave-Redlich-Kwong",
    "PR": "Peng-Robinson (original)",
    "PR78": "Peng-Robinson (1978)",
    "BWRS": "Benedict-Webb-Rubin-Starling",
    "GERG-2008": "GERG-2008 (natural gas reference)",
    "EOS-CG": "EOS-CG (CO2 mixtures)",
    "CPA": "Cubic-Plus-Association",
    "PC-SAFT": "Perturbed-Chain SAFT"
}


def _validate_eos_model(eos: str) -> str:
    """Validate and normalize EOS model name.

    Returns normalized EOS name or None if invalid.
    """
    eos_upper = eos.upper().replace(" ", "").replace("_", "-")

    # Handle common variations
    if eos_upper == "PENG-ROBINSON" or eos_upper == "PENGROBINSON":
        return "PR78"
    if eos_upper == "GERG" or eos_upper == "GERG2008":
        return "GERG-2008"
    if eos_upper == "EOSCG":
        return "EOS-CG"
    if eos_upper == "PCSAFT":
        return "PC-SAFT"

    # Check exact match (case-insensitive)
    for valid_eos in EOS_MODELS:
        if valid_eos.upper() == eos_upper:
            return valid_eos

    return None  # Invalid


def _generate_mfl_content(
    components: List[dict],
    eos_model: str,
    mixture_name: str
) -> str:
    """
    Generate MFL file content for a mixture.

    Uses Multiflash MFL syntax to define components, EOS model, and composition.
    Based on working MFL files from Multiflash 7.5.

    Args:
        components: List of {"name": str, "mole_fraction": float}
        eos_model: Validated EOS model name (PR78, SRK, etc.)
        mixture_name: Name for the mixture

    Returns:
        MFL file content as string
    """
    # Map EOS model to Multiflash model syntax
    eos_model_map = {
        "SRK": "MSRK",
        "PR": "MPR",
        "PR78": "MPR78",
        "BWRS": "MBWRS",
        "GERG-2008": "MGERG2008",
        "EOS-CG": "MEOSCG",
        "CPA": "MCPA",
        "PC-SAFT": "MPCSAFT"
    }
    mf_model = eos_model_map.get(eos_model, "MPR78")

    lines = [
        f"#Multiflash MFL - {mixture_name} - EOS: {eos_model}#",
        "remove all;",
        "units temperature K pressure Pa enthalpy J/mol entropy J/mol/K volume m3/mol",
        "amounts mol viscosity Pas thcond W/m/K surten N/m diffusion m2/s;",
        "datum enthalpy compound entropy compound;",
        "set fractions; chardata INFOCHAR TBSOEREIDE;",
        "puredata Infodata;",
        "chardata Infochar TbSoereide;",
        "Components overwrite"
    ]

    # Component definition - one per line, quote names with spaces
    for i, comp in enumerate(components):
        name = comp["name"].upper()
        # Quote names with spaces, leave simple names unquoted
        if " " in name:
            lines.append(f'{i+1} "{name}"')
        else:
            lines.append(f'{i+1} {name}')

    # End component list with semicolon on last line
    lines[-1] += " ;"

    # BIP data - use general INFOBIPS for broad compatibility
    lines.append("bipdata INFOBIPS;")
    lines.append("BipSet PR78BIP 1 constant eos none;")

    # Model definition
    if eos_model in ["PR78", "PR", "SRK"]:
        lines.append(f"model {mf_model} PRA PSAT78 LDEN VDW PR78BIP;")
    else:
        lines.append(f"model {mf_model};")
    lines.append("model VSuperTRAPP SPVISC LFIT;")
    lines.append("model TCSuperTRAPP SPTHCOND SPTHCOND;")

    # Phase definitions
    lines.append(f"PD GAS gas {mf_model} {mf_model} {mf_model} VSuperTRAPP TCSuperTRAPP;")
    lines.append(f"PD LIQUID1 liquid {mf_model} {mf_model} {mf_model} VSuperTRAPP TCSuperTRAPP;")
    lines.append('keys LIQUID1 "*";')
    lines.append(f"PD LIQUID2 liquid {mf_model} {mf_model} {mf_model} VSuperTRAPP TCSuperTRAPP;")
    lines.append('keys LIQUID2 "*";')

    # Composition (mole amounts that sum to 100)
    amounts = " ".join(str(comp["mole_fraction"] * 100) for comp in components)
    lines.append(f"amounts {amounts};")

    # Tolerance amounts - one zero per component
    tolamounts = " ".join("0." for _ in components)
    lines.append(f"tolamounts {tolamounts};")

    # Default conditions
    lines.append("Temperature 298.15;")
    lines.append("Pressure 100000;")

    # Output units
    lines.append("units temperature K pressure bar enthalpy J/mol entropy J/mol/K")
    lines.append("volume m3/mol density kg/m3 amounts mole viscosity Pas thcond W/m/K")
    lines.append("surten N/m diffusion m2/s GOR sm3/sm3;")
    lines.append("set physprops 2VCS;")

    return "\n".join(lines)


class MCPError(Exception):
    """Structured error for MCP responses - local copy to avoid circular import."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


def register_fluid_loader_tools(mcp_server, get_wrapper_fn, logger):
    """Register fluid loader tools with the MCP server."""

    @mcp_server.tool()
    def load_mfl_file(path: str) -> dict:
        """
        Load a Multiflash MFL file from disk.

        Args:
            path: Path to .mfl file (absolute or relative to CWD)

        Returns:
            Dict with fluid info: {
                "status": "loaded",
                "fluid_name": str,
                "num_components": int,
                "components": [component names],
                "replaced": str (optional, if replacing previous fluid)
            }

        Error codes:
            INVALID_INPUT: Empty path, path too long, or doesn't end with .mfl
            FILE_NOT_FOUND: MFL file doesn't exist at specified path
            INVALID_MFL: MFL file has syntax errors or Multiflash can't parse it
        """
        # Input validation
        if not path or not path.strip():
            raise MCPError("INVALID_INPUT", "Path cannot be empty")

        if len(path) > 1000:
            raise MCPError("INVALID_INPUT", "Path too long (max 1000 chars)")

        if not path.lower().endswith('.mfl'):
            raise MCPError("INVALID_INPUT", "File must have .mfl extension")

        # Resolve path relative to CWD
        resolved_path = Path(path).resolve()

        # Check file exists before calling wrapper
        if not resolved_path.exists():
            raise MCPError(
                "FILE_NOT_FOUND",
                f"MFL file not found: {resolved_path}\n"
                f"Please verify the file path is correct."
            )

        # Get wrapper and track previous fluid name
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise  # Re-raise DLL connection errors as-is

        previous_fluid = wrapper.fluid_name

        # Load MFL file
        try:
            result = wrapper.load_mfl(str(resolved_path))
        except FileNotFoundError as e:
            raise MCPError("FILE_NOT_FOUND", str(e))
        except RuntimeError as e:
            raise MCPError(
                "INVALID_MFL",
                f"Failed to load MFL file: {e}\n"
                f"The file may have syntax errors or be incompatible with Multiflash."
            )
        except Exception as e:
            raise MCPError("INVALID_MFL", f"Unexpected error loading MFL: {e}")

        # Extract component names from wrapper composition
        # Note: wrapper.composition is mole numbers, need component names from MFL
        # For now, return basic info from the load result
        fluid_name = Path(path).stem
        wrapper.fluid_name = fluid_name

        response = {
            "status": "loaded",
            "fluid_name": fluid_name,
            "num_components": result.get("num_components", 0),
            "components": [f"Component_{i+1}" for i in range(result.get("num_components", 0))]
        }

        # Add replacement notification if replacing previous fluid
        if previous_fluid is not None:
            response["replaced"] = previous_fluid
            logger.info(f"Replaced fluid '{previous_fluid}' with '{fluid_name}'")
        else:
            logger.info(f"Loaded fluid '{fluid_name}' ({response['num_components']} components)")

        return response

    @mcp_server.tool()
    def load_mfl_text(content: str, fluid_name: str = "CustomMixture") -> dict:
        """
        Load a Multiflash MFL from text content.

        Creates a temporary file, loads the MFL, then cleans up the temp file.

        Args:
            content: MFL file content as text
            fluid_name: Name to assign to this fluid (default: "CustomMixture")

        Returns:
            Dict with fluid info: {
                "status": "loaded",
                "fluid_name": str,
                "num_components": int,
                "components": [component names],
                "replaced": str (optional, if replacing previous fluid)
            }

        Error codes:
            INVALID_INPUT: Empty content or content too large (>1MB)
            INVALID_MFL: MFL content has syntax errors or Multiflash can't parse it
        """
        # Input validation
        if not content or not content.strip():
            raise MCPError("INVALID_INPUT", "Content cannot be empty")

        if len(content) > 1024 * 1024:  # 1MB limit
            raise MCPError("INVALID_INPUT", "Content too large (max 1MB)")

        # Get wrapper and track previous fluid name
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise  # Re-raise DLL connection errors as-is

        previous_fluid = wrapper.fluid_name

        # Create temporary file and load MFL
        temp_fd = None
        temp_path = None
        try:
            # Create temp file with .mfl extension
            temp_fd, temp_path = tempfile.mkstemp(suffix='.mfl', text=True)

            # Write content to temp file
            with os.fdopen(temp_fd, 'w') as f:
                f.write(content)
                temp_fd = None  # File handle closed by with block

            # Load MFL from temp file
            try:
                result = wrapper.load_mfl(temp_path)
            except FileNotFoundError as e:
                raise MCPError("INVALID_MFL", f"Temp file error: {e}")
            except RuntimeError as e:
                raise MCPError(
                    "INVALID_MFL",
                    f"Failed to load MFL content: {e}\n"
                    f"The content may have syntax errors or be incompatible with Multiflash."
                )
            except Exception as e:
                raise MCPError("INVALID_MFL", f"Unexpected error loading MFL: {e}")

            # Set fluid name from parameter
            wrapper.fluid_name = fluid_name

            response = {
                "status": "loaded",
                "fluid_name": fluid_name,
                "num_components": result.get("num_components", 0),
                "components": [f"Component_{i+1}" for i in range(result.get("num_components", 0))]
            }

            # Add replacement notification if replacing previous fluid
            if previous_fluid is not None:
                response["replaced"] = previous_fluid
                logger.info(f"Replaced fluid '{previous_fluid}' with '{fluid_name}'")
            else:
                logger.info(f"Loaded fluid '{fluid_name}' ({response['num_components']} components)")

            return response

        finally:
            # Clean up temp file
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except:
                    pass

            if temp_path is not None and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass

    @mcp_server.tool()
    def create_fluid_mixture(
        components: list,
        eos_model: str = "PR78",
        mixture_name: str = "CustomMixture"
    ) -> dict:
        """
        Create a fluid mixture programmatically from component list.

        This tool allows you to define mixtures without writing MFL files.
        Component names are from the Multiflash database (use list_available_components
        to see valid names). Mole fractions are automatically normalized to sum to 1.0.

        Args:
            components: List of dicts with "name" and "mole_fraction" keys.
                Example: [{"name": "CARBON DIOXIDE", "mole_fraction": 0.95},
                          {"name": "NITROGEN", "mole_fraction": 0.05}]
            eos_model: Equation of state model (default: "PR78")
                Valid options: PR78, SRK, PR, BWRS, GERG-2008, EOS-CG, CPA, PC-SAFT
            mixture_name: Reference name for the mixture (default: "CustomMixture")

        Returns:
            Dict with mixture info: {
                "status": "created",
                "mixture_name": str,
                "eos_model": str,
                "num_components": int,
                "components": [{"name": str, "mole_fraction": float}, ...],
                "normalized": bool,
                "original_sum": float (only if normalized),
                "replaces_previous": str or None
            }

        Error codes:
            INVALID_INPUT: Empty components, unknown component, negative fraction,
                           missing name/mole_fraction field
            INVALID_EOS: Unknown EOS model (not in supported list)
            MIXTURE_FAILED: Multiflash could not create the mixture

        Examples:
            >>> create_fluid_mixture(
            ...     components=[
            ...         {"name": "CARBON DIOXIDE", "mole_fraction": 0.95},
            ...         {"name": "NITROGEN", "mole_fraction": 0.05}
            ...     ],
            ...     eos_model="PR78",
            ...     mixture_name="CO2_N2_Mix"
            ... )
            # Returns created mixture with 2 components

            >>> create_fluid_mixture(
            ...     components=[
            ...         {"name": "METHANE", "mole_fraction": 85},
            ...         {"name": "ETHANE", "mole_fraction": 10},
            ...         {"name": "PROPANE", "mole_fraction": 5}
            ...     ]
            ... )
            # Fractions normalized automatically: 0.85, 0.10, 0.05
        """
        # Validate components list
        if not components or len(components) == 0:
            raise MCPError("INVALID_INPUT", "Components list cannot be empty")

        if len(components) > 20:
            raise MCPError("INVALID_INPUT", "Maximum 20 components supported")

        # Validate each component
        validated_components = []
        for i, comp in enumerate(components):
            if not isinstance(comp, dict):
                raise MCPError(
                    "INVALID_INPUT",
                    f"Component {i} must be a dict with 'name' and 'mole_fraction' keys"
                )
            if "name" not in comp:
                raise MCPError(
                    "INVALID_INPUT",
                    f"Component {i} missing 'name' field"
                )
            if "mole_fraction" not in comp:
                raise MCPError(
                    "INVALID_INPUT",
                    f"Component {i} missing 'mole_fraction' field"
                )
            if not isinstance(comp["name"], str) or not comp["name"].strip():
                raise MCPError(
                    "INVALID_INPUT",
                    f"Component {i} name must be a non-empty string"
                )
            if not isinstance(comp["mole_fraction"], (int, float)):
                raise MCPError(
                    "INVALID_INPUT",
                    f"Component {i} mole_fraction must be a number"
                )
            if comp["mole_fraction"] < 0:
                raise MCPError(
                    "INVALID_INPUT",
                    f"Component {i} has negative mole_fraction: {comp['mole_fraction']}"
                )
            if comp["mole_fraction"] == 0:
                raise MCPError(
                    "INVALID_INPUT",
                    f"Component {i} has zero mole_fraction (use non-zero values only)"
                )

            validated_components.append({
                "name": comp["name"].strip().upper(),
                "mole_fraction": float(comp["mole_fraction"])
            })

        # Validate EOS model
        validated_eos = _validate_eos_model(eos_model)
        if validated_eos is None:
            valid_models = ", ".join(EOS_MODELS.keys())
            raise MCPError(
                "INVALID_EOS",
                f"Unknown EOS model: '{eos_model}'. Valid models: {valid_models}"
            )

        # Normalize mole fractions
        total = sum(c["mole_fraction"] for c in validated_components)
        normalized = False
        original_sum = total

        if abs(total - 1.0) > 1e-6:  # Not already normalized
            normalized = True
            validated_components = [
                {"name": c["name"], "mole_fraction": c["mole_fraction"] / total}
                for c in validated_components
            ]
            logger.info(f"Normalized mole fractions from sum={original_sum:.6f} to 1.0")

        # Generate MFL content
        mfl_content = _generate_mfl_content(validated_components, validated_eos, mixture_name)

        # Get wrapper and track previous fluid
        try:
            wrapper = get_wrapper_fn()
        except MCPError:
            raise

        previous_fluid = wrapper.fluid_name

        # Load via temp file (reuse load_mfl_text logic)
        temp_fd = None
        temp_path = None
        try:
            temp_fd, temp_path = tempfile.mkstemp(suffix='.mfl', text=True)
            with os.fdopen(temp_fd, 'w') as f:
                f.write(mfl_content)
                temp_fd = None

            try:
                result = wrapper.load_mfl(temp_path)
            except RuntimeError as e:
                # Check for component name errors
                error_str = str(e).lower()
                if "component" in error_str or "unknown" in error_str or "not found" in error_str:
                    raise MCPError(
                        "INVALID_INPUT",
                        f"Unknown component name in mixture: {e}"
                    )
                raise MCPError("MIXTURE_FAILED", f"Failed to create mixture: {e}")
            except Exception as e:
                raise MCPError("MIXTURE_FAILED", f"Unexpected error creating mixture: {e}")

            wrapper.fluid_name = mixture_name

            response = {
                "status": "created",
                "mixture_name": mixture_name,
                "eos_model": validated_eos,
                "eos_description": EOS_MODELS[validated_eos],
                "num_components": len(validated_components),
                "components": validated_components,
                "normalized": normalized,
            }

            if normalized:
                response["original_sum"] = original_sum

            if previous_fluid is not None:
                response["replaces_previous"] = previous_fluid
                logger.info(f"Created mixture '{mixture_name}' (replaced '{previous_fluid}')")
            else:
                response["replaces_previous"] = None
                logger.info(
                    f"Created mixture '{mixture_name}' "
                    f"({len(validated_components)} components, {validated_eos})"
                )

            return response

        finally:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except:
                    pass
            if temp_path is not None and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
