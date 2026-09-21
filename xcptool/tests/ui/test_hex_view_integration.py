"""MainWindow <-> HexView wiring — navigation, menu, Session calls.
HexView's own dialog/rendering/diff-highlight behavior is covered in
tests/ui/test_hex_view.py; this file only covers what MainWindow adds on
top of it. Fixtures (`window`, `session`, `qtbot`) come from
tests/ui/conftest.py.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu

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
