"""Theme tối dùng `setTheme(Theme.DARK)` của Fluent-Widgets.

QMenuBar và QStatusBar là widget Qt chuẩn, không nằm trong bộ Fluent, nên chỉ
hai thứ đó cần QSS thủ công — đúng như DESIGN.md QĐ5 đã lường trước.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import Theme, isDarkTheme, setTheme

__all__ = ["apply_theme", "CHROME_QSS_DARK", "CHROME_QSS_LIGHT"]

CHROME_QSS_DARK = """
QMainWindow, QWidget#chrome { background: #202020; }
QMenuBar { background: #202020; color: #e8e8e8; border: none; padding: 2px; }
QMenuBar::item { padding: 4px 10px; background: transparent; border-radius: 4px; }
QMenuBar::item:selected { background: #3a3a3a; }
QMenu { background: #2b2b2b; color: #e8e8e8; border: 1px solid #3a3a3a; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 4px; }
QMenu::item:selected { background: #3a3a3a; }
QMenu::separator { height: 1px; background: #3a3a3a; margin: 4px 8px; }
QStatusBar { background: #1a1a1a; color: #c8c8c8; }
QStatusBar::item { border: none; }
QDockWidget { background: #202020; color: #e8e8e8; border: 1px solid #3a3a3a; }
QMainWindow::separator { background: #3a3a3a; width: 5px; height: 5px; }
QMainWindow::separator:hover { background: #6b6b6b; }
QTabBar::pane { border: none; }
QTabBar::tab {
    background: #2b2b2b; color: #c8c8c8; padding: 6px 14px;
    border: 1px solid #3a3a3a; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #202020; color: #e8e8e8; border-bottom: 2px solid #0078d4; }
QTabBar::tab:hover:!selected { background: #3a3a3a; }
"""

CHROME_QSS_LIGHT = """
QMainWindow, QWidget#chrome { background: #f3f3f3; }
QMenuBar { background: #f3f3f3; color: #1a1a1a; border: none; padding: 2px; }
QMenuBar::item { padding: 4px 10px; background: transparent; border-radius: 4px; }
QMenuBar::item:selected { background: #e0e0e0; }
QMenu { background: #ffffff; color: #1a1a1a; border: 1px solid #d8d8d8; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 4px; }
QMenu::item:selected { background: #ececec; }
QStatusBar { background: #e9e9e9; color: #303030; }
QStatusBar::item { border: none; }
QDockWidget { background: #f3f3f3; color: #1a1a1a; border: 1px solid #d8d8d8; }
QMainWindow::separator { background: #d8d8d8; width: 5px; height: 5px; }
QMainWindow::separator:hover { background: #a8a8a8; }
QTabBar::pane { border: none; }
QTabBar::tab {
    background: #e9e9e9; color: #404040; padding: 6px 14px;
    border: 1px solid #d8d8d8; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #f3f3f3; color: #1a1a1a; border-bottom: 2px solid #0078d4; }
QTabBar::tab:hover:!selected { background: #ececec; }
"""


def apply_theme(window: QWidget, dark: bool = True) -> None:
    setTheme(Theme.DARK if dark else Theme.LIGHT)
    window.setStyleSheet(CHROME_QSS_DARK if isDarkTheme() else CHROME_QSS_LIGHT)
