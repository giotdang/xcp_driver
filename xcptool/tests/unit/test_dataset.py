"""Unit tests for a2l/dataset.py — pure, no Qt, no filesystem beyond a2l_path."""
from __future__ import annotations

import json

import pytest

from xcptool.a2l.dataset import DatasetImportResult, FORMAT_VERSION, SkipReason, apply_dataset, build_dataset
from xcptool.a2l.types import A2LDatabase, Characteristic, RecordLayout


def test_build_dataset_shape(tmp_path) -> None:
    a2l_path = tmp_path / "project.a2l"
    a2l_path.write_bytes(b"/* fake a2l content */")
    db = A2LDatabase()
    payload = build_dataset({"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}, db, a2l_path)

    assert payload["format_version"] == FORMAT_VERSION
    assert payload["a2l_filename"] == "project.a2l"
    assert payload["a2l_checksum"].startswith("sha256:")
    assert payload["values"] == {"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}
    # must be JSON-serializable as-is
    json.dumps(payload)


def test_build_dataset_checksum_changes_with_file_content(tmp_path) -> None:
    p1 = tmp_path / "a.a2l"
    p1.write_bytes(b"AAAA")
    p2 = tmp_path / "b.a2l"
    p2.write_bytes(b"BBBB")
    db = A2LDatabase()
    c1 = build_dataset({}, db, p1)["a2l_checksum"]
    c2 = build_dataset({}, db, p2)["a2l_checksum"]
    assert c1 != c2


def _db_with_chars() -> A2LDatabase:
    db = A2LDatabase()
    db.record_layouts["RL_F32"] = RecordLayout(name="RL_F32", datatype="FLOAT32_IEEE")
    db.characteristics["speedPid_kp"] = Characteristic(
        name="speedPid_kp", description="", char_type="VALUE", address=0x1000,
        record_layout="RL_F32", lower_limit=0.0, upper_limit=10.0,
        datatype="FLOAT32_IEEE", array_size=1,
    )
    db.characteristics["torqueTable"] = Characteristic(
        name="torqueTable", description="", char_type="VAL_BLK", address=0x2000,
        record_layout="RL_F32", lower_limit=0.0, upper_limit=100.0,
        datatype="FLOAT32_IEEE", array_size=4,
    )
    return db


def test_apply_dataset_matches_known_names() -> None:
    db = _db_with_chars()
    payload = {"format_version": 1, "values": {"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}}
    result = apply_dataset(payload, db)
    assert result.matched == {"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}
    assert result.skipped == []
    assert result.a2l_mismatch_warning is None


def test_apply_dataset_skips_unknown_name() -> None:
    db = _db_with_chars()
    payload = {"format_version": 1, "values": {"doesNotExist": "1"}}
    result = apply_dataset(payload, db)
    assert result.matched == {}
    assert result.skipped == [SkipReason(name="doesNotExist", reason="not found in A2L")]


def test_apply_dataset_skips_array_size_mismatch() -> None:
    db = _db_with_chars()
    # torqueTable is array_size=4 — 2 values is neither 1 (broadcast) nor 4
    payload = {"format_version": 1, "values": {"torqueTable": "10, 20"}}
    result = apply_dataset(payload, db)
    assert result.matched == {}
    assert result.skipped == [SkipReason(name="torqueTable", reason="datatype/size mismatch")]


def test_apply_dataset_single_value_broadcasts_to_array_ok() -> None:
    db = _db_with_chars()
    payload = {"format_version": 1, "values": {"torqueTable": "5"}}
    result = apply_dataset(payload, db)
    assert result.matched == {"torqueTable": "5"}
    assert result.skipped == []


def test_apply_dataset_missing_format_version_raises() -> None:
    db = _db_with_chars()
    with pytest.raises(ValueError):
        apply_dataset({"values": {}}, db)


def test_apply_dataset_missing_values_raises() -> None:
    db = _db_with_chars()
    with pytest.raises(ValueError):
        apply_dataset({"format_version": 1}, db)


def test_apply_dataset_unknown_format_version_raises() -> None:
    db = _db_with_chars()
    with pytest.raises(ValueError):
        apply_dataset({"format_version": 2, "values": {}}, db)


def test_apply_dataset_checksum_match_no_warning(tmp_path) -> None:
    db = _db_with_chars()
    a2l_path = tmp_path / "p.a2l"
    a2l_path.write_bytes(b"content")
    payload = build_dataset({"speedPid_kp": "1.0"}, db, a2l_path)
    result = apply_dataset(payload, db, a2l_path)
    assert result.a2l_mismatch_warning is None
    assert result.matched == {"speedPid_kp": "1.0"}


def test_apply_dataset_checksum_mismatch_warns_but_still_matches(tmp_path) -> None:
    db = _db_with_chars()
    old_path = tmp_path / "old.a2l"
    old_path.write_bytes(b"old content")
    payload = build_dataset({"speedPid_kp": "1.0"}, db, old_path)

    new_path = tmp_path / "new.a2l"
    new_path.write_bytes(b"different content")
    result = apply_dataset(payload, db, new_path)
    assert result.a2l_mismatch_warning is not None
    assert result.matched == {"speedPid_kp": "1.0"}  # still applied, just warned


def test_apply_dataset_float64_precision_roundtrip() -> None:
    """A value that %.6g would corrupt must survive build+apply unchanged —
    dataset.py never re-formats already-formatted text."""
    db = A2LDatabase()
    db.record_layouts["RL_F64"] = RecordLayout(name="RL_F64", datatype="FLOAT64_IEEE")
    db.characteristics["preciseGain"] = Characteristic(
        name="preciseGain", description="", char_type="VALUE", address=0x3000,
        record_layout="RL_F64", lower_limit=0.0, upper_limit=10.0,
        datatype="FLOAT64_IEEE", array_size=1,
    )
    precise_text = "1.234567890123456"
    result = apply_dataset({"format_version": 1, "values": {"preciseGain": precise_text}}, db)
    assert result.matched["preciseGain"] == precise_text
