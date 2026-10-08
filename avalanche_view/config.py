import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_PATH = PROJECT_ROOT / "demo_data" / "demo_wrf.nc"
CACHE_LIMIT_BYTES = 128 * 1024 * 1024
ORGANIZATION = "AvalancheView"
APPLICATION = "AvalancheView"


def runtime_root() -> Path:
    """Keep frozen-app writes outside PyInstaller's temporary resource directory."""
    if not getattr(sys, "frozen", False):
        return PROJECT_ROOT / ".runtime"
    override = os.environ.get("AVALANCHEVIEW_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return local / APPLICATION


RUNTIME_ROOT = runtime_root()
LOG_DIRECTORY = RUNTIME_ROOT / "logs" if getattr(sys, "frozen", False) else PROJECT_ROOT / "logs"
DEFAULT_DATA_DIRECTORY = Path(sys.executable).parent if getattr(sys, "frozen", False) else PROJECT_ROOT / "demo_data"
