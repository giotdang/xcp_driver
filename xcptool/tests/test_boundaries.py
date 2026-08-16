"""Cưỡng chế ranh giới kiến trúc bằng test, không bằng kỷ luật.

╔══════════════════════════════════════════════════════════════════════════════╗
║  FILE NÀY DO LEAD SỞ HỮU. Agent không sửa. Test đỏ = kiến trúc bị vi phạm,   ║
║  sửa code của bạn, đừng sửa test.                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

Quét import bằng AST — không import module thật, nên chạy được cả khi chưa cài
PySide6 hay python-can.

Ba ranh giới được bảo vệ:

  1. `master/` là protocol core thuần: không biết CAN là gì, không biết GUI là gì.
     Đây là thứ làm công cụ dùng lại được cho transport khác (Ethernet, USB).
  2. `ui/` và `cli/` chỉ nói chuyện qua `session.api`. Không được với tay xuống
     tầng dưới — nếu được thì FakeSession vô nghĩa và frontend hết chạy độc lập.
  3. `session/api.py` là contract thuần stdlib.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "xcptool"

# package (đường dẫn tương đối trong src/xcptool) → các module bị cấm import
FORBIDDEN: dict[str, set[str]] = {
    "master": {"can", "PySide6", "xcptool.ui", "xcptool.cli", "xcptool.transport"},
    "transport": {"PySide6", "xcptool.ui", "xcptool.cli", "xcptool.master"},
    "ui": {"can", "xcptool.master", "xcptool.transport", "xcptool.a2l"},
    "cli": {"can", "xcptool.master", "xcptool.transport", "xcptool.a2l"},
}

# file lẻ → các module bị cấm
FORBIDDEN_FILES: dict[str, set[str]] = {
    "session/api.py": {"can", "PySide6", "xcptool.master", "xcptool.transport"},
    "session/fake.py": {"can", "PySide6", "xcptool.master", "xcptool.transport"},
}


def _imports(path: Path) -> set[str]:
    """Mọi module được import trong file, đã quy về tên tuyệt đối."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # gói mà import tương đối được giải theo, dạng ['xcptool', 'ui'].
    # Với cả module thường lẫn __init__.py, đó đều là phần tử cuối bị bỏ đi.
    rel = path.relative_to(SRC.parent).with_suffix("")
    package = list(rel.parts)[:-1]

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                      # import tương đối
                base = package[: len(package) - node.level + 1]
                mod = ".".join([*base, node.module] if node.module else base)
            else:
                mod = node.module or ""
            if mod:
                found.add(mod)
    return found


def _violates(imported: str, forbidden: str) -> bool:
    """'can.interface' vi phạm luật cấm 'can'; 'candy' thì không."""
    return imported == forbidden or imported.startswith(forbidden + ".")


def _files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_package_boundary(package: str) -> None:
    banned = FORBIDDEN[package]
    offences: list[str] = []
    for path in _files(package):
        for imported in _imports(path):
            for bad in banned:
                if _violates(imported, bad):
                    offences.append(f"{path.relative_to(SRC)} import '{imported}'")
    assert not offences, (
        f"'{package}/' không được import {sorted(banned)}.\n"
        + "\n".join(f"  - {o}" for o in offences)
        + "\n\nĐi qua xcptool.session.api thay vì với tay xuống tầng dưới."
    )


@pytest.mark.parametrize("relpath", sorted(FORBIDDEN_FILES))
def test_file_boundary(relpath: str) -> None:
    path = SRC / relpath
    if not path.exists():
        pytest.skip(f"{relpath} chưa được viết")
    banned = FORBIDDEN_FILES[relpath]
    offences = [
        f"import '{imported}'"
        for imported in _imports(path)
        for bad in banned
        if _violates(imported, bad)
    ]
    assert not offences, f"{relpath} không được import {sorted(banned)}: {offences}"


def test_no_hardcoded_ecu_constants() -> None:
    """Đặc tính của một ECU cụ thể chỉ được xuất hiện làm giá trị mặc định
    trong `session/api.py` và module config — không được rải trong logic.

    Hardcode 0x7E0 trong master/ nghĩa là công cụ chỉ chạy với đúng ECU này,
    trái với mục tiêu dùng lại cho nhiều ECU.
    """
    magic = ("0x7E0", "0x7e0", "0x7E1", "0x7e1")
    allowed = {"session/api.py", "transport/config.py", "cli/defaults.py"}

    offences: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in allowed:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if any(m in code for m in magic):
                offences.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offences, (
        "CAN ID phải đến từ BusConfig, không hardcode:\n"
        + "\n".join(f"  - {o}" for o in offences)
    )
