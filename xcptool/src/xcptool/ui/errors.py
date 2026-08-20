"""Exception → human-readable message mapping.

Never show tracebacks or raw error codes to the user. `XcpToolError` already
carries a `user_message`; this module adds actionable hints about what to do next.
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
    """(title, body) — both are English sentences intended for the end user."""
    if isinstance(exc, DriverMissingError):
        return (
            "Interface driver not found",
            f"{exc.user_message}\n\n"
            f"Install the following package, then click Scan Devices: {exc.package_hint}",
        )
    if isinstance(exc, DeviceNotFoundError):
        return (
            "Interface not found",
            f"{exc.user_message}\n\n"
            "Check the USB cable and port, then scan for devices again.",
        )
    if isinstance(exc, BusError):
        return (
            "CAN bus error",
            f"{exc.user_message}\n\n"
            "Verify the bitrate, 120 Ω termination resistors, and ECU power supply.",
        )
    if isinstance(exc, XcpTimeoutError):
        return (
            "ECU not responding",
            f"{exc.user_message}\n\n"
            "Check the CRO/DTO CAN IDs and bitrate — these are the most common "
            "misconfiguration points.",
        )
    if isinstance(exc, MalformedResponseError):
        return (
            "Invalid response",
            f"{exc.user_message}\n\n"
            "Open the CAN Trace window to inspect the raw bytes returned by the ECU.",
        )
    if isinstance(exc, WriteProtectedError):
        return (
            "Memory write protected",
            f"{exc.user_message}\n\n"
            "The XCP tool is likely pointing at the reference page (ROM). "
            "Switch XCP to the working page (RAM) and retry.",
        )
    if isinstance(exc, SlaveError):
        return (
            f"ECU rejected command — {exc.name}",
            f"{exc.description}\n\nRaw error code: 0x{exc.code:02X}",
        )
    if isinstance(exc, NotConnectedError):
        return ("Not connected", f"{exc.user_message}\n\nClick Connect first.")
    if isinstance(exc, BusyError):
        return (
            "Bus busy",
            f"{exc.user_message}\n\n"
            "Only one XCP command can run at a time. Wait for the current "
            "operation to finish and try again.",
        )
    if isinstance(exc, UnsupportedByEcuError):
        return ("Feature not supported by ECU", exc.user_message)
    if isinstance(exc, XcpToolError):
        return ("Error", exc.user_message)
    return (
        "Unexpected error",
        f"{type(exc).__name__}: {exc}\n\n"
        "This is a tool-level error, not a user mistake. "
        "Details have been written to the log file.",
    )


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    """Single-button error dialog. Always logs before displaying."""
    title, body = describe(exc)
    if isinstance(exc, XcpToolError):
        log.warning("%s: %s", title, exc)
    else:
        log.error("%s\n%s", title, "".join(traceback.format_exception(exc)))
    box = MessageBox(title, body, parent)
    box.cancelButton.hide()
    box.buttonLayout.insertStretch(1)
    box.yesButton.setText("OK")
    box.exec()


def show_unexpected(parent: QWidget | None, exc: BaseException, log_path: str) -> None:
    """For the excepthook: apologize, point to the log, never show a traceback."""
    box = MessageBox(
        "Unexpected tool error",
        f"{type(exc).__name__}: {exc}\n\n"
        f"The tool is still running. Full details have been written to:\n{log_path}",
        parent,
    )
    box.cancelButton.hide()
    box.buttonLayout.insertStretch(1)
    box.yesButton.setText("Close")
    box.exec()
