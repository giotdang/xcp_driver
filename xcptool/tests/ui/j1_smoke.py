"""J1 — cùng kịch bản GUI, nhưng chạy trên RealSession + fake slave của backend.

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/ui/j1_smoke.py

Chỉ đổi ĐÚNG một thứ so với `--session fake`: hiện thực Session. Nếu kịch bản
selftest cho kết quả giống hệt thì phần frontend đã sẵn sàng ghép.

Script chạy tay, pytest không thu — J1 là mốc chung, lead điều phối.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig
from xcptool.session.real import RealSession
from xcptool.ui.app import ensure_utf8_stdio
from xcptool.ui.logging_setup import install_excepthooks, setup_logging
from xcptool.ui.main_window import MainWindow
from xcptool.ui.selftest import run_selftest

# Phải trùng kênh mà transport/registry.py quảng cáo cho backend 'virtual',
# nếu không thì slave ngồi trên một bus khác và CONNECT sẽ hết giờ.
CHANNEL = "xcptool"


def main() -> int:
    ensure_utf8_stdio()
    setup_logging()

    # Slave mặc định nghe CRO 0x600, còn selftest dựng BusConfig mặc định (0x7E0).
    # Lấy CAN ID từ chính BusConfig để hai bên không lệch nhau.
    bus_defaults = BusConfig(backend="", channel="")
    slave = FakeSlave(SlaveConfig(
        channel=CHANNEL,
        cro_id=bus_defaults.cro_id,
        dto_id=bus_defaults.dto_id,
    ))
    slave.start()
    try:
        app = QApplication.instance() or QApplication(sys.argv[:1])
        session = RealSession()
        window = MainWindow(session)
        install_excepthooks(window.report_unexpected)
        window.show()
        return run_selftest(app, window)
    finally:
        slave.stop()


if __name__ == "__main__":
    raise SystemExit(main())
