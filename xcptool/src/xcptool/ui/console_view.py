"""Console lệnh thô — gõ hex, gửi CTO, xem byte thô ECU trả về.

`raw_command(raise_on_error=False)` TRẢ VỀ frame lỗi thay vì ném, đúng ý đồ của
contract: ở đây user muốn nhìn byte, không muốn hộp thoại.
"""

from __future__ import annotations

from collections import deque
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    TextEdit,
)

__all__ = ["ConsoleView", "parse_hex"]

_HISTORY = 50


def parse_hex(text: str) -> bytes:
    """'FF 00', 'ff00', '0xFF,0x00' → b'\\xff\\x00'. Ném ValueError nếu sai."""
    cleaned = text.replace(",", " ").replace("0x", " ").replace("0X", " ")
    tokens = cleaned.split()
    if not tokens:
        raise ValueError("Chưa nhập byte nào")

    out = bytearray()
    for tok in tokens:
        if len(tok) % 2 != 0:
            raise ValueError(f"'{tok}' lẻ ký tự — mỗi byte phải đủ 2 chữ số hex")
        for i in range(0, len(tok), 2):
            pair = tok[i:i + 2]
            try:
                out.append(int(pair, 16))
            except ValueError:
                raise ValueError(f"'{pair}' không phải số hex") from None
    if len(out) > 255:
        raise ValueError("Payload quá dài")
    return bytes(out)


class ConsoleView(QWidget):
    """`send_cb(payload, raise_on_error)` do MainWindow cấp — nó lo worker thread."""

    def __init__(
        self,
        send_cb: Callable[[bytes, bool], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("consoleView")
        self._send_cb = send_cb
        self._history: deque[str] = deque(maxlen=_HISTORY)
        self._history_pos = 0

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)

        self.output = TextEdit(self)
        self.output.setReadOnly(True)
        self.output.setFont(mono)

        self.input = LineEdit(self)
        self.input.setPlaceholderText("Nhập CTO dạng hex, ví dụ: FF 00  (CONNECT)")
        self.input.setFont(mono)
        self.input.returnPressed.connect(self.send)
        self.input.installEventFilter(self)

        self.send_btn = PrimaryPushButton("Gửi", self)
        self.send_btn.clicked.connect(self.send)

        self.clear_btn = PushButton("Xoá", self)
        self.clear_btn.clicked.connect(self.output.clear)

        self.raise_cb = CheckBox("Coi response lỗi là ngoại lệ", self)
        self.raise_cb.setToolTip(
            "Tắt (mặc định): frame 0xFE được in ra để tự nhìn byte.\n"
            "Bật: lỗi của ECU hiện thành hộp thoại như các lệnh khác."
        )

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        row.addWidget(self.clear_btn)

        quick = QHBoxLayout()
        quick.addWidget(BodyLabel("Lệnh nhanh:", self))
        for label, payload in (
            ("CONNECT", "FF 00"),
            ("GET_STATUS", "FD"),
            ("SYNCH", "FC"),
            ("GET_ID", "FA 00"),
            ("DISCONNECT", "FE"),
        ):
            btn = PushButton(label, self)
            btn.clicked.connect(lambda _=False, p=payload: self.input.setText(p))
            quick.addWidget(btn)
        quick.addStretch(1)
        quick.addWidget(self.raise_cb)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self.output, 1)
        layout.addLayout(quick)
        layout.addLayout(row)
        layout.addWidget(CaptionLabel(
            "Byte 0 của response: 0xFF = OK, 0xFE = ECU báo lỗi, 0xFD = event. "
            "Cùng những frame này cũng xuất hiện trong cửa sổ Trace CAN.", self))

    # ── gửi / nhận ───────────────────────────────────────────────────────────

    def send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        try:
            payload = parse_hex(text)
        except ValueError as exc:
            self.log_line(f"!!! {exc}")
            return
        self._history.append(text)
        self._history_pos = len(self._history)
        self.input.clear()
        self.log_line(">>> " + " ".join(f"{b:02X}" for b in payload))
        self._send_cb(payload, self.raise_cb.isChecked())

    def on_response(self, data: bytes) -> None:
        hexed = " ".join(f"{b:02X}" for b in data)
        tag = "ERR" if data and data[0] == 0xFE else "OK "
        self.log_line(f"<<< {hexed}    [{tag}]")

    def on_error(self, message: str) -> None:
        self.log_line(f"!!! {message}")

    def log_line(self, line: str) -> None:
        self.output.append(line)
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ── lịch sử bằng phím mũi tên ────────────────────────────────────────────

    def eventFilter(self, obj: object, event: object) -> bool:  # type: ignore[override]
        if obj is self.input and getattr(event, "type", lambda: None)() == event.Type.KeyPress:
            key = event.key()
            if key == Qt.Key_Up and self._history:
                self._history_pos = max(0, self._history_pos - 1)
                self.input.setText(self._history[self._history_pos])
                return True
            if key == Qt.Key_Down and self._history:
                self._history_pos = min(len(self._history), self._history_pos + 1)
                if self._history_pos == len(self._history):
                    self.input.clear()
                else:
                    self.input.setText(self._history[self._history_pos])
                return True
        return super().eventFilter(obj, event)
