"""Giải bộ số bit-timing từ (bitrate mong muốn, sample point) — bọc python-can.

`can.BitTiming.from_sample_point` / `can.BitTimingFd.from_sample_point` làm toàn
bộ việc tìm brp/tseg. Module này chỉ:

  * rẽ nhánh classic / CAN FD,
  * dịch `ValueError` tiếng Anh của python-can sang `BitTimingError` có
    `user_message` để dialog hiện một dòng đọc được thay vì traceback.

Đặt ở `session/` chứ không phải `transport/` vì `test_boundaries.py` cấm `ui/`
import thẳng `xcptool.transport` — frontend chỉ được với tới tầng dưới qua
`session/`. Đây là điểm duy nhất trong `session/` (ngoài `real.py`) chạm python-can.

python-can bảo đảm bitrate **khớp chính xác hoặc ném lỗi**; sample point thì lấy
gần yêu cầu nhất — nên `TimingSolution` trả về giá trị *thực đạt* để UI cảnh báo
khi lệch.
"""

from __future__ import annotations

from dataclasses import dataclass

import can

from .api import TransportError

__all__ = ["Segments", "TimingSolution", "BitTimingError", "solve"]


class BitTimingError(TransportError):
    """Không có bộ số hợp lệ cho bitrate/clock đang chọn."""


@dataclass(frozen=True)
class Segments:
    brp: int
    tseg1: int
    tseg2: int
    sjw: int


@dataclass(frozen=True)
class TimingSolution:
    nominal: Segments
    data: Segments | None
    nom_bitrate: int                 # bitrate thực đạt (== yêu cầu, python-can bảo đảm)
    nom_sample_point: float          # sample point thực đạt, % — có thể lệch nhẹ
    data_bitrate: int | None
    data_sample_point: float | None


def solve(
    f_clock: int,
    nom_bitrate: int,
    nom_sample_point: float,
    *,
    data_bitrate: int | None = None,
    data_sample_point: float | None = None,
) -> TimingSolution:
    """Bộ số tối ưu cho sample point yêu cầu.

    `data_bitrate` khác None → giải luôn data phase (CAN FD), cần cả
    `data_sample_point`. Ném `BitTimingError` khi không tìm được bộ số cho
    bitrate ở clock này.
    """
    try:
        if data_bitrate is None:
            bt = can.BitTiming.from_sample_point(f_clock, nom_bitrate, nom_sample_point)
            return TimingSolution(
                nominal=Segments(bt.brp, bt.tseg1, bt.tseg2, bt.sjw),
                data=None,
                nom_bitrate=bt.bitrate,
                nom_sample_point=bt.sample_point,
                data_bitrate=None,
                data_sample_point=None,
            )
        if data_sample_point is None:
            raise BitTimingError("Thiếu data sample point cho CAN FD.")
        bt = can.BitTimingFd.from_sample_point(
            f_clock, nom_bitrate, nom_sample_point, data_bitrate, data_sample_point
        )
        return TimingSolution(
            nominal=Segments(bt.nom_brp, bt.nom_tseg1, bt.nom_tseg2, bt.nom_sjw),
            data=Segments(bt.data_brp, bt.data_tseg1, bt.data_tseg2, bt.data_sjw),
            nom_bitrate=bt.nom_bitrate,
            nom_sample_point=bt.nom_sample_point,
            data_bitrate=bt.data_bitrate,
            data_sample_point=bt.data_sample_point,
        )
    except ValueError as exc:
        which = "data " if data_bitrate is not None else ""
        raise BitTimingError(
            f"Không tìm được bộ số cho {which}bitrate "
            f"{data_bitrate or nom_bitrate} bps ở clock {f_clock / 1_000_000:g} MHz. "
            f"Thử clock hoặc bitrate khác. ({exc})"
        ) from exc
