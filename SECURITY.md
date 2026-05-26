# Security and agent-safety notes

This server exposes a commercial PVT engine to an LLM as MCP tool calls. The risk model is *agent tool use*, not a public web API. The notes below describe what the server does and does not protect against, so a reviewer or operator can decide how to deploy it.

## Threat model assumptions

- The MCP client (Claude, etc.) is **trusted**, and so is the user driving it.
- Tool **arguments** may come from prompts that include data from untrusted sources (documents, search results, MFL strings). They must be treated as untrusted.
- Tool **outputs** may be fed back into the LLM's context — they must not influence the model with instructions disguised as engine output.
- The Multiflash DLL itself is trusted (it is commercial vendor code installed by the operator).

## What the server does

- **No arbitrary shell execution.** The server does not call `subprocess`, `os.system`, `eval`, `exec`, or any equivalent. Search the source: `grep -RInE 'subprocess|os\.system|shell=True|eval\(|exec\(' mcp_server/` returns nothing. The Multiflash engine is reached only through declared `ctypes` calls.
- **File access is explicit.** `load_mfl_file(path)` opens the path the caller provides, reads it, and hands the text to Multiflash. There is no recursive directory walk, glob, or shell expansion. Run the server as a user that can only read paths you are willing to expose.
- **Untrusted MFL text is fed to a parser, not to a shell.** `load_mfl_text` writes the supplied text to a temp file and calls Multiflash. A malformed string returns `INVALID_MFL`. We do not interpret the MFL content ourselves.
- **Unit strings are bounded.** The unit-conversion layer rejects unknown units with `INVALID_INPUT` and validates pressures / temperatures against physical bounds (no negative absolute pressures, nothing below absolute zero, etc.). See `mcp_server/utils/units.py`.
- **Structured errors over tracebacks.** Every tool wraps its work and returns `MCPError(code, message)`. The LLM gets a stable code (`DLL_NOT_FOUND`, `LICENSE_FAILED`, `NO_FLUID_LOADED`, `INVALID_INPUT`, `FLASH_FAILED`, `SOLID_FORMED`, `ABOVE_CRITICAL`, `MULTI_PHASE_SYSTEM`, …). No raw Fortran tracebacks are surfaced.
- **Lazy DLL init, no startup license burn.** The wrapper is created on first call. A missing DLL or license never crashes the server; it surfaces a structured error on the first tool that needs the engine.
- **No outbound network calls.** The server speaks MCP over stdio. It does not phone home, fetch packages at runtime, or read remote configuration.

## What the server does NOT protect against

- **Prompt injection through MFL content or tool output.** If an LLM is asked to ingest a `.mfl` file from an untrusted source, that text may contain prompt-style instructions the LLM might follow. The server cannot strip natural-language fragments embedded in fluid metadata. The MCP client (or a wrapper around it) should treat tool inputs and outputs as untrusted text for the LLM, not as instructions.
- **Path access controls.** The server runs with whatever filesystem rights its OS process has. If you do not want the LLM to read `C:\Secrets\production.mfl`, do not start the server as a user that can read that file.
- **Multiflash engine bugs or numerical errors.** The wrapper translates engine failures to structured codes, but it cannot guarantee the engine's numbers. Treat results as advisory; cross-check critical values against literature or a second engine.
- **Resource exhaustion.** A batch tool or a property sweep can take real CPU. There is no per-call timeout or rate limit. If you expose the server to an autonomous agent, put a budget around it externally.

## Human review is required for operational decisions

The server is a calculation tool. It is **not** a safety-rated system. Any decision that has operational, safety, environmental, or commercial consequences — pipeline operating envelopes, relief-valve sizing, blowdown, CO₂-rich flow assurance, equipment integrity — must be reviewed by a qualified engineer. Structured error codes are advisory; they do not replace engineering validation.

Examples of decisions an LLM should **not** make alone using these tools:

- whether to open or close a real valve,
- whether a pipeline section is safe to repressurise,
- whether a temperature excursion is acceptable,
- whether a transport calculation is accurate for a real composition with unknown contaminants.

In those cases the recommended pattern is: the LLM does the calculation, summarises the result, and escalates to a human engineer with the numbers and the assumptions on the table.

## Secrets and artifacts

- Secrets are read from environment variables (`MULTIFLASH_DLL_PATH`, `MULTIFLASH_DB_PATH`). `.env` is gitignored. See [`.env.example`](.env.example).
- Runtime artifacts (`mcp_server/logs/`, `__pycache__/`, `.pytest_cache/`, `*.log`, `*.db`) are gitignored. They are also stripped before publishing.
- This repository contains no API keys, tokens, vendor binaries, license files, or customer data. See [DATA_AND_LICENSE.md](DATA_AND_LICENSE.md).

## Reporting a vulnerability

Open a GitHub issue with reproduction steps. If the vulnerability would be unsafe to disclose publicly (for example, an exploit against a downstream agent setup), email `a.sayed90@gmail.com` instead and the issue will be tracked privately.
