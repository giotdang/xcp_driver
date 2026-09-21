"""Unit tests for Session.export_dataset/import_dataset — RealSession and
FakeSession both wrap a2l/dataset.py identically; neither needs a live connection."""
from __future__ import annotations

import pytest

from xcptool.a2l.dataset import SkipReason
from xcptool.session.api import XcpToolError
from xcptool.session.fake import FakeSession
from xcptool.session.real import RealSession


@pytest.fixture(params=[RealSession, FakeSession])
def session(request):
    return request.param()


def test_export_dataset_without_a2l_raises(session) -> None:
    with pytest.raises(XcpToolError):
        session.export_dataset({"x": "1"})


def test_export_then_import_roundtrip(session, tmp_path) -> None:
    a2l_path = tmp_path / "project.a2l"
    # Field order/shape confirmed against examples/xcp_daq_example.a2l:348-357
    # (name, description, char_type, address, record_layout, max_diff,
    # compu_method, lower_limit, upper_limit).
    a2l_path.write_text(
        "/begin RECORD_LAYOUT RL_F32\n"
        "  FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT\n"
        "/end RECORD_LAYOUT\n"
        "/begin CHARACTERISTIC speedPid_kp\n"
        '  "PID gain"\n'
        "  VALUE\n"
        "  0x1000\n"
        "  RL_F32\n"
        "  0\n"
        "  NO_COMPU_METHOD\n"
        "  0.0\n"
        "  10.0\n"
        "/end CHARACTERISTIC\n",
        encoding="utf-8",
    )
    session.load_a2l(a2l_path)

    payload = session.export_dataset({"speedPid_kp": "1.25"})
    assert payload["values"] == {"speedPid_kp": "1.25"}
    assert payload["a2l_filename"] == "project.a2l"

    result = session.import_dataset(payload)
    assert result.matched == {"speedPid_kp": "1.25"}
    assert result.skipped == []
    assert result.a2l_mismatch_warning is None


def test_import_dataset_invalid_payload_raises(session) -> None:
    with pytest.raises(XcpToolError):
        session.import_dataset({"not": "a valid dataset"})


def test_import_dataset_unknown_name_skipped(session, tmp_path) -> None:
    a2l_path = tmp_path / "empty.a2l"
    a2l_path.write_text("", encoding="utf-8")
    session.load_a2l(a2l_path)

    result = session.import_dataset({"format_version": 1, "values": {"ghost": "1"}})
    assert result.matched == {}
    assert result.skipped == [SkipReason(name="ghost", reason="not found in A2L")]
