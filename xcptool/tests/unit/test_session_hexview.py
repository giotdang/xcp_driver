"""Session.load_hex_file()/hex_regions()/generate_hex_from_dataset() —
exercised against both RealSession and FakeSession, since neither touches
the bus for this feature (mirrors tests/unit/test_session_dataset.py's
export_dataset/import_dataset tests)."""
from __future__ import annotations

from pathlib import Path

import pytest

from xcptool.session.api import XcpToolError
from xcptool.session.fake import FakeSession
from xcptool.session.real import RealSession

_IHEX = ":080100000102030405060708D3\n:00000001FF\n"


def _write_hex(tmp_path: Path) -> Path:
    p = tmp_path / "image.hex"
    p.write_text(_IHEX, encoding="ascii")
    return p


@pytest.fixture(params=[RealSession, FakeSession])
def session(request):
    return request.param()


def test_hex_regions_before_load_returns_none_for_everything(session) -> None:
    result = session.hex_regions([(0x0100, 4, "p1")])
    assert result == {"p1": None}


def test_load_then_hex_regions_returns_covered_bytes(session, tmp_path) -> None:
    session.load_hex_file(_write_hex(tmp_path))
    result = session.hex_regions([(0x0100, 4, "p1"), (0x9000, 2, "notInFile")])
    assert result == {"p1": b"\x01\x02\x03\x04", "notInFile": None}


def test_load_hex_file_unrecognized_extension_raises_xcptoolerror(session, tmp_path) -> None:
    bad = tmp_path / "image.bin"
    bad.write_text(_IHEX, encoding="ascii")
    with pytest.raises(XcpToolError):
        session.load_hex_file(bad)


def test_load_hex_file_replaces_previous(session, tmp_path) -> None:
    first = _write_hex(tmp_path)
    session.load_hex_file(first)

    # Checksum generated via bincopy itself (see test_hexfile.py's fixture
    # note) rather than hand-computed — same lesson applied preemptively.
    second_content = ":04020000AABBCCDDEC\n:00000001FF\n"
    second = tmp_path / "second.hex"
    second.write_text(second_content, encoding="ascii")
    session.load_hex_file(second)

    result = session.hex_regions([(0x0100, 4, "fromFirst"), (0x0200, 4, "fromSecond")])
    assert result == {"fromFirst": None, "fromSecond": b"\xAA\xBB\xCC\xDD"}
