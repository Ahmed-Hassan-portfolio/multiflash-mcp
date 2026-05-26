# Example agent transcript

This walkthrough shows what a typical LLM ↔ server interaction looks like. It is illustrative — a real transcript from Claude or any MCP client follows the same shape, just with the LLM's natural-language framing around each tool call.

Scenario: an engineer asks the agent to check a low-temperature CO₂ pipeline for solid/two-phase risk near the inlet conditions.

---

**User prompt (to the LLM):**

> I have an impure CO₂ pipeline running at 50 bar and 4 °C inlet. Can you check what phase the stream is in, whether there's any solid-formation risk if it cools further, and flag anything I should not act on without an engineer?

---

### Step 1 — load the fluid

LLM emits an MCP tool call:

```json
{
  "tool": "load_mfl_file",
  "arguments": {
    "path": "examples/data/Impure_CO2_Pipeline.mfl"
  }
}
```

Server response:

```json
{
  "fluid_name": "Impure_CO2_Pipeline",
  "num_components": 9,
  "components": ["ARGON", "HYDROGEN", "OXYGEN", "NITROGEN",
                 "CARBON DIOXIDE", "WATER", "SULPHUR DIOXIDE",
                 "METHANE", "NITROUS OXIDE"],
  "eos_model": "EOS-CG"
}
```

### Step 2 — PT flash at inlet conditions

```json
{
  "tool": "pt_flash",
  "arguments": {
    "pressure": 50, "pressure_unit": "bar",
    "temperature": 4, "temperature_unit": "C"
  }
}
```

Server response (one liquid phase — happy case):

```json
{
  "num_phases": 1,
  "phases": [
    {"name": "LIQUID1", "mole_fraction": 1.0}
  ],
  "input_echo": {"pressure_bar": 50, "temperature_C": 4},
  "si_canonical": {"pressure_Pa": 5000000.0, "temperature_K": 277.15}
}
```

### Step 3 — check saturation pressure to see how close we are to two-phase

```json
{
  "tool": "get_saturation_pressure",
  "arguments": {"temperature": 4, "temperature_unit": "C"}
}
```

Server response:

```json
{
  "saturation_pressure_bar": 39.2,
  "input_echo": {"temperature_C": 4},
  "note": "Above Psat. The stream is sub-cooled liquid."
}
```

(The exact `Psat` depends on the mixture; for pure CO₂ at 4 °C it is ~38.8 bar.)

### Step 4 — probe a colder operating point that risks the triple line

```json
{
  "tool": "pt_flash",
  "arguments": {
    "pressure": 50, "pressure_unit": "bar",
    "temperature": -60, "temperature_unit": "C"
  }
}
```

Server response — the structured-error path:

```json
{
  "error": {
    "code": "SOLID_FORMED",
    "message": "PT flash entered the solid CO2 region (below the triple line). Multiflash returned a solid phase, which the server does not currently return as a regular phase. Re-run above ~-56.6 C or call get_saturation_temperature to find the boundary."
  }
}
```

### Step 5 — LLM synthesises and escalates

The LLM now has structured evidence. It does not invent numbers; it reports what the server returned, and **escalates the decision**:

> At the inlet (50 bar, 4 °C) the stream is a single sub-cooled liquid phase; saturation is around 39 bar at 4 °C, so the operating point sits roughly 11 bar above the two-phase line. A cool-down to −60 °C at 50 bar would cross the triple line for CO₂ and the server returned `SOLID_FORMED` — that path is unsafe to run blind.
>
> Before I recommend anything operational, please confirm with a flow-assurance engineer:
> - whether the real composition matches `Impure_CO2_Pipeline.mfl` (95 % CO₂ + N₂/Ar/H₂/H₂O/SO₂/CH₄/N₂O),
> - whether the worst-case downstream temperature actually approaches the triple line,
> - whether a JT-cooling check across any valve is needed (the server has `get_joule_thomson_coefficient` and `ph_flash` for that).
>
> I can run the JT and isenthalpic-flash steps next if you want a more complete picture, but the equipment decision should not be made on this calculation alone.

---

## What this transcript demonstrates for a reviewer

- **Deterministic tool schemas.** Every call has typed inputs (`pressure`, `pressure_unit`, …), echoed inputs in the response, and SI canonical values — so the LLM cannot quietly confuse bar and Pa.
- **Structured error codes.** `SOLID_FORMED` is one of ~16 stable codes (see [docs/TOOLS.md](docs/TOOLS.md)). The LLM can branch on the code; the human can read the message.
- **Human escalation built into the workflow.** The LLM does the calculation and surfaces the assumptions; it does not commit to an operational recommendation. The [SECURITY.md](SECURITY.md) note about not being a safety-rated system is the policy this transcript follows.
- **Graceful degradation.** If the DLL or license were not available, every one of those tool calls would have returned `DLL_NOT_FOUND` / `LICENSE_FAILED` instead of crashing the server. The transcript shape would be identical; only the responses change.
