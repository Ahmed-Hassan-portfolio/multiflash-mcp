# Tools reference

Quick reference for every MCP tool exposed by the server. All tools accept user-facing units and convert internally to Pa / K / J/mol.

## Workflow

```
1. Load fluid     → load_mfl_file OR create_fluid_mixture
2. Query state    → pt_flash (what phase at this P, T?)
3. Get properties → get_pvt_properties / get_transport_properties
4. Analyze bounds → get_saturation_pressure / get_phase_envelope / get_critical_point
```

## Tool catalog

### Server / liveness
| Tool | Purpose |
|---|---|
| `ping` | Server liveness probe. Pass `check_dll=True` to also verify the Multiflash DLL is reachable. |

### Fluid loading
| Tool | Purpose |
|---|---|
| `load_mfl_file(path)` | Load a `.mfl` file from disk. |
| `load_mfl_text(content, fluid_name)` | Load an MFL definition passed as a string (no temp file leak). |
| `create_fluid_mixture(components, eos_model, mixture_name)` | Build an MFL programmatically from a component list. EOS choices: PR78, SRK, PR, BWRS, GERG-2008, EOS-CG, CPA, PC-SAFT. Mole fractions normalized automatically. |
| `query_fluid_info(detail_level)` | What's currently loaded. `summary` or `detailed`. |

### Flash calculations
| Tool | Purpose |
|---|---|
| `pt_flash(pressure, temperature, …)` | Phase state and per-phase mole fractions at given P, T. |
| `ph_flash(pressure, enthalpy, …)` | Isenthalpic flash (valve / Joule-Thomson). Returns the outlet temperature. |

### Single-phase PVT
| Tool | Purpose |
|---|---|
| `get_pvt_properties(pressure, temperature, …)` | Density, MW, Z, isothermal compressibility, thermal expansion, molar volume. Errors with `MULTI_PHASE_SYSTEM` if the state is two-phase. |

### Multi-phase PVT
| Tool | Purpose |
|---|---|
| `get_multiphase_properties(pressure, temperature, …)` | Per-phase PVT plus volume-fraction-weighted bulk values. |

### Transport
| Tool | Purpose |
|---|---|
| `get_transport_properties(pressure, temperature, …)` | Viscosity (Pa·s, cP) and thermal conductivity (W/m·K). Single- or multi-phase. |

### Phase boundary
| Tool | Purpose |
|---|---|
| `get_saturation_pressure(temperature, …)` | Vapor pressure at the given T. Useful for relief-valve sizing. |
| `get_saturation_temperature(pressure, …)` | Boiling point at the given P. |
| `bubble_point(specification, …)` / `dew_point(specification, …)` | Bubble / dew pressure or temperature for mixtures. |
| `get_cricondentherm(…)` | Maximum temperature on the two-phase envelope. |
| `get_cricondenbar(…)` | Maximum pressure on the two-phase envelope. |

### Critical point & envelope
| Tool | Purpose |
|---|---|
| `get_critical_point()` | Tc, Pc, Vc, Zc for the loaded fluid. |
| `get_phase_envelope(…)` | Full P-T two-phase envelope as a list of points. |
| `get_joule_thomson_coefficient(pressure, temperature, …)` | ∂T/∂P at constant H. |

### Batch
| Tool | Purpose |
|---|---|
| `batch_flash(flash_type, points, include_properties)` | Run many flashes in one call (e.g., a pipeline profile). |
| `property_sweep(…)` | Sweep one variable over a range and return tabulated properties. |

### Reference
| Tool | Purpose |
|---|---|
| `list_available_components(filter)` | Search the Multiflash component database. |
| `get_component_properties(name)` | Pure-component data (Tc, Pc, ω, MW, …) for one component. |
| `list_eos_models()` | List supported EOS model names grouped by category. |
| `list_supported_units()` | Every unit string the server accepts. |

### Validation (smoke checks)
| Tool | Purpose |
|---|---|
| `run_validation(test_case)` | Pure-CO2 PVT smoke check against published values. |
| `run_v2_validation(test_case)` | Saturation / critical / JT / sweep / batch smoke check. |

## Error codes

| Code | When |
|---|---|
| `DLL_NOT_FOUND` | `MULTIFLASH_DLL_PATH` doesn't point at an existing file. |
| `LICENSE_FAILED` | DLL loaded but rejected the license check. |
| `DLL_INIT_FAILED` | DLL failed to initialize for another reason. |
| `NO_FLUID_LOADED` | A tool was called before `load_mfl_file` / `load_mfl_text` / `create_fluid_mixture`. |
| `INVALID_INPUT` | Bad unit string, negative pressure, T below absolute zero, malformed component list, … |
| `FILE_NOT_FOUND` | MFL path doesn't exist. |
| `INVALID_MFL` | Multiflash couldn't parse the MFL content. |
| `INVALID_EOS` | Unknown EOS model. |
| `MIXTURE_FAILED` | `create_fluid_mixture` couldn't build the requested mixture. |
| `FLASH_FAILED` | PT or PH flash failed internally. |
| `SOLID_FORMED` | PH flash produced a state below the triple point. |
| `MULTI_PHASE_SYSTEM` | Single-phase tool called in a two-phase region. |
| `SINGLE_PHASE_SYSTEM` | Multi-phase tool called in a single-phase region. |
| `PROPERTY_CALC_FAILED` | AYMIX / AYAVMW / similar failed. |
| `TRANSPORT_CALC_FAILED` | AYVISC / AYTCND failed. |
| `ABOVE_CRITICAL` | Asked for a saturation property where none exists. |

## Units accepted

- **Pressure:** `bar` (default), `Pa`, `kPa`, `MPa`, `psi`, `atm` — plus aliases (`bars`, `pascal`, `megapascal`, etc.).
- **Temperature:** `C` (default), `K` — plus `Celsius`, `Kelvin`, `degC`, `°C`.
- **Enthalpy:** `J/mol` (default), `kJ/mol`, `J/kg`, `kJ/kg`. Mass-based units require a loaded fluid (the server reads MW from the wrapper).

## Reference numbers

### Pure CO₂

| Property | Value | Note |
|---|---|---|
| Tc | 304.13 K (31.0 °C) | Critical temperature |
| Pc | 73.77 bar | Critical pressure |
| Zc | 0.274 | Critical compressibility |
| Triple T | 216.55 K (-56.6 °C) | Below this CO₂ can solidify |
| Triple P | 5.18 bar | |

### CO₂ saturation pressure

| T (°C) | P_sat (bar) |
|---|---|
| -40 | 10.05 |
| -20 | 19.70 |
| 0   | 34.85 |
| 10  | 45.02 |
| 20  | 57.29 |
| 30  | 71.95 |
