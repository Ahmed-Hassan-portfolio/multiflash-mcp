# multiflash-mcp

This is the LLM-facing side of my Multiflash work. It exposes KBC Multiflash through the Model Context Protocol so an agent can ask for PVT, flash, phase-boundary, and transport calculations as typed tool calls instead of trying to infer thermodynamics from text.

The point is not to make the model "know" thermodynamics. The point is to give it a reliable engineering tool, clear units, structured errors, and enough guardrails that a human engineer can see what happened.

## What's technically interesting

- **27 tools** across 15 modules wrapping a closed-source Fortran-backed PVT engine — PT/PH flash, single- and multi-phase PVT, transport properties, phase boundaries (saturation, bubble, dew, cricondentherm, cricondenbar), critical point, phase envelopes, batch operations, and a programmatic mixture builder
- **Structured error model** (`DLL_NOT_FOUND`, `LICENSE_FAILED`, `SOLID_FORMED`, `ABOVE_CRITICAL`, `NO_FLUID_LOADED`, `MULTI_PHASE_SYSTEM`) so the LLM can recover gracefully instead of seeing opaque Fortran tracebacks
- **Unit conversion at the boundary** — accepts bar/Pa/kPa/MPa/psi/atm, °C/K, J/mol/kJ/mol/J/kg/kJ/kg, and converts to Multiflash's SI internals so the LLM doesn't have to track units
- **Lazy DLL initialization** + dual-import pattern (`python -m mcp_server` and direct execution both work; the server boots even when the DLL isn't reachable, and tools surface a clean error on first call)
- **Programmatic mixture creation** without writing MFL files — pass a component list and EOS choice (PR78, GERG-2008, EOS-CG, …) and the server generates valid Multiflash syntax internally

## Architecture

```
┌─────────────┐   MCP (JSON-RPC)   ┌───────────────────────┐
│ LLM client  │ ─────────────────▶ │   FastMCP server      │
│ (Claude)    │ ◀───────────────── │   mcp_server.server   │
└─────────────┘                    └─────────┬─────────────┘
                                             │ Python
                                  ┌──────────▼────────────┐
                                  │  MultiflashWrapper    │
                                  │  (error translation,  │
                                  │   unit conversion)    │
                                  └──────────┬────────────┘
                                             │ ctypes
                                  ┌──────────▼────────────┐
                                  │  mfpvt64.dll (KBC)    │
                                  │  Multiflash 7.5       │
                                  └───────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the tool catalog and design notes, and [examples/agent_transcript.md](examples/agent_transcript.md) for a short walkthrough of an LLM driving the server end-to-end (load fluid → flash → detect solid-formation risk → escalate to a human).

## Stack

Python 3.10+ · [FastMCP](https://github.com/jlowin/fastmcp) · KBC Multiflash 7.5 (commercial, BYO license)

## Try it

```bash
pip install -e ".[dev]"
# Windows: set the env var before launching
$env:MULTIFLASH_DLL_PATH = "C:\program files\KBC\Multiflash 7.5\x64\mfpvt64.dll"
python -m mcp_server                       # start the server
python examples/01_pt_flash.py             # or run an example directly
python -m pytest -q                        # run the test suite
```

Without a Multiflash install, the server still boots and the structural tests (`pytest -q`) still pass — actual calls into the engine return a clean `DLL_NOT_FOUND` or `LICENSE_FAILED` structured error instead of crashing. Tests marked `requires_multiflash` are skipped cleanly when the DLL file or the `multiflash` Python package is missing (the skip check is a pure availability check; it does not load the DLL or exercise the license — see `tests/conftest.py`).

## Status

Portfolio / research prototype maintained for demonstration and reproducibility. KBC Multiflash is commercial software and is **not** redistributed here; bring your own licensed install. The repository contains only the MCP wrapper, sample fluid definitions, examples, and tests.

What works without a Multiflash install:

- server startup and smoke import,
- schema definitions and unit-conversion logic,
- the structural test subset — 18 of 36 tests (smoke + unit conversion) run unconditionally; the other 18 are marked `requires_multiflash` and skip cleanly when the DLL/package is absent (this is the path CI exercises).

With a Multiflash install + valid license, all 36 tests run and currently pass locally.

What needs a license: any live thermodynamic calculation (PT/PH flash, PVT, transport, phase boundaries, etc.). See [DATA_AND_LICENSE.md](DATA_AND_LICENSE.md) for the dependency boundary and [SECURITY.md](SECURITY.md) for the agent-tool safety model.

## My Contribution

I designed and implemented every layer above the commercial DLL:

- the **FastMCP server** (`mcp_server/server.py`) with lazy DLL initialization and a structured `MCPError` class so the LLM gets actionable codes instead of opaque tracebacks;
- the **27 tool schemas** across 15 modules (`mcp_server/tools/*.py`) including PT/PH flash, single- and multi-phase PVT, transport, phase boundaries, batch operations, and a programmatic mixture builder;
- the **unit-conversion boundary** (`mcp_server/utils/units.py`) with fuzzy unit matching and physical-bound validation;
- the **`MultiflashWrapper`** that adapts Multiflash's ctypes API into dataclass results, error translation, and helpers for the most common calls;
- the **example workflows** and **test harness** with `requires_multiflash` skip-logic so the suite runs structurally on any machine.

KBC Multiflash itself is the commercial engine — I do not own or distribute it. This repo is the agent/tool integration layer around it.

## See also

If you want the same thermodynamic capabilities at a shell prompt instead of through an MCP client, see [`multiflash-cli`](https://github.com/Ahmed-Hassan-portfolio/multiflash-cli). It has subcommands like `mfcli sat-pressure --t 0`, stable exit codes, and `--json` output for scripts and CI jobs. Different surface, same engine.

For the broader agentic workflow, [`Olga-automation`](https://github.com/Ahmed-Hassan-portfolio/Olga-automation) shows how an LLM-driven simulator workflow can call documentation tools, thermodynamic tools, and simulator automation through controlled interfaces instead of free-form shell access.
