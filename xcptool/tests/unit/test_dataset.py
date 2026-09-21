"""Unit tests for a2l/dataset.py — pure, no Qt, no filesystem beyond a2l_path."""
from __future__ import annotations

import json

from xcptool.a2l.dataset import FORMAT_VERSION, build_dataset
from xcptool.a2l.types import A2LDatabase


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
