"""Fixture dùng chung cho test GUI.

Chạy headless: `QT_QPA_PLATFORM=offscreen`. Cảnh báo "Cannot find font directory"
là vô hại (DEV_PLAN.md §5.1) — đừng đi sửa.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from xcptool.session.api import BusConfig  # noqa: E402
from xcptool.session.fake import FakeBehavior, FakeSession  # noqa: E402
from xcptool.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Không test nào được treo vì một hộp thoại modal chờ người bấm."""
    from qfluentwidgets import MessageBox, MessageBoxBase

    monkeypatch.setattr(MessageBox, "exec", lambda self, *a, **k: 0, raising=False)
    monkeypatch.setattr(MessageBoxBase, "exec", lambda self, *a, **k: 0, raising=False)


@pytest.fixture
def host(qtbot):
    """Dialog Fluent dựng trên MaskDialogBase nên BẮT BUỘC có parent widget —
    không có parent thì nó đọc parent.width() và vỡ ngay trong __init__."""
    from PySide6.QtWidgets import QWidget

    w = QWidget()
    w.resize(900, 700)
    qtbot.addWidget(w)
    return w


@pytest.fixture
def behavior() -> FakeBehavior:
    return FakeBehavior()


@pytest.fixture
def session(behavior: FakeBehavior) -> FakeSession:
    s = FakeSession(behavior)
    yield s
    s.close()


@pytest.fixture
def window(qtbot, session: FakeSession) -> MainWindow:
    w = MainWindow(session)
    qtbot.addWidget(w)
    yield w
    w.close()


@pytest.fixture
def cfg() -> BusConfig:
    return BusConfig(backend="virtual", channel="fake0")


@pytest.fixture
def connected_window(qtbot, window: MainWindow, cfg: BusConfig) -> MainWindow:
    from xcptool.session.api import ConnState

    window.connect_to(cfg)
    qtbot.waitUntil(lambda: window.session.state is ConnState.CONNECTED, timeout=5000)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)
    return window
