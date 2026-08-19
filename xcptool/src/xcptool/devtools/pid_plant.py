"""Mô phỏng một 'nhà máy' (plant) tốc độ xe điều khiển bằng PID, chạy trên
`FakeSlave`, khớp với `examples/xcp_daq_example.a2l`.

Ý tưởng: CHARACTERISTIC (`speedPid_kp/_ki/_kd/_outMin/_outMax`) là input
calibration thật — người dùng ghi qua panel Hiệu chỉnh của xcptool y hệt ECU
thật. Vòng lặp ở đây đọc lại các giá trị đó bằng `FakeSlave.peek()`, chạy một
bước PID + mô hình vật lý đơn giản, rồi ghi kết quả (`vehicleSpeedKph`,
`engineRpm`, `speedPidTelemetry_*`, ...) bằng `FakeSlave.poke()`. DAQ send
loop của FakeSlave đọc đúng những byte này như đọc RAM thật — không có
đường tắt nào qua giao thức XCP.

Không phải test đơn vị — chỉ để DEMO "đổi calibration → đổi measurement"
thật sự hoạt động, thứ mà một sóng sine tĩnh không chứng minh được.
"""

from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass

from .fakeslave import FakeSlave

__all__ = ["PidPlantAddresses", "PidPlant"]


@dataclass(frozen=True)
class PidPlantAddresses:
    """Địa chỉ khớp `examples/xcp_daq_example.a2l` — sửa ở đây nếu A2L đổi."""

    # CHARACTERISTIC (calibration — plant CHỈ ĐỌC, không tự ghi)
    speed_pid_kp: int = 0x80100050
    speed_pid_ki: int = 0x80100054
    speed_pid_kd: int = 0x80100058
    speed_pid_out_min: int = 0x8010005C
    speed_pid_out_max: int = 0x80100060
    temp_comp_table: int = 0x80100044   # VAL_BLK, 6 × SWORD (int16)

    # MEASUREMENT (output — plant tự ghi mỗi tick)
    daq_heartbeat: int = 0x90000000
    engine_rpm: int = 0x90000004
    vehicle_speed_kph: int = 0x90000008
    coolant_temp_c: int = 0x9000000C
    pid_error: int = 0x90000010
    pid_integral: int = 0x90000014
    pid_output: int = 0x90000018
    torque_samples: int = 0x9000001C   # 4 × float32, lịch sử 4 tick gần nhất


_TARGET_SPEED_KPH = 80.0
"""Setpoint mô phỏng cố định — thông số MÔI TRƯỜNG (như tài xế đạp ga tới
80km/h rồi giữ), không phải calibration nên không đặt ở CHARACTERISTIC nào."""

_LOAD_TORQUE_NM = 30.0
"""Tải cản không đổi (ma sát + khí động học) — PID phải thắng được lực này."""

_VEHICLE_MASS_EFFECTIVE = 25.0
"""Hằng số quy đổi torque → gia tốc, chọn để hội tụ trong vài giây — vừa đủ
để nhìn thấy đường cong trên scope, không phải giá trị vật lý thật."""

_RPM_PER_KPH = 30.0
_RPM_IDLE = 800.0
_UPDATE_HZ = 50.0
_TEMP_COMP_TABLE_COUNT = 6


