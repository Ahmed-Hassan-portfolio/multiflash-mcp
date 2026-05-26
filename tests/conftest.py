"""
Test fixtures and skip-logic for tests that need a live Multiflash install.

The skip check is a lightweight DLL/package availability check only — it
does NOT load the DLL or trigger the license check, because doing so would
have side effects at test-collection time. Specifically, tests marked
`@pytest.mark.requires_multiflash` are skipped when:

  - the Multiflash Python package isn't importable, or
  - the DLL pointed at by MULTIFLASH_DLL_PATH doesn't exist on disk.

If both are present, the marked tests run and exercise the real DLL. A
license failure surfaces inside those tests (or in the fixture below)
rather than at skip time. Tests without the marker run unconditionally
and must not touch the DLL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXAMPLES_DATA = PROJECT_ROOT / "examples" / "data"
PURE_CO2_MFL = EXAMPLES_DATA / "Pure_CO2.mfl"


def _multiflash_available() -> tuple[bool, str]:
    try:
        import multiflash  # noqa: F401
    except ImportError:
        return False, "multiflash Python package not installed"

    dll_path = os.environ.get(
        "MULTIFLASH_DLL_PATH",
        r"C:\program files\KBC\Multiflash 7.5\x64\mfpvt64.dll",
    )
    if not os.path.exists(dll_path):
        return False, f"DLL not found at {dll_path}"
    return True, ""


_AVAILABLE, _REASON = _multiflash_available()


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason=f"Multiflash not available: {_REASON}")
    for item in items:
        if "requires_multiflash" in item.keywords and not _AVAILABLE:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def wrapper():
    """Session-scoped Multiflash wrapper with Pure_CO2.mfl loaded."""
    from mcp_server.multiflash_wrapper import MultiflashWrapper

    w = MultiflashWrapper()
    w.load_mfl(str(PURE_CO2_MFL))
    return w
