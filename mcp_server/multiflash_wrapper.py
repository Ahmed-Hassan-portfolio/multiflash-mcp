"""
Multiflash Wrapper Module

Provides a clean interface to the Multiflash DLL for PVT calculations.
Handles initialization, error checking, and common operations.

Usage:
    from mcp_server.multiflash_wrapper import MultiflashWrapper

    mf = MultiflashWrapper()
    mf.load_mfl("path/to/mixture.mfl")
    result = mf.pt_flash(temperature=300, pressure=10e6)
"""

import os
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any

# Default paths for Multiflash 7.5 installation.
# Override via MULTIFLASH_DLL_PATH / MULTIFLASH_DB_PATH environment variables.
DEFAULT_DLL_PATH = os.environ.get(
    "MULTIFLASH_DLL_PATH",
    r"C:\program files\KBC\Multiflash 7.5\x64\mfpvt64.dll",
)
DEFAULT_DB_PATH = os.environ.get(
    "MULTIFLASH_DB_PATH",
    r"C:\program files\KBC\Multiflash 7.5",
)


@dataclass
class FlashResult:
    """Result of a flash calculation."""
    temperature: float  # K
    pressure: float     # Pa
    phases: List[int]   # Phase load numbers
    phase_names: List[str]  # Phase names (e.g., 'GAS', 'LIQUID1')
    moles_per_phase: List[float]  # Moles in each phase
    compositions: List[List[float]]  # Mole fractions [phase][component]

    @property
    def num_phases(self) -> int:
        return len(self.phases)

    @property
    def is_single_phase(self) -> bool:
        return self.num_phases == 1

    @property
    def has_vapor(self) -> bool:
        return any('GAS' in name.upper() for name in self.phase_names)

    @property
    def has_liquid(self) -> bool:
        return any('LIQUID' in name.upper() for name in self.phase_names)


@dataclass
class AYMIXResult:
    """Result of AYMIX thermodynamic property calculation."""
    volume: float           # Molar volume, m³/mol
    volume_T: float         # dV/dT at const P, m³/(mol·K)
    volume_P: float         # dV/dP at const T, m³/(mol·Pa)
    enthalpy: float         # Molar enthalpy, J/mol
    enthalpy_T: float       # Cp = dH/dT at const P, J/(mol·K)
    fugacity: Optional[List[float]] = None  # Component fugacities


@dataclass
class TransportResult:
    """Result of transport property calculation."""
    value: float           # Property value (viscosity in Pa.s or conductivity in W/(m.K))
    value_T: float = 0.0   # dValue/dT derivative (optional)
    value_P: float = 0.0   # dValue/dP derivative (optional)


