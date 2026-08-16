"""Giá trị mặc định của tham số dòng lệnh.

Đây là một trong ba file mà `tests/test_boundaries.py` cho phép nhắc tới CAN ID
cụ thể — vì nó là *mặc định tiện tay cho user*, không phải giả định của logic.
Ở đây chúng lấy thẳng từ `BusConfig` để không có nơi thứ hai phải sửa khi giá
trị mặc định của contract đổi.
"""

from __future__ import annotations

from ..session.api import BusConfig

__all__ = ["DEFAULT_BUS"]

DEFAULT_BUS = BusConfig(backend="", channel="")