class PidPlant:
    """Chạy trong thread riêng. Dùng như context manager hoặc gọi start()/stop()."""

    def __init__(self, slave: FakeSlave, addrs: PidPlantAddresses | None = None) -> None:
        self._slave = slave
        self._addr = addrs or PidPlantAddresses()
        self._bo = slave.cfg.byte_order
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._speed = 0.0
        self._integral = 0.0
        self._heartbeat = 0
        self._torque_hist = [0.0, 0.0, 0.0, 0.0]

        self._seed_defaults()

    def _seed_defaults(self) -> None:
        """Golden defaults hợp lý cho gain — 0.0 (mặc định bytearray) làm PID
        chết đứng (output luôn 0), không phải trạng thái khởi động ECU thật
        thường có (calROM có sẵn giá trị nhà máy)."""
        a = self._addr
        self._poke_f32(a.speed_pid_kp, 8.0)
        self._poke_f32(a.speed_pid_ki, 2.0)
        self._poke_f32(a.speed_pid_kd, 0.0)
        self._poke_f32(a.speed_pid_out_min, -200.0)
        self._poke_f32(a.speed_pid_out_max, 200.0)

    def start(self) -> "PidPlant":
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="fake-slave-plant", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None

    def __enter__(self) -> "PidPlant":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ── vòng lặp mô phỏng ────────────────────────────────────────────────────

    def _loop(self) -> None:
        period = 1.0 / _UPDATE_HZ
        next_at = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_at:
                time.sleep(min(next_at - now, 0.01))
                continue
            next_at += period
            self._step(period)

    def _step(self, dt: float) -> None:
        a = self._addr
        kp = self._peek_f32(a.speed_pid_kp)
        ki = self._peek_f32(a.speed_pid_ki)
        out_min = self._peek_f32(a.speed_pid_out_min)
        out_max = self._peek_f32(a.speed_pid_out_max)
        if out_max < out_min:  # ECU thật cũng không tự sửa calibration vô lý
            out_min, out_max = out_max, out_min

        error = _TARGET_SPEED_KPH - self._speed
        self._integral += error * dt
        if ki > 1e-6:  # chống windup — kẹp integral theo biên output / ki
            bound = max(abs(out_min), abs(out_max)) / ki
            self._integral = max(-bound, min(bound, self._integral))

        output = kp * error + ki * self._integral
        output = max(out_min, min(out_max, output))

        net_torque = output - _LOAD_TORQUE_NM
        accel = net_torque / _VEHICLE_MASS_EFFECTIVE
        self._speed = max(0.0, min(250.0, self._speed + accel * dt))
        self._heartbeat = (self._heartbeat + 1) & 0xFFFF_FFFF
        self._torque_hist = self._torque_hist[1:] + [output]

        engine_rpm = min(8000.0, _RPM_IDLE + self._speed * _RPM_PER_KPH)
        # Công thức đơn giản, dễ tính tay để verify: trung bình cộng
        # tempCompTable (CHARACTERISTIC, 6 phần tử int16) — không mang ý
        # nghĩa vật lý thật, chỉ để kiểm chứng "ghi calib → đổi measurement"
        # bằng một phép tính không cần chạy simulator để đối chiếu.
        comp_values = self._peek_i16_array(a.temp_comp_table, _TEMP_COMP_TABLE_COUNT)
        coolant = sum(comp_values) / len(comp_values)

        self._poke_u32(a.daq_heartbeat, self._heartbeat)
        self._poke_u16(a.engine_rpm, int(engine_rpm))
        self._poke_f32(a.vehicle_speed_kph, self._speed)
        self._poke_f32(a.coolant_temp_c, coolant)
        self._poke_f32(a.pid_error, error)
        self._poke_f32(a.pid_integral, self._integral)
        self._poke_f32(a.pid_output, output)
        for i, v in enumerate(self._torque_hist):
            self._poke_f32(a.torque_samples + i * 4, v)

    # ── pack/unpack qua FakeSlave.peek()/poke() ─────────────────────────────

    def _endian(self) -> str:
        return "<" if self._bo == "little" else ">"

    def _peek_f32(self, addr: int) -> float:
        raw = self._slave.peek(addr, 4)
        return struct.unpack(self._endian() + "f", raw)[0]

    def _peek_i16_array(self, addr: int, count: int) -> list[int]:
        raw = self._slave.peek(addr, count * 2)
        return list(struct.unpack(self._endian() + "h" * count, raw))

    def _poke_f32(self, addr: int, value: float) -> None:
        self._slave.poke(addr, struct.pack(self._endian() + "f", value))

    def _poke_u32(self, addr: int, value: int) -> None:
        self._slave.poke(addr, value.to_bytes(4, self._bo))  # type: ignore[arg-type]

    def _poke_u16(self, addr: int, value: int) -> None:
        self._slave.poke(addr, (value & 0xFFFF).to_bytes(2, self._bo))  # type: ignore[arg-type]
