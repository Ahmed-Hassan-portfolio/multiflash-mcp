# Data, dependencies, and license boundary

This repository is the MCP/agent integration layer for KBC Multiflash. It does **not** include the Multiflash engine, license files, customer data, or proprietary correlations.

## What this repo contains

- the FastMCP server (`mcp_server/`) — Python, MIT licensed,
- two MFL fluid definitions authored for this repo (`examples/data/*.mfl` — see "Sample MFL files" below),
- example scripts (`examples/01_*.py` through `04_*.py`),
- a test harness (`tests/`) with structural tests that run without the DLL.

## What this repo does NOT contain

- the `mfpvt64.dll` (Multiflash 7.5 engine) — commercial, redistribute-restricted,
- any Multiflash license file or license server configuration,
- any customer, field, or operator-specific compositions,
- any vendor binaries, header files, or shipped C/Fortran samples,
- API keys, tokens, `.env` files, generated databases, or runtime logs.

## KBC Multiflash dependency

Multiflash is a commercial PVT engine sold by KBC Advanced Technologies (a Yokogawa company). You must hold your own valid Multiflash license to run any tool that actually performs a thermodynamic calculation. The MIT license on this repo applies only to the MCP wrapper code; it does not grant you any rights to Multiflash.

Set `MULTIFLASH_DLL_PATH` to your local install before starting the server. See [`.env.example`](.env.example).

## Sample MFL files

`examples/data/Pure_CO2.mfl` and `examples/data/Impure_CO2_Pipeline.mfl` were **authored by the repository owner** from scratch in the Multiflash GUI for this project. They are not copies of, or modifications of, any KBC-shipped sample template (the KBC samples — `ACETH2O.MFL`, `BLACKOIL.MFL`, `BTEX_MEG.MFL`, etc. — are not included here).

They are:

- **original** — written for this repo, not derived from a vendor template;
- **generic** — pure CO₂ on PR78, and a representative ~95 % CO₂ + impurities composition on EOS-CG that is not taken from any operator's real stream;
- **text-only** — no binary data, no vendor IP beyond the MFL scripting syntax KBC documents publicly in `mfcmd.pdf` (Commands Reference).

The MFL format itself is a documented scripting language (see the `Commands_Reference` directory of a Multiflash install). Authoring an MFL file is analogous to writing a `.sql` script: the format is open, even though the engine that runs it is commercial.

If you fork this repo and want to avoid the file route entirely, the server also accepts MFL content as a string via `load_mfl_text`, and lets you build a mixture programmatically via `create_fluid_mixture(components=[...], eos_model=...)`. The `.mfl` files are convenience for the examples; they are not required by the server.

## What works without a Multiflash license

| Action | Needs DLL? |
|---|---|
| `import mcp_server.server` (smoke) | no |
| `python -m mcp_server` (server boots) | no |
| `python -m pytest -q` — 18 structural tests run unconditionally (smoke + unit conversion) | no |
| `python -m pytest -q` — 18 tests marked `requires_multiflash` | yes (auto-skip when DLL/package absent) |
| Tool schema introspection, error-class behavior, unit conversion | no |
| Any actual flash, PVT, transport, phase-boundary, critical-point, or batch call | **yes** |

When the DLL or license is missing, tools return a clean structured error (`DLL_NOT_FOUND`, `LICENSE_FAILED`, `DLL_INIT_FAILED`) rather than crashing the server.

## License of this repository

MIT — see [`LICENSE`](LICENSE). The MIT terms apply to the wrapper code only. Multiflash is **not** covered by this license and is **not** redistributed here.

## Reporting a problem with data or attribution

If you believe one of the example MFL files contains information that should not be public, open an issue and the file will be removed.
