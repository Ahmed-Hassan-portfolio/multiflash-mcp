# Examples

Four standalone scripts that exercise the same Multiflash operations exposed by the MCP server, but call the underlying wrapper directly — so they read top-to-bottom and don't require running an MCP client.

| Script | What it does | MCP tool equivalent |
|---|---|---|
| `01_pt_flash.py` | Loads CO₂, runs a PT flash at 50 bar / 4 °C, prints phase + composition | `pt_flash` |
| `02_phase_envelope.py` | Traces the pure CO₂ phase envelope and (if matplotlib is installed) plots it | `get_phase_envelope` |
| `03_critical_and_saturation.py` | Computes the critical point and walks the saturation curve | `get_critical_point`, `get_saturation_pressure` |
| `04_batch_pipeline_profile.py` | Runs a batch flash at multiple P/T points to verify a pipeline operating envelope | `batch_flash` |

All four are illustrative / synthetic — none of them contain real field data or proprietary compositions.

## Running

```bash
pip install -e ".[examples]"
export MULTIFLASH_DLL_PATH="C:/program files/KBC/Multiflash 7.5/x64/mfpvt64.dll"
python examples/01_pt_flash.py
```

If the Multiflash DLL or license is unavailable, each script prints a clean error and exits with a non-zero status.

## Fluid files (`data/`)

- **`Pure_CO2.mfl`** — pure CO₂ on the PR78 equation of state. Generic, single-component.
- **`Impure_CO2_Pipeline.mfl`** — a representative impure CO₂ pipeline composition (~95% CO₂ with typical CCS impurities: N₂, O₂, Ar, H₂, H₂O, SO₂, CH₄, N₂O) on the EOS-CG (GERG-CG) equation of state. Composition is illustrative, not specific to any real project.
