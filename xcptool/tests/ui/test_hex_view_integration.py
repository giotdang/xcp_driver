"""MainWindow <-> HexView wiring — navigation, menu, Session calls.
HexView's own dialog/rendering/diff-highlight behavior is covered in
tests/ui/test_hex_view.py; this file only covers what MainWindow adds on
top of it. Fixtures (`window`, `session`, `qtbot`) come from
tests/ui/conftest.py.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMenu

from xcptool.a2l.types import A2LDatabase, Characteristic
from xcptool.session.api import AppConfig, BusConfig, ConnState
from xcptool.session.fake import FakeBehavior, FakeSession
from xcptool.ui.main_window import MainWindow


def test_hex_view_registered_as_third_nav_route(window: MainWindow) -> None:
    assert window.hex_view is not None
    assert window.stack.indexOf(window.hex_view) != -1


def test_switching_to_hex_route_persists_in_app_config(window: MainWindow) -> None:
    window.switch_to(window.hex_view)
    window.nav.setCurrentItem("hex")
    window._save_current_app_config()
    assert window._app_config.active_route == "hex"


def test_session_menu_has_load_hex_action(window: MainWindow) -> None:
    assert window.act_load_hex.text() == "&Load Hex/S19…"
    menus = window.menuBar().findChildren(QMenu)
    session_menu = next(m for m in menus if m.title() == "&Session")
    assert window.act_load_hex in session_menu.actions()


def test_load_hex_success_refreshes_origin_table(window: MainWindow, tmp_path: Path, qtbot) -> None:
    p = tmp_path / "image.hex"
    p.write_text(":080100000102030405060708D3\n:00000001FF\n", encoding="ascii")

    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x0100,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    window.hex_view.set_database(db)

    window._on_hex_load_requested(str(p))
    qtbot.waitUntil(lambda: window.hex_view.origin_table.rowCount() == 1, timeout=2000)
    assert window.hex_view.origin_table.item(0, 3).text() == "01"


def test_hexview_generate_requested_reaches_session_and_reports_error(window: MainWindow, qtbot, monkeypatch) -> None:
    # Exercises the MainWindow wiring only — HexView's own dialog/patch-
    # building behavior is covered in test_hex_view.py. `window`'s
    # FakeSession has no hex file loaded here, so this exercises (and
    # pins) the error path: the call must reach HexView, not crash
    # MainWindow or silently vanish.
    #
    # on_generate_error() shows a real QMessageBox.critical(...) — under the
    # offscreen QPA platform that blocks indefinitely without a mock (same
    # class of hang as QFileDialog, confirmed empirically: this test hung
    # past pytest-timeout's 60s watchdog before this monkeypatch was added).
    monkeypatch.setattr(
        "xcptool.ui.hex_view.QMessageBox.critical", lambda *a, **k: None
    )

    window._on_hexview_generate_requested([(0x1000, b"\x2A", "kp")], "C:/proj/out.hex")
    # status_label starts non-empty ("Load an A2L…"), so waiting on it merely
    # being non-empty would pass instantly without ever observing the async
    # call land — wait for the actual expected text instead.
    qtbot.waitUntil(
        lambda: "Generate failed" in window.hex_view.status_label.text(), timeout=2000
    )


def test_connect_success_persists_byte_order_and_updates_hexview(qtbot) -> None:
    # FakeSession.connect() hardcodes SlaveCaps(byte_order="little", ...) —
    # it cannot be made to report "big". Pre-seed a non-default starting
    # value so a pass proves the wiring actually ran, not that the field
    # already matched its default.
    session = FakeSession(FakeBehavior())
    session._app_cfg = AppConfig(
        bus=BusConfig(backend="virtual", channel="fake0"), last_byte_order="big",
    )
    window = MainWindow(session)
    qtbot.addWidget(window)

    window.connect_to(BusConfig(backend="virtual", channel="fake0"))
    qtbot.waitUntil(lambda: window.session.state is ConnState.CONNECTED, timeout=5000)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)

    assert window._app_config.last_byte_order == "little"  # FakeSession always reports "little"
    assert window.hex_view.byte_order_combo.currentText() == "Little Endian"
    window.close()


def test_startup_auto_reloads_last_hex_path_if_file_exists(tmp_path: Path, qtbot) -> None:
    p = tmp_path / "golden.hex"
    p.write_text(":080100000102030405060708D3\n:00000001FF\n", encoding="ascii")

    session = FakeSession(FakeBehavior())
    session._app_cfg = AppConfig(
        bus=BusConfig(backend="virtual", channel="fake0"), last_hex_path=str(p),
    )
    window = MainWindow(session)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.hex_view._hex_loaded, timeout=2000)
    assert window.hex_view._hex_path_str == str(p)
    window.close()
