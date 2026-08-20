"""Fixture dùng chung cho test backend.

Bus `virtual` của python-can nối các bus cùng `channel` trong cùng tiến trình,
nên mỗi test phải có channel riêng — nếu không hai test chạy nối tiếp sẽ nghe
thấy frame thừa của nhau và hỏng theo kiểu rất khó tìm.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig
from xcptool.session.real import RealSession

_counter = itertools.count()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch) -> None:
    """RealSession lưu lựa chọn vào thư mục hiện tại sau mỗi lần connect thành công.
    Test không được đụng vào thư mục thật của user."""
    monkeypatch.setenv("XCPTOOL_HOME", str(tmp_path / "xcptool-home"))


@pytest.fixture
def channel() -> str:
    return f"xcptest-{next(_counter)}"


@pytest.fixture
def slave_cfg(channel: str) -> SlaveConfig:
    return SlaveConfig(channel=channel)


@pytest.fixture
def slave(slave_cfg: SlaveConfig) -> Iterator[FakeSlave]:
    with FakeSlave(slave_cfg) as s:
        yield s


@pytest.fixture
def bus_cfg(slave_cfg: SlaveConfig) -> BusConfig:
    """Cấu hình master khớp với ECU giả — CAN ID lấy từ cấu hình, không hardcode."""
    return BusConfig(
        backend="virtual",
        channel=slave_cfg.channel,
        cro_id=slave_cfg.cro_id,
        dto_id=slave_cfg.dto_id,
        pad_dlc=slave_cfg.pad_dlc,
        t1_timeout_s=0.5,
    )


@pytest.fixture
def session() -> Iterator[RealSession]:
    s = RealSession()
    try:
        yield s
    finally:
        s.close()
