"""
Server smoke tests. No DLL or license required.

Confirms that the package imports cleanly, every tool module registers
its tool function with the FastMCP server, and the structured-error
class behaves as expected.
"""
from __future__ import annotations


def test_package_imports():
    import mcp_server
    import mcp_server.server
    import mcp_server.multiflash_wrapper
    import mcp_server.utils.units

    assert mcp_server.server.VERSION


def test_all_tool_modules_import():
    from mcp_server.tools import (
        batch_operations,
        component_database,
        eos_reference,
        flash,
        fluid_loader,
        fluid_query,
        multiphase_properties,
        phase_boundary,
        ping,
        pvt_properties,
        thermodynamic_properties,
        transport_properties,
        unit_info,
        v2_validation,
        validation,
    )

    expected_registrars = [
        (batch_operations, "register_batch_operations_tools"),
        (component_database, "register_component_database_tools"),
        (eos_reference, "register_eos_reference_tools"),
        (flash, "register_flash_tools"),
        (fluid_loader, "register_fluid_loader_tools"),
        (fluid_query, "register_fluid_query_tools"),
        (multiphase_properties, "register_multiphase_properties_tools"),
        (phase_boundary, "register_phase_boundary_tools"),
        (ping, "register_ping_tool"),
        (pvt_properties, "register_pvt_properties_tools"),
        (thermodynamic_properties, "register_thermodynamic_tools"),
        (transport_properties, "register_transport_properties_tools"),
        (unit_info, "register_unit_info_tools"),
        (v2_validation, "register_v2_validation_tools"),
        (validation, "register_validation_tools"),
    ]
    for module, attr in expected_registrars:
        assert hasattr(module, attr), f"{module.__name__} missing {attr}"


def test_server_creates_mcp_instance():
    from mcp_server.server import mcp

    assert mcp.name == "multiflash"


def test_mcp_error_structure():
    from mcp_server.server import MCPError

    err = MCPError("TEST_CODE", "test message")
    payload = err.to_dict()
    assert payload == {"error": {"code": "TEST_CODE", "message": "test message"}}
    assert str(err) == "test message"
