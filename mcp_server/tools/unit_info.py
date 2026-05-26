"""
Unit Info Tool - Explain transport property units and conversions.

Provides MCP tool for understanding viscosity and thermal conductivity units.
"""


def register_unit_info_tools(mcp_server, get_wrapper_fn, logger):
    """Register unit info tools with the MCP server."""

    @mcp_server.tool()
    def get_transport_unit_info() -> dict:
        """
        Get information about transport property units and conversions.

        Returns structured information about viscosity and thermal conductivity
        units used by the Multiflash MCP server. Use this to understand
        unit meanings and convert between common units.

        Args:
            None

        Returns:
            Dict with transport property unit information:
            {
                "viscosity": {
                    "description": str,
                    "symbol": str,
                    "output_units": [...],
                    "conversions": {...},
                    "typical_values": {...}
                },
                "thermal_conductivity": {
                    "description": str,
                    "symbol": str,
                    "output_units": [...],
                    "conversions": {...},
                    "typical_values": {...}
                }
            }

        Examples:
            >>> get_transport_unit_info()
            # Returns unit information for viscosity and thermal conductivity
        """
        logger.info("get_transport_unit_info called")

        return {
            "viscosity": {
                "description": "Dynamic viscosity - resistance to flow. Higher values = more resistance.",
                "symbol": "mu (Greek letter μ)",
                "output_units": [
                    {
                        "unit": "Pa.s",
                        "full_name": "Pascal-second",
                        "description": "SI unit of dynamic viscosity"
                    },
                    {
                        "unit": "cP",
                        "full_name": "centipoise",
                        "description": "Common engineering unit (1 cP = 0.001 Pa.s)"
                    }
                ],
                "conversions": {
                    "Pa.s_to_cP": "multiply by 1000",
                    "cP_to_Pa.s": "divide by 1000",
                    "Pa.s_to_mPa.s": "multiply by 1000 (same as cP)",
                    "Pa.s_to_poise": "multiply by 10"
                },
                "typical_values": {
                    "water_at_20C": "0.001 Pa.s = 1 cP",
                    "liquid_CO2_at_50bar_4C": "~0.0001 Pa.s = 0.1 cP",
                    "gaseous_CO2_at_10bar_50C": "~0.000015 Pa.s = 0.015 cP"
                }
            },
            "thermal_conductivity": {
                "description": "Ability to conduct heat. Higher values = better heat conductor.",
                "symbol": "k (or lambda λ)",
                "output_units": [
                    {
                        "unit": "W/(m.K)",
                        "full_name": "Watt per meter-Kelvin",
                        "description": "SI unit of thermal conductivity"
                    }
                ],
                "conversions": {
                    "W/(m.K)_to_mW/(m.K)": "multiply by 1000",
                    "W/(m.K)_to_BTU/(hr.ft.F)": "multiply by 0.5778"
                },
                "typical_values": {
                    "water_at_20C": "0.6 W/(m.K)",
                    "liquid_CO2_at_50bar_4C": "~0.1 W/(m.K)",
                    "gaseous_CO2_at_10bar_50C": "~0.02 W/(m.K)",
                    "copper": "400 W/(m.K)",
                    "air": "0.025 W/(m.K)"
                }
            }
        }
