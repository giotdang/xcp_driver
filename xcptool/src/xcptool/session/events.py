"""Catalog event đo được và các event hợp lệ của từng signal, theo A2L.

Mặt tiền cho `a2l.events`: `ui/` không được import `xcptool.a2l` (test ranh
giới ép luật này), nhưng combobox "Synchronous Event" trong Measurement cần
đúng mấy hàm đó. Toàn bộ logic nằm ở `a2l/events.py` — file này chỉ mở đường
qua tầng session, không thêm hành vi nào.

Tất cả đều là hàm thuần trên `A2LDatabase`, không đụng bus: dialog gọi được
trực tiếp từ UI thread.
"""

from __future__ import annotations

from ..a2l.events import EventOption, allowed_events, event_catalog, event_locked

__all__ = ["EventOption", "allowed_events", "event_catalog", "event_locked"]
