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
