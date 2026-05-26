"""
Fluid Query Tools - Query loaded fluid information and composition.

Provides MCP tool:
- query_fluid_info: Get information about the currently loaded fluid
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


def register_fluid_query_tools(mcp_server, get_wrapper_fn, logger):
    """Register fluid query tools with the MCP server."""

    @mcp_server.tool()
    def query_fluid_info(detail_level: str = "summary") -> dict:
        """
        Query information about the currently loaded fluid.

        Args:
            detail_level: Output mode - "summary" (default) or "detailed"
                - summary: Basic fluid name, num_components, composition
                - detailed: Adds component names, phase information

        Returns:
            Dict with fluid information based on detail_level

        Error codes:
            NO_FLUID_LOADED: No fluid is currently loaded
            INVALID_INPUT: Invalid detail_level parameter
            DLL_ERROR: Multiflash DLL connection or query error
        """
        # Validate detail_level parameter
        valid_levels = ["summary", "detailed"]
        if detail_level not in valid_levels:
            raise MCPError(
                "INVALID_INPUT",
                f"Invalid detail_level: '{detail_level}'. Must be one of: {valid_levels}"
            )

        # Get wrapper and check DLL connection
        try:
            wrapper = get_wrapper_fn()
        except Exception as e:
            raise MCPError("DLL_ERROR", str(e))

        # Check if fluid is loaded
        if not wrapper.is_loaded:
            raise MCPError(
                "NO_FLUID_LOADED",
                "No fluid loaded. Use load_mfl_file or load_mfl_text first."
            )

        # Build response based on detail level
        try:
            # Summary mode - basic info
            result = {
                "fluid_name": wrapper.fluid_name or "Unknown",
                "num_components": len(wrapper.composition),
                "composition": [float(x) for x in wrapper.composition]
            }

            # Detailed mode - add component and phase information
            if detail_level == "detailed":
                # Get component names from MFL
                component_names = []
                if hasattr(wrapper.mfl, 'compounds'):
                    component_names = list(wrapper.mfl.compounds)
                else:
                    # Fallback to generic names
                    component_names = [f"Component_{i+1}" for i in range(len(wrapper.composition))]

                result["components"] = {
                    "names": component_names,
                    "mole_fractions": [float(x) for x in wrapper.composition]
                }

                # Get phase information if available
                phases_info = {
                    "names": [],
                    "phase_ids": []
                }
                if hasattr(wrapper.mfl, 'phases'):
                    phases_info["names"] = list(wrapper.mfl.phases)
                if hasattr(wrapper.mfl, 'phase_ids'):
                    phases_info["phase_ids"] = [int(x) for x in wrapper.mfl.phase_ids]

                result["phases"] = phases_info

            logger.info(f"Query fluid info: {wrapper.fluid_name} (detail_level={detail_level})")
            return result

        except Exception as e:
            raise MCPError(
                "DLL_ERROR",
                f"Failed to query fluid information: {e}"
            )
