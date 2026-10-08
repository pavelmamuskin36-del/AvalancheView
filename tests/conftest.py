import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt6")

import pytest  # noqa: E402

from avalanche_view.data.demo import create_demo_dataset  # noqa: E402
from avalanche_view.data.wrf_dataset import WRFDataset  # noqa: E402


@pytest.fixture(scope="session")
def demo_path(tmp_path_factory):
    return create_demo_dataset(
        tmp_path_factory.mktemp("data") / "demo.nc", timesteps=6, ny=12, nx=16
    )


@pytest.fixture
def dataset(demo_path):
    with WRFDataset(demo_path) as data:
        yield data
