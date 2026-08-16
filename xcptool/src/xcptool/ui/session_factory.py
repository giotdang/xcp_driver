"""Chọn hiện thực Session lúc chạy. Không import Qt — CLI dùng lại được."""

from __future__ import annotations

from typing import Any

__all__ = ["SESSION_KINDS", "create_session"]

SESSION_KINDS = ("fake", "real")


def create_session(kind: str) -> Any:
    """`kind` = 'fake' (FakeSession, không cần phần cứng) | 'real' (RealSession)."""
    if kind == "fake":
        from ..session.fake import FakeSession

        return FakeSession()
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
