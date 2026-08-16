"""F3 — console lệnh thô.

Cổng của mốc này: gửi `FF 00` thấy response `FF …` xuất hiện CẢ trong console
LẪN trong cửa sổ debug CAN — tức là cùng một frame, không phải hai đường riêng.
"""

from __future__ import annotations

import pytest

from xcptool.ui.console_view import parse_hex
from xcptool.ui.main_window import MainWindow


# ── phân tích hex ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("FF 00", b"\xff\x00"),
    ("ff00", b"\xff\x00"),
    ("0xFF 0x00", b"\xff\x00"),
    ("FF,00", b"\xff\x00"),
    ("  F4 04 00 00  ", b"\xf4\x04\x00\x00"),
    ("FD", b"\xfd"),
])
def test_parse_hex_cac_dang_go_thuong_gap(text: str, expected: bytes) -> None:
    assert parse_hex(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "FFF", "ZZ", "0xGG"])
def test_parse_hex_go_sai_thi_bao_loi_ro_rang(text: str) -> None:
    with pytest.raises(ValueError):
        parse_hex(text)


# ── luồng gửi / nhận ─────────────────────────────────────────────────────────

def test_gui_ff00_thay_response_ff_trong_console(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    w.console_view.input.setText("FF 00")
    w.console_view.send()
    qtbot.waitUntil(lambda: "<<<" in w.console_view.output.toPlainText(), timeout=5000)

    text = w.console_view.output.toPlainText()
    assert ">>> FF 00" in text
    assert "<<< FF" in text
    assert "[OK ]" in text


def test_cung_frame_do_xuat_hien_trong_cua_so_trace(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    w.trace_view.clear()
    w.console_view.input.setText("FF 00")
    w.console_view.send()
    qtbot.waitUntil(lambda: "<<<" in w.console_view.output.toPlainText(), timeout=5000)
    qtbot.waitUntil(lambda: w.trace_view.model.rowCount() >= 2, timeout=2000)

    entries = w.trace_view.model.visible_entries()
    sent = [e for e in entries if e.direction == "tx" and e.data[0] == 0xFF]
    got = [e for e in entries if e.direction == "rx" and e.data[0] == 0xFF]
    assert sent and got, "lệnh thô phải hiện trong cửa sổ debug như mọi frame khác"


def test_response_loi_duoc_in_ra_chu_khong_nem(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    w.console_view.input.setText("55")            # lệnh ECU không biết
    w.console_view.send()
    qtbot.waitUntil(lambda: "<<<" in w.console_view.output.toPlainText(), timeout=5000)

    text = w.console_view.output.toPlainText()
    assert "<<< FE" in text, "raise_on_error=False thì frame lỗi phải in ra để user tự nhìn"
    assert "[ERR]" in text


def test_bat_raise_on_error_thi_thanh_thong_bao(
    qtbot, connected_window: MainWindow, monkeypatch
) -> None:
    from xcptool.ui import errors

    w = connected_window
    shown: list[BaseException] = []
    monkeypatch.setattr(errors, "show_error", lambda parent, e: shown.append(e))

    w.console_view.raise_cb.setChecked(True)
    w.console_view.input.setText("55")
    w.console_view.send()
    qtbot.waitUntil(lambda: "!!!" in w.console_view.output.toPlainText(), timeout=5000)

    assert "CRC_CMD_UNKNOWN" in w.console_view.output.toPlainText()
    assert not shown, "lỗi của ECU đã hiện trong console rồi, không cần hộp thoại nữa"


def test_go_sai_hex_khong_gui_gi_len_bus(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    qtbot.wait(200)          # để trace của bước CONNECT chảy hết vào bảng
    w.trace_view.clear()
    w.console_view.input.setText("ZZ")
    w.console_view.send()
    qtbot.wait(200)
    assert "!!!" in w.console_view.output.toPlainText()
    assert w.trace_view.model.rowCount() == 0


def test_chua_ket_noi_thi_bao_ro_thay_vi_im_lang(qtbot, window: MainWindow) -> None:
    window.console_view.input.setText("FF 00")
    window.console_view.send()
    qtbot.wait(100)
    assert "Chưa kết nối" in window.console_view.output.toPlainText()


def test_lich_su_bang_phim_mui_ten(qtbot, connected_window: MainWindow) -> None:
    from PySide6.QtCore import Qt

    w = connected_window
    for cmd in ("FD", "FF 00"):
        w.console_view.input.setText(cmd)
        w.console_view.send()
        qtbot.wait(50)

    qtbot.keyClick(w.console_view.input, Qt.Key_Up)
    assert w.console_view.input.text() == "FF 00"
    qtbot.keyClick(w.console_view.input, Qt.Key_Up)
    assert w.console_view.input.text() == "FD"


def test_nut_lenh_nhanh_dien_vao_o_nhap(qtbot, window: MainWindow) -> None:
    from PySide6.QtCore import Qt
    from qfluentwidgets import PushButton

    buttons = {b.text(): b for b in window.console_view.findChildren(PushButton)}
    qtbot.mouseClick(buttons["CONNECT"], Qt.LeftButton)
    assert window.console_view.input.text() == "FF 00"
