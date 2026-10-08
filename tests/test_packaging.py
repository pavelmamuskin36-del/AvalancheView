"""Frozen runtime paths must survive temporary extraction and read-only installs."""

import sys

from avalanche_view.config import PROJECT_ROOT, runtime_root


def test_source_runtime_path(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("AVALANCHEVIEW_DATA_DIR", str(tmp_path))
    assert runtime_root() == PROJECT_ROOT / ".runtime"


def test_frozen_runtime_is_user_writable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("AVALANCHEVIEW_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert runtime_root() == tmp_path / "AvalancheView"


def test_frozen_runtime_override(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("AVALANCHEVIEW_DATA_DIR", str(tmp_path / "portable data"))
    assert runtime_root() == (tmp_path / "portable data").resolve()
