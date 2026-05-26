"""
EOS Reference Tool - List available equation of state models.

Provides MCP tool for querying valid Multiflash EOS model names grouped by category.
"""


class MCPError(Exception):
    """Structured error for MCP responses - local copy to avoid circular import."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


def register_eos_reference_tools(mcp_server, get_wrapper_fn, logger):
    """Register EOS reference tools with the MCP server."""

    @mcp_server.tool()
    def list_eos_models() -> dict:
        """
        List all available equation of state (EOS) models in Multiflash.

        Returns grouped dictionary of EOS models by category, with exact
        Multiflash spelling for use when creating MFL files. Also shows
        which EOS the currently loaded fluid uses (if fluid is loaded).

        Args:
            None

        Returns:
            Dict with EOS models grouped by category:
            {
                "categories": {
                    "cubic_eos": {
                        "description": str,
                        "models": [...]
                    },
                    "activity_models": {...},
                    "specialty_eos": {...}
                },
                "mfl_model_syntax": str,
                "current_fluid_eos": str or null,
                "fluid_loaded": bool
            }

        Examples:
            >>> list_eos_models()
            # Returns all available EOS models with current fluid EOS
        """
        logger.info("list_eos_models called")

        # Define EOS categories (static reference data - no DLL calls needed)
        categories = {
            "cubic_eos": {
                "description": "Cubic equations of state for general hydrocarbons",
                "models": [
                    "SRK",       # Soave-Redlich-Kwong
                    "PR",        # Peng-Robinson
                    "PR78",      # Peng-Robinson 1978
                    "RKS",       # Redlich-Kwong-Soave
                    "RKSA",      # RKS with Adachi-Lu alpha
                    "PRSV",      # Peng-Robinson-Stryjek-Vera
                    "PRMC",      # Peng-Robinson with Mathias-Copeman
                    "ZJ",        # Zudkevitch-Joffe
                    "BWRS"       # Benedict-Webb-Rubin-Starling
                ]
            },
            "activity_models": {
                "description": "Activity coefficient models for polar/non-ideal systems",
                "models": [
                    "NRTL",
                    "UNIQUAC",
                    "UNIFAC",
                    "UNIFAC-LL",
                    "WILSON"
                ]
            },
            "specialty_eos": {
                "description": "Specialized EOS for specific applications",
                "models": [
                    "EOS-CG",    # For CO2-rich mixtures
                    "GERG-2008", # For natural gas
                    "CPA",       # Cubic Plus Association
                    "PC-SAFT",   # Perturbed Chain SAFT
                    "SAFT"       # Statistical Associating Fluid Theory
                ]
            }
        }

        # Try to get currently loaded fluid's EOS
        current_eos = None
        fluid_loaded = False

        try:
            wrapper = get_wrapper_fn()
            if wrapper.is_loaded:
                fluid_loaded = True
                # Try to read EOS from MFL object
                if hasattr(wrapper.mfl, 'model') and wrapper.mfl.model:
                    current_eos = wrapper.mfl.model
                elif hasattr(wrapper.mfl, 'eos') and wrapper.mfl.eos:
                    current_eos = wrapper.mfl.eos
                else:
                    # No EOS attribute accessible
                    current_eos = "Unable to determine (MFL attribute not accessible)"
        except Exception:
            # Wrapper not available or error accessing - not critical
            pass

        return {
            "categories": categories,
            "mfl_model_syntax": "Use M prefix for mixing rules (e.g., MPR78 = PR78 with mixing)",
            "current_fluid_eos": current_eos,
            "fluid_loaded": fluid_loaded
        }
