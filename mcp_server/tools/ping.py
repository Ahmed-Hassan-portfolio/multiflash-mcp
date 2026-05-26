"""
Ping tool - placeholder for testing MCP infrastructure.
Demonstrates tool registration pattern and input validation.
"""
from typing import Optional


def register_ping_tool(mcp_server, get_wrapper_fn, logger):
    """Register the ping tool with the MCP server."""

    @mcp_server.tool()
    def ping(
        message: Optional[str] = None,
        check_dll: bool = False
    ) -> dict:
        """
        Test tool to verify MCP server is running.

        Args:
            message: Optional message to echo back
            check_dll: If True, verify Multiflash DLL connection

        Returns:
            Dict with status and optional message/dll_status
        """
        # Input validation
        if message is not None and len(message) > 1000:
            return {
                "error": {
                    "code": "INVALID_INPUT",
                    "message": "Message too long (max 1000 chars)"
                }
            }

        result = {"status": "ok", "server": "multiflash"}

        if message:
            result["echo"] = message

        if check_dll:
            try:
                wrapper = get_wrapper_fn()
                result["dll_status"] = "connected"
                result["dll_path"] = wrapper.dll_path
            except Exception as e:
                result["dll_status"] = "error"
                result["dll_error"] = str(e)

        logger.info(f"ping tool called: check_dll={check_dll}")
        return result
