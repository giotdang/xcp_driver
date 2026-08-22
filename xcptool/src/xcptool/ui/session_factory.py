"""Chọn hiện thực Session lúc chạy. Không import Qt — CLI dùng lại được."""

from __future__ import annotations

from typing import Any

__all__ = ["SESSION_KINDS", "create_session"]

SESSION_KINDS = ("fake", "real")


_FAKE_MEM_SIZE = 0x1000_1000
"""Đủ phủ CHARACTERISTIC (~0x80100000+) LẪN MEASUREMENT (~0x90000000+) của
examples/xcp_daq_example.a2l trong MỘT cửa sổ liên tục từ mem_base — đơn
giản hơn nhiều vùng nhớ rời rạc, phần giữa không dùng chỉ tốn RAM (~256 MiB
bytearray, không đáng kể). Chỉ override cho phiên demo này, không đổi default
của SlaveConfig — test khác vẫn dựa vào cửa sổ 1 KiB nhỏ để kiểm OUT_OF_RANGE."""


class _FakeEcuSession:
    """`RealSession` nối với `FakeSlave` (ECU giả) qua virtual CAN bus nội bộ.

    KHÔNG tự chế trạng thái/chuỗi lệnh DAQ như `session.fake.FakeSession` —
    `XcpMaster` gửi ĐÚNG chuỗi lệnh XCP thật (FREE_DAQ→ALLOC_DAQ→ALLOC_ODT→
    WRITE_DAQ→...→START_STOP_SYNCH, xem `master/daq.py::configure_daq`), và
    `FakeSlave` (devtools/fakeslave.py) thật sự xử lý/trả lời từng lệnh đó
    qua bus — không có gì "tự bơm" dữ liệu tắt qua mặt giao thức. Đường code
    khác ECU thật đúng MỘT chỗ: transport là `virtual` thay vì pcan/vector/...

    Đi kèm `PidPlant` (`devtools/pid_plant.py`) — một mô phỏng nhỏ khớp
    `examples/xcp_daq_example.a2l`: đọc calibration (`speedPid_kp/_ki/...`)
    và TÍNH RA measurement (`vehicleSpeedKph`, `speedPidTelemetry_*`...) thay
    đổi thật theo thời gian. Không nằm trong `fakeslave.py` (core vẫn hoàn
    toàn không biết A2L nào) — đây là lựa chọn CÓ CHỦ ĐÍCH riêng cho demo GUI.
    """

    def __init__(self) -> None:
        from ..devtools.fakeslave import FakeSlave, SlaveConfig
        from ..devtools.pid_plant import PidPlant
        from ..session.api import BusConfig
        from ..session.real import RealSession

        defaults = BusConfig(backend="virtual", channel="xcptool")
        self._slave = FakeSlave(SlaveConfig(
            channel=defaults.channel, cro_id=defaults.cro_id, dto_id=defaults.dto_id,
            mem_size=_FAKE_MEM_SIZE,
            is_fd=True, max_cto=64, max_dto=64,
        )).start()
        self._plant = PidPlant(self._slave).start()
        self._session = RealSession()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def close(self) -> None:
        self._session.close()
        self._plant.stop()
        self._slave.stop()


def create_session(kind: str) -> Any:
    """`kind` = 'fake' (RealSession + FakeSlave qua virtual bus — không cần
    phần cứng, nhưng Master vẫn chạy đúng giao thức XCP thật) | 'real'
    (RealSession với phần cứng CAN thật)."""
    if kind == "fake":
        return _FakeEcuSession()
    if kind == "real":
        try:
            from ..session.real import RealSession  # type: ignore[attr-defined]
        except ImportError as exc:
            raise SystemExit(
                "Chưa có xcptool.session.real (backend đang viết). "
                "Chạy với --session fake để dùng bản giả."
            ) from exc
        return RealSession()
    raise SystemExit(f"--session chỉ nhận {' | '.join(SESSION_KINDS)}, không phải '{kind}'")
