"""Ngoại lệ → thông báo người đọc được.

Không bao giờ hiện traceback hay mã lỗi thô cho user. `XcpToolError` đã mang sẵn
`user_message`; phần thêm ở đây là *gợi ý phải làm gì tiếp theo*.
"""

from __future__ import annotations

import logging
import traceback

from PySide6.QtWidgets import QWidget
from qfluentwidgets import MessageBox

from ..session.api import (
    BusError,
    BusyError,
    DeviceNotFoundError,
    DriverMissingError,
    MalformedResponseError,
    NotConnectedError,
    SlaveError,
    UnsupportedByEcuError,
    WriteProtectedError,
    XcpTimeoutError,
    XcpToolError,
)

log = logging.getLogger(__name__)

__all__ = ["describe", "show_error", "show_unexpected"]


def describe(exc: BaseException) -> tuple[str, str]:
    """(tiêu đề, nội dung) — cả hai đều là câu tiếng Việt cho user đọc."""
    if isinstance(exc, DriverMissingError):
        return (
            "Thiếu driver của hãng",
            f"{exc.user_message}\n\n"
            f"Cài gói sau rồi bấm Dò lại: {exc.package_hint}",
        )
    if isinstance(exc, DeviceNotFoundError):
        return (
            "Không tìm thấy thiết bị",
            f"{exc.user_message}\n\n"
            "Kiểm tra dây USB và cổng cắm, sau đó dò lại danh sách thiết bị.",
        )
    if isinstance(exc, BusError):
        return (
            "Lỗi bus CAN",
            f"{exc.user_message}\n\n"
            "Kiểm tra bitrate, điện trở đầu cuối 120Ω và xem ECU có đang cấp nguồn không.",
        )
    if isinstance(exc, XcpTimeoutError):
        return (
            "ECU không trả lời",
            f"{exc.user_message}\n\n"
            "Kiểm tra CAN ID của CRO/DTO và bitrate — đây là hai thứ hay đặt sai nhất.",
        )
    if isinstance(exc, MalformedResponseError):
        return (
            "Response không hợp lệ",
            f"{exc.user_message}\n\n"
            "Xem cửa sổ debug CAN để đối chiếu byte thô mà ECU gửi về.",
        )
    if isinstance(exc, WriteProtectedError):
        return (
            "Vùng nhớ đang được bảo vệ ghi",
            f"{exc.user_message}\n\n"
            "Thường là do XCP đang trỏ vào reference page (ROM). "
            "Chuyển XCP về working page (RAM) rồi ghi lại.",
        )
    if isinstance(exc, SlaveError):
        return (
            f"ECU từ chối lệnh — {exc.name}",
            f"{exc.description}\n\nMã lỗi thô: 0x{exc.code:02X}",
        )
    if isinstance(exc, NotConnectedError):
        return ("Chưa kết nối", f"{exc.user_message}\n\nBấm Kết nối trước đã.")
    if isinstance(exc, BusyError):
        return (
            "Bus đang bận",
            f"{exc.user_message}\n\n"
            "Mỗi lúc chỉ chạy được một lệnh XCP. Chờ lệnh hiện tại xong rồi thử lại.",
        )
    if isinstance(exc, UnsupportedByEcuError):
        return ("ECU không hỗ trợ", exc.user_message)
    if isinstance(exc, XcpToolError):
        return ("Lỗi", exc.user_message)
    return (
        "Lỗi ngoài dự kiến",
        f"{type(exc).__name__}: {exc}\n\n"
        "Đây là lỗi của công cụ, không phải của bạn. Chi tiết đã ghi vào file log.",
    )


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    """Hộp thoại một nút. Luôn ghi log trước khi hiện."""
    title, body = describe(exc)
    if isinstance(exc, XcpToolError):
        log.warning("%s: %s", title, exc)
    else:
        log.error("%s\n%s", title, "".join(traceback.format_exception(exc)))
    box = MessageBox(title, body, parent)
    box.cancelButton.hide()
    box.buttonLayout.insertStretch(1)
    box.yesButton.setText("Đã hiểu")
    box.exec()


def show_unexpected(parent: QWidget | None, exc: BaseException, log_path: str) -> None:
    """Dành cho excepthook: xin lỗi, chỉ chỗ xem log, KHÔNG hiện traceback."""
    box = MessageBox(
        "Công cụ gặp lỗi ngoài dự kiến",
        f"{type(exc).__name__}: {exc}\n\n"
        f"Công cụ vẫn đang chạy. Toàn bộ chi tiết đã ghi vào:\n{log_path}",
        parent,
    )
    box.cancelButton.hide()
    box.buttonLayout.insertStretch(1)
    box.yesButton.setText("Đóng")
    box.exec()
