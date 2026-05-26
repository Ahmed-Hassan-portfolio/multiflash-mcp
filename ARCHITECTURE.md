# Architecture

## Components

| Layer | What it does |
|---|---|
| `mcp_server/server.py` | FastMCP entry point. Lazy DLL init, structured error class, env-driven config, registers every tool module. |
| `mcp_server/tools/` | One module per logical tool group. Each exposes `register_*_tools(mcp, get_wrapper, logger)`. |
| `mcp_server/utils/units.py` | Pressure / temperature / enthalpy unit conversion with fuzzy unit matching and physical-bound validation. |
| `mcp_server/multiflash_wrapper.py` | Thin Python adapter over Multiflash's `ctypes` API. Adds clean exceptions, dataclass results, and helpers for the most common calls (PT flash, PH flash, AYMIX, AYAVMW, AYVISC, AYTCND, AXCRIT). |

## Data flow (single tool call)

```
LLM call: pt_flash(pressure=50, temperature=4, pressure_unit="bar", temperature_unit="C")
   │
   ▼
flash.pt_flash()
   │  validate_pressure / validate_temperature
   │  convert_pressure_to_pa / convert_temperature_to_k
   ▼
wrapper.pt_flash(temperature=277.15, pressure=5_000_000)
   │  ctypes call into mfpvt64.dll
   ▼
FlashResult(phases, phase_names, moles_per_phase, compositions)
   │  shaped into JSON-friendly response with input echo + SI canonical values
   ▼
{"num_phases": 1, "phases": [{"name": "LIQUID1", "mole_fraction": 1.0, ...}], ...}
```

Every tool follows the same shape: validate units → convert to SI → call wrapper → translate exceptions to `MCPError` codes → return structured JSON with both the original inputs and the SI canonical values.

## Tool catalog

| Module | Tools |
|---|---|
| `ping.py` | `ping` |
| `fluid_loader.py` | `load_mfl_file`, `load_mfl_text`, `create_fluid_mixture` |
| `fluid_query.py` | `query_fluid_info` |
| `flash.py` | `pt_flash`, `ph_flash` |
| `pvt_properties.py` | `get_pvt_properties` (single-phase) |
| `multiphase_properties.py` | `get_multiphase_properties` |
| `transport_properties.py` | `get_transport_properties` (viscosity, thermal conductivity) |
| `phase_boundary.py` | `get_saturation_pressure`, `get_saturation_temperature`, `get_critical_point`, `bubble_point`, `dew_point`, `get_cricondentherm`, `get_cricondenbar`, `get_phase_envelope` |
| `thermodynamic_properties.py` | `get_joule_thomson_coefficient` |
| `batch_operations.py` | `batch_flash`, `property_sweep` |
| `component_database.py` | `list_available_components`, `get_component_properties` |
| `eos_reference.py` | `list_eos_models` |
| `unit_info.py` | `list_supported_units` |
| `validation.py` | `run_validation` (smoke-checks pure CO2 against published values) |
| `v2_validation.py` | `run_v2_validation` (smoke-checks Psat / Tc / JT / sweep / batch) |

Total: 27 tools across 15 modules.

## Key design decisions

**Structured errors over raw exceptions.** Every tool wraps its work in `try / except MCPError`. Each failure mode gets a stable code (`DLL_NOT_FOUND`, `LICENSE_FAILED`, `NO_FLUID_LOADED`, `INVALID_INPUT`, `FLASH_FAILED`, `SOLID_FORMED`, `ABOVE_CRITICAL`, `MULTI_PHASE_SYSTEM`, etc.). The LLM can branch on the code; humans can read the message.

**Lazy global wrapper.** The Multiflash DLL is large and license-checked. We initialize it on first use and cache the wrapper in a module-level singleton, so the MCP server boots instantly even when the DLL or license is unavailable — and reports a clean `DLL_NOT_FOUND` / `LICENSE_FAILED` only when a tool actually needs it.

**Unit conversion at the tool boundary, not in the engine.** Multiflash's API speaks Pa and K. Every tool accepts user-facing units (`bar`, `MPa`, `psi`, `°C`, `K`, `kJ/mol`, …) and converts before calling the wrapper. The response always echoes the user's input units *and* the SI canonical values, so the LLM can trace any unit confusion.

**Dual-import pattern.** Each tool module tries `from mcp_server.utils.units import …` first, then falls back to `from utils.units import …`. This makes both `python -m mcp_server` and `python mcp_server/server.py` work without sys.path gymnastics. The same pattern is used for the wrapper import in `server.py`.

**Single-phase / multi-phase split.** `get_pvt_properties` rejects multi-phase systems with `MULTI_PHASE_SYSTEM` and points to `get_multiphase_properties`. This avoids returning meaningless bulk averages (e.g., averaged Z factor for a VLE mixture) and forces the caller to acknowledge the phase regime.
