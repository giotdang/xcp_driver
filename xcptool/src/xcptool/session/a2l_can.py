"""Áp cấu hình CAN đọc từ A2L (`XcpCanInfo`) lên `BusConfig`.

Hàm thuần: không đọc file, không mở bus — để dialog hiển thị trước và
`connect()` áp thật cùng một kết quả.
"""

from __future__ import annotations

from dataclasses import replace

from ..a2l.types import XcpCanInfo
from .api import BusConfig

__all__ = ["apply_a2l_can"]


def apply_a2l_can(cfg: BusConfig, info: XcpCanInfo) -> tuple[BusConfig, list[str]]:
    """Trả về `(cfg_hiệu_lực, ghi_chú)`.

    A2L thắng ở: CRO/DTO ID, 11/29-bit, bitrate, sample point, FD, data bitrate,
    `pad_dlc` (khi A2L có MAX_DLC_REQUIRED) và `daq_can_ids` (list FIXED). Trường
    A2L không có thì giữ giá trị của `cfg` và ghi một dòng. Không đụng backend,
    channel, f_clock, các thanh ghi timing, `t1_timeout_s`, `use_a2l_can`.

    List VARIABLE không có CAN ID để áp (master phải SET_DAQ_ID, chưa hỗ trợ).
    Timing thủ công (`custom_bit_timing`) thắng bitrate/sample point của A2L.
    """
    notes: list[str] = []
    changes: dict[str, object] = {}

    def take(field: str, value: object | None, label: str) -> None:
        if value is None:
            notes.append(f"{label} không có trong A2L — giữ giá trị nhập tay "
                         f"({getattr(cfg, field)})")
        else:
            changes[field] = value

    take("cro_id", info.master_id, "CAN_ID_MASTER")
    take("dto_id", info.slave_id, "CAN_ID_SLAVE")
    if info.extended is not None:
        changes["extended_id"] = info.extended

    if cfg.custom_bit_timing:
        notes.append("Đang dùng timing thủ công (Advanced Timing) — bitrate/sample point "
                     "của A2L chưa được dùng")
    else:
        take("bitrate", info.baudrate, "BAUDRATE")
        take("sample_point", info.sample_point, "SAMPLE_POINT")

    changes["is_fd"] = info.is_fd
    if info.is_fd:
        take("data_bitrate", info.fd_data_baudrate, "CAN_FD_DATA_TRANSFER_BAUDRATE")
        if info.fd_data_sample_point is not None:
            changes["data_sample_point"] = info.fd_data_sample_point
    if info.max_dlc_required:
        changes["pad_dlc"] = True

    fixed = tuple((e.daq_list, e.can_id) for e in info.daq_list_ids
                  if e.fixed and e.can_id is not None)
    changes["daq_can_ids"] = fixed
    for e in info.daq_list_ids:
        if not e.fixed:
            notes.append(f"list {e.daq_list}: VARIABLE — cần SET_DAQ_ID (chưa hỗ trợ)")

    notes.extend(info.notes)
    return replace(cfg, **changes), notes
