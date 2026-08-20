"""F2 — cửa sổ debug CAN dưới tải.

Cổng của mốc này: 2000 frame/s → UI vẫn mượt, RAM không tăng đơn điệu, số đếm
khớp `dropped_frames`. Bài 60 giây chạy tay bằng `tests/ui/soak_trace.py`; bản
tự động ở đây rút ngắn còn vài giây để nằm trong `timeout = 60` của pytest.
"""

from __future__ import annotations

import time
import tracemalloc

from xcptool.session.api import TraceEntry
from xcptool.session.fake import FakeSession
from xcptool.ui.main_window import MainWindow
from xcptool.ui.trace_view import TraceModel, TraceView

RATE = 2000


def _entry(seq: int, kind: str = "daq", can_id: int = 0x7E1) -> TraceEntry:
    return TraceEntry(
        seq=seq, t_mono=seq * 0.001, direction="rx", can_id=can_id,
        data=bytes([seq & 0xFF]) * 8, kind=kind, decoded=f"DAQ {seq}",
    )


# ── model ────────────────────────────────────────────────────────────────────

def test_model_giu_dung_tran(qtbot) -> None:
    m = TraceModel(capacity=100)
    m.append([_entry(i) for i in range(1000)])
    assert m.rowCount() == 100, "quá trần phải bỏ dòng CŨ nhất, không phình RAM"
    assert m.total_held == 100


def test_model_bo_dong_cu_nhat_chu_khong_phai_moi_nhat(qtbot) -> None:
    m = TraceModel(capacity=10)
    m.append([_entry(i) for i in range(20)])
    seqs = [e.seq for e in m.visible_entries()]
    assert seqs == list(range(10, 20))


def test_loc_theo_kind(qtbot) -> None:
    m = TraceModel(capacity=100)
    m.append([_entry(1, "cmd"), _entry(2, "res"), _entry(3, "daq"), _entry(4, "err")])
    assert m.rowCount() == 4
    m.set_kinds({"err"})
    assert m.rowCount() == 1
    assert m.visible_entries()[0].kind == "err"
    m.set_kinds({"cmd", "res", "err", "ev", "serv", "daq", "other"})
    assert m.rowCount() == 4, "bỏ lọc phải hiện lại đủ, không mất dữ liệu đã giữ"


def test_loc_van_dung_sau_khi_them_va_bo_dong(qtbot) -> None:
    m = TraceModel(capacity=10)
    m.set_kinds({"err"})
    m.append([_entry(i, "err" if i % 2 else "daq") for i in range(20)])
    assert all(e.kind == "err" for e in m.visible_entries())
    assert m.rowCount() <= 10


def test_du_lieu_hien_thi_dung_dinh_dang(qtbot) -> None:
    from PySide6.QtCore import Qt

    m = TraceModel()
    m.append([_entry(7, "cmd", can_id=0x7E0)])
    row = [m.data(m.index(0, c), Qt.DisplayRole) for c in range(7)]
    assert row[0] == 7
    assert row[2] == "←"
    assert row[3] == "0x7E0"
    assert row[4] == 8
    assert row[5].startswith("07 07")
    assert "DAQ 7" in row[6]


# ── view ─────────────────────────────────────────────────────────────────────

def test_tam_dung_ngung_cap_nhat_bang(qtbot) -> None:
    v = TraceView()
    qtbot.addWidget(v)
    v.feed([_entry(1)], dropped=0)
    assert v.model.rowCount() == 1

    v.pause_btn.setChecked(True)
    v.feed([_entry(i) for i in range(2, 100)], dropped=0)
    assert v.model.rowCount() == 1, "tạm dừng thì bảng không được đổi"
    assert "Paused 98" in v.counter_label.text()

    v.pause_btn.setChecked(False)
    v.feed([_entry(200)], dropped=0)
    assert v.model.rowCount() == 2


def test_xoa_dua_ve_rong(qtbot) -> None:
    v = TraceView()
    qtbot.addWidget(v)
    v.feed([_entry(i) for i in range(50)], dropped=0)
    v.clear()
    assert v.model.rowCount() == 0
    assert "Rx 0" in v.counter_label.text()


def test_bo_dem_hien_dung_so_dropped_cua_session(qtbot) -> None:
    v = TraceView()
    qtbot.addWidget(v)
    v.feed([_entry(1)], dropped=137)
    assert "Dropped 137" in v.counter_label.text()


def test_xuat_csv(qtbot, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    v = TraceView()
    qtbot.addWidget(v)
    v.feed([_entry(1, "cmd"), _entry(2, "res")], dropped=0)

    out = tmp_path / "trace.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    v._on_export()

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("seq,")
    assert len(lines) == 3


def test_ghi_ro_chat_luong_timestamp_khac_nhau_theo_thiet_bi(qtbot) -> None:
    v = TraceView()
    qtbot.addWidget(v)
    note = v.note_label.text()
    assert "timestamp" in note.lower()
    assert "hardware" in note.lower() and "software" in note.lower()


# ── dưới tải thật ────────────────────────────────────────────────────────────

def test_flood_2000_fps_ui_van_muot_ram_khong_phinh(qtbot, cfg) -> None:
    seconds = 5.0
    session = FakeSession()
    window = MainWindow(session)
    qtbot.addWidget(window)
    window.connect_to(cfg)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)
    window.trace_view.cap_spin.setValue(5000)

    tracemalloc.start()
    session.start_flood(rate_hz=RATE)
    try:
        qtbot.wait(2000)
        early, _ = tracemalloc.get_traced_memory()
        early_rows = window.trace_view.model.total_held
        qtbot.wait(int(seconds * 1000))
        late, _ = tracemalloc.get_traced_memory()
    finally:
        session.stop_flood()
        tracemalloc.stop()

    v = window.trace_view
    assert v.model.total_held <= 5000, "ring buffer của bảng phải chạm trần rồi dừng"
    assert early_rows > 0, "phải có frame chảy vào bảng"
    assert v._received > RATE * seconds * 0.5, (
        f"chỉ rút được {v._received} frame — timer trace không theo kịp"
    )
    growth = (late - early) / max(early, 1)
    assert growth < 0.5, f"RAM tăng {growth:.0%} sau khi đã chạm trần — nghi rò rỉ"
    assert f"Dropped {session.dropped_frames}" in v.counter_label.text()
    window.close()


def test_khong_ve_theo_tung_frame(qtbot, cfg) -> None:
    """Bảng chỉ được cập nhật theo timer, không phải mỗi lần có frame mới."""
    session = FakeSession()
    window = MainWindow(session)
    qtbot.addWidget(window)

    repaints: list[float] = []
    original = window.trace_view.feed

    def counting_feed(entries, dropped):
        if entries:
            repaints.append(time.monotonic())
        original(entries, dropped)

    window.trace_view.feed = counting_feed
    window.connect_to(cfg)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)
    session.start_flood(rate_hz=RATE)
    qtbot.wait(1000)
    session.stop_flood()

    assert repaints, "phải có ít nhất một lần gom"
    assert len(repaints) < RATE / 4, (
        f"{len(repaints)} lần vẽ trong 1 giây — đang vẽ theo từng frame thay vì theo timer"
    )
    window.close()