class MultiflashWrapper:
    """
    Wrapper class for Multiflash DLL operations.

    Provides error handling, diagnostics, and a cleaner interface for the
    PVT calculations exposed by the MCP server: PT/PH flash, single- and
    multi-phase property calls (AYMIX, AYAVMW), transport properties
    (AYVISC, AYTCND), and critical-point / phase-boundary helpers (AXCRIT).
    """

    def __init__(self,
                 dll_path: str = DEFAULT_DLL_PATH,
                 db_path: str = DEFAULT_DB_PATH,
                 auto_connect: bool = True):
        """
        Initialize the Multiflash wrapper.

        Args:
            dll_path: Path to mfpvt64.dll (or mfpvt32.dll for 32-bit)
            db_path: Path to Multiflash installation directory
            auto_connect: If True, connect to DLL immediately
        """
        self.dll_path = dll_path
        self.db_path = db_path
        self.dll = None
        self.mfl = None
        self.composition = None
        self.mfl_path = None
        self.fluid_name = None
        self._connected = False

        if auto_connect:
            self.connect()

    def connect(self) -> bool:
        """
        Connect to the Multiflash DLL.

        Returns:
            True if connection successful

        Raises:
            FileNotFoundError: If DLL or database path not found
            RuntimeError: If DLL fails to load
        """
        # Validate paths
        if not os.path.exists(self.dll_path):
            raise FileNotFoundError(
                f"Multiflash DLL not found at: {self.dll_path}\n"
                f"Please verify your Multiflash installation."
            )

        if not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f"Multiflash database path not found: {self.db_path}\n"
                f"Please verify your Multiflash installation."
            )

        try:
            from multiflash import MultiflashDll
            self.dll = MultiflashDll(self.dll_path, self.db_path)
            self._connected = True
            return True
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Multiflash DLL: {e}\n"
                f"Make sure you have the Multiflash Python API installed:\n"
                f"  pip install path/to/Multiflash_Python_API-7.5-py2.py3-none-any.whl"
            )

    @property
    def is_connected(self) -> bool:
        """Check if connected to Multiflash DLL."""
        return self._connected and self.dll is not None

    @property
    def is_loaded(self) -> bool:
        """Check if an MFL file is loaded."""
        return self.mfl is not None and self.composition is not None

    def load_mfl(self, mfl_path: str) -> Dict[str, Any]:
        """
        Load a Multiflash .mfl file.

        Args:
            mfl_path: Path to the .mfl file

        Returns:
            Dict with composition info

        Raises:
            FileNotFoundError: If MFL file not found
            RuntimeError: If loading fails
        """
        if not self.is_connected:
            self.connect()

        if not os.path.exists(mfl_path):
            raise FileNotFoundError(f"MFL file not found: {mfl_path}")

        try:
            self.mfl = self.dll.load_mfl(mfl_path)
            self.composition = self.mfl.composition
            self.mfl_path = mfl_path

            # Extract fluid name from filename
            from pathlib import Path
            self.fluid_name = Path(mfl_path).stem

            return {
                "path": mfl_path,
                "num_components": len(self.composition),
                "composition": list(self.composition),
                "status": "loaded"
            }
        except Exception as e:
            raise RuntimeError(f"Failed to load MFL file: {e}")

    def pt_flash(self,
                 temperature: float,
                 pressure: float,
                 composition: Optional[List[float]] = None) -> FlashResult:
        """
        Perform PT flash calculation.

        Args:
            temperature: Temperature in K
            pressure: Pressure in Pa
            composition: Mole numbers (optional, uses loaded composition if None)

        Returns:
            FlashResult with phase information

        Raises:
            ValueError: If no composition available
            RuntimeError: If flash calculation fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Multiflash. Call connect() first.")

        comp = composition if composition is not None else self.composition
        if comp is None:
            raise ValueError(
                "No composition available. Either load an MFL file or provide composition."
            )

        try:
            res = self.dll.PTFlash(temperature, pressure, comp)

            # Get phase names from phase load numbers
            phase_names = self._get_phase_names(res.phases)

            return FlashResult(
                temperature=temperature,
                pressure=pressure,
                phases=list(res.phases),
                phase_names=phase_names,
                moles_per_phase=list(res.nmolph),
                compositions=[list(c) for c in res.composition]
            )
        except Exception as e:
            raise RuntimeError(
                f"PT flash failed at T={temperature} K, P={pressure/1e6:.2f} MPa: {e}"
            )

    def ph_flash(self,
                 pressure: float,
                 enthalpy: float,
                 composition: Optional[List[float]] = None) -> FlashResult:
        """
        Perform PH (pressure-enthalpy) flash calculation.

        This is essential for isenthalpic processes like:
        - Valve/choke expansion
        - Joule-Thomson cooling
        - Heat exchanger analysis

        Args:
            pressure: Pressure in Pa
            enthalpy: Molar enthalpy in J/mol
            composition: Mole numbers (optional, uses loaded composition if None)

        Returns:
            FlashResult with calculated temperature and phase information

        Raises:
            ValueError: If no composition available
            RuntimeError: If flash calculation fails or solid forms
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Multiflash. Call connect() first.")

        comp = composition if composition is not None else self.composition
        if comp is None:
            raise ValueError(
                "No composition available. Either load an MFL file or provide composition."
            )

        try:
            # PHFlash returns equilibrium state at given P, H
            res = self.dll.PHFlash(pressure, enthalpy, comp)

            # Get phase names from phase load numbers
            phase_names = self._get_phase_names(res.phases)

            # Check for solid formation (temperature below triple point)
            # CO2 triple point: 216.55 K (-56.6 C) at 5.18 bar
            if res.temperature < 216.0:  # Slightly below CO2 triple point
                raise RuntimeError(
                    f"SOLID_FORMED: Temperature {res.temperature:.2f} K is below "
                    f"CO2 triple point (216.55 K). Solid CO2 may form."
                )

            return FlashResult(
                temperature=res.temperature,
                pressure=pressure,
                phases=list(res.phases),
                phase_names=phase_names,
                moles_per_phase=list(res.nmolph),
                compositions=[list(c) for c in res.composition]
            )
        except RuntimeError:
            raise  # Re-raise our SOLID_FORMED error
        except Exception as e:
            error_str = str(e).upper()
            if 'SOLID' in error_str or 'TRIPLE' in error_str:
                raise RuntimeError(f"SOLID_FORMED: {e}")
            raise RuntimeError(
                f"PH flash failed at P={pressure/1e5:.2f} bar, H={enthalpy:.2f} J/mol: {e}"
            )

    def _get_phase_names(self, phase_lnos: List[int]) -> List[str]:
        """
        Get human-readable phase names from phase load numbers.

        Common phase load numbers in Multiflash:
        - 1: GAS
        - 2: LIQUID1 (oil/hydrocarbon)
        - 3: LIQUID2
        - 4: WATER
        """
        # This mapping may need adjustment based on your MFL setup
        phase_map = {
            1: "GAS",
            2: "LIQUID1",
            3: "LIQUID2",
            4: "WATER"
        }
        return [phase_map.get(lno, f"PHASE_{lno}") for lno in phase_lnos]

    def get_aymix_properties(self,
                             phase_lno: int,
                             temperature: float,
                             pressure: float,
                             composition: Optional[List[float]] = None,
                             get_volume_derivs: bool = True,
                             get_enthalpy_derivs: bool = False) -> AYMIXResult:
        """
        Get thermodynamic properties using AYMIX.

        This is the core function for getting density, bulk modulus K,
        and thermal expansion beta for the mass balance equation.

        Args:
            phase_lno: Phase load number from flash result
            temperature: Temperature in K
            pressure: Pressure in Pa
            composition: Mole fractions (uses flash result composition if None)
            get_volume_derivs: If True, get dV/dT and dV/dP
            get_enthalpy_derivs: If True, get Cp (dH/dT)

        Returns:
            AYMIXResult with thermodynamic properties
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Multiflash.")

        comp = composition if composition is not None else self.composition
        if comp is None:
            raise ValueError("No composition available.")

        # Set up flags: [value, dT, dP, dN]
        volume_flags = [True, get_volume_derivs, get_volume_derivs, False]
        enthalpy_flags = [get_enthalpy_derivs, get_enthalpy_derivs, False, False]
        fugacity_flags = [False, False, False, False]

        try:
            res = self.dll.AYMIX(
                phaseDescriptorLoadNumber=phase_lno,
                temperature=temperature,
                pressure=pressure,
                componentLoadNumbers=[],  # Use loaded components
                moleNumbers=comp,
                FugacityFlags=fugacity_flags,
                VolumeFlags=volume_flags,
                EnthalpyFlags=enthalpy_flags
            )

            return AYMIXResult(
                volume=res.volume if hasattr(res, 'volume') else 0.0,
                volume_T=res.volume_T if hasattr(res, 'volume_T') else 0.0,
                volume_P=res.volume_P if hasattr(res, 'volume_P') else 0.0,
                enthalpy=res.enthalpy if hasattr(res, 'enthalpy') else 0.0,
                enthalpy_T=res.enthalpy_T if hasattr(res, 'enthalpy_T') else 0.0
            )
        except Exception as e:
            raise RuntimeError(
                f"AYMIX failed for phase {phase_lno} at T={temperature} K, "
                f"P={pressure/1e6:.2f} MPa: {e}"
            )

    def get_molecular_weight(self, composition: Optional[List[float]] = None) -> float:
        """
        Get average molecular weight of mixture.

        Args:
            composition: Mole fractions (uses loaded if None)

        Returns:
            Molecular weight in kg/mol
        """
        comp = composition if composition is not None else self.composition
        if comp is None:
            raise ValueError("No composition available.")

        try:
            result = self.dll.AYAVMW(comp, [])
            # AYAVMW returns (MW, ...), MW is in g/mol, convert to kg/mol
            mw = result[0] / 1000.0  # g/mol -> kg/mol
            return mw
        except Exception as e:
            raise RuntimeError(f"Failed to get molecular weight: {e}")

    def get_viscosity(self,
                      phase_lno: int,
                      temperature: float,
                      pressure: float,
                      composition: Optional[List[float]] = None,
                      get_derivatives: bool = False) -> TransportResult:
        """
        Get viscosity of a phase using AYVISC.

        Args:
            phase_lno: Phase load number from flash result
            temperature: Temperature in K
            pressure: Pressure in Pa
            composition: Mole fractions (uses loaded if None)
            get_derivatives: If True, get dmu/dT and dmu/dP

        Returns:
            TransportResult with viscosity in Pa.s
        """
        comp = composition if composition is not None else self.composition
        if comp is None:
            raise ValueError("No composition available.")

        deriv_flags = [get_derivatives, get_derivatives, False]

        try:
            res = self.dll.AYVISC(
                phaseDescriptorLoadNumber=phase_lno,
                temperature=temperature,
                pressure=pressure,
                componentLoadNumbers=[],
                moleNumbers=comp,
                derivativeFlags=deriv_flags
            )
            # AYVISC returns viscosity in Pa.s
            return TransportResult(
                value=res.viscosity if hasattr(res, 'viscosity') else res[0],
                value_T=res.viscosity_T if hasattr(res, 'viscosity_T') else 0.0,
                value_P=res.viscosity_P if hasattr(res, 'viscosity_P') else 0.0
            )
        except Exception as e:
            raise RuntimeError(
                f"AYVISC failed for phase {phase_lno} at T={temperature} K, "
                f"P={pressure/1e6:.2f} MPa: {e}"
            )

    def get_thermal_conductivity(self,
                                 phase_lno: int,
                                 temperature: float,
                                 pressure: float,
                                 composition: Optional[List[float]] = None,
                                 get_derivatives: bool = False) -> TransportResult:
        """
        Get thermal conductivity of a phase using AYTCND.

        Args:
            phase_lno: Phase load number from flash result
            temperature: Temperature in K
            pressure: Pressure in Pa
            composition: Mole fractions (uses loaded if None)
            get_derivatives: If True, get dk/dT and dk/dP

        Returns:
            TransportResult with thermal conductivity in W/(m.K)
        """
        comp = composition if composition is not None else self.composition
        if comp is None:
            raise ValueError("No composition available.")

        deriv_flags = [get_derivatives, get_derivatives, False]

        try:
            res = self.dll.AYTCND(
                phaseDescriptorLoadNumber=phase_lno,
                temperature=temperature,
                pressure=pressure,
                componentLoadNumbers=[],
                moleNumbers=comp,
                derivativeFlags=deriv_flags
            )
            # AYTCND returns thermal conductivity in W/(m.K)
            return TransportResult(
                value=res.thermalConductivity if hasattr(res, 'thermalConductivity') else res[0],
                value_T=res.thermalConductivity_T if hasattr(res, 'thermalConductivity_T') else 0.0,
                value_P=res.thermalConductivity_P if hasattr(res, 'thermalConductivity_P') else 0.0
            )
        except Exception as e:
            raise RuntimeError(
                f"AYTCND failed for phase {phase_lno} at T={temperature} K, "
                f"P={pressure/1e6:.2f} MPa: {e}"
            )

    def get_critical_point(self,
                          composition: Optional[List[float]] = None) -> Tuple[float, float, float]:
        """
        Get critical point properties using AXCRIT.

        Args:
            composition: Mole numbers (uses loaded composition if None)

        Returns:
            Tuple of (Tc_K, Pc_Pa, Vc_m3_mol)

        Raises:
            ValueError: If no composition available
            RuntimeError: If critical point calculation fails
        """
        comp = composition if composition is not None else self.composition
        if comp is None:
            raise ValueError("No composition available.")

        try:
            res = self.dll.AXCRIT(comp)
            return (res.Tc, res.Pc, res.Vc)
        except Exception as e:
            raise RuntimeError(f"AXCRIT failed: {e}")

    def diagnose(self) -> Dict[str, Any]:
        """
        Run diagnostics to check Multiflash connection and capabilities.

        Returns:
            Dict with diagnostic information
        """
        diag = {
            "dll_path": self.dll_path,
            "db_path": self.db_path,
            "dll_exists": os.path.exists(self.dll_path),
            "db_exists": os.path.exists(self.db_path),
            "connected": self.is_connected,
            "mfl_loaded": self.is_loaded,
            "mfl_path": self.mfl_path,
            "composition": self.composition,
            "tests": {}
        }

        if not self.is_connected:
            diag["tests"]["connection"] = "FAILED - Not connected"
            return diag

        diag["tests"]["connection"] = "PASSED"

        if not self.is_loaded:
            diag["tests"]["mfl_load"] = "SKIPPED - No MFL file loaded"
            return diag

        diag["tests"]["mfl_load"] = "PASSED"

        # Test PT flash at safe conditions (away from critical point)
        try:
            result = self.pt_flash(temperature=350, pressure=5e6)
            diag["tests"]["pt_flash"] = f"PASSED - {result.num_phases} phase(s): {result.phase_names}"
        except Exception as e:
            diag["tests"]["pt_flash"] = f"FAILED - {e}"

        # Test AYMIX
        try:
            flash_result = self.pt_flash(temperature=350, pressure=5e6)
            if flash_result.phases:
                phase_lno = flash_result.phases[0]
                comp = flash_result.compositions[0]
                aymix_result = self.get_aymix_properties(
                    phase_lno=phase_lno,
                    temperature=350,
                    pressure=5e6,
                    composition=comp
                )
                diag["tests"]["aymix"] = f"PASSED - V={aymix_result.volume:.6e} m³/mol"
        except Exception as e:
            diag["tests"]["aymix"] = f"FAILED - {e}"

        # Test molecular weight
        try:
            mw = self.get_molecular_weight()
            diag["tests"]["molecular_weight"] = f"PASSED - MW={mw*1000:.2f} g/mol"
        except Exception as e:
            diag["tests"]["molecular_weight"] = f"FAILED - {e}"

        return diag


def create_wrapper(mfl_path: Optional[str] = None,
                   dll_path: str = DEFAULT_DLL_PATH,
                   db_path: str = DEFAULT_DB_PATH) -> MultiflashWrapper:
    """
    Convenience function to create and initialize a MultiflashWrapper.

    Args:
        mfl_path: Optional path to MFL file to load
        dll_path: Path to Multiflash DLL
        db_path: Path to Multiflash database directory

    Returns:
        Initialized MultiflashWrapper instance
    """
    wrapper = MultiflashWrapper(dll_path=dll_path, db_path=db_path)

    if mfl_path:
        wrapper.load_mfl(mfl_path)

    return wrapper
