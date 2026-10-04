"""`XCP_ON_CAN` trong A2L → `XcpCanInfo`.

Cú pháp theo AML XCP on CAN v1.0 (pyxcp/pyA2L): `DAQ_LIST_CAN_ID` là block CON,
`VARIABLE` không kèm ID, `FIXED <id>`; ID có bit 31 = 1 là 29-bit. Block CAN FD
(XCP >= 1.2) chưa đối chiếu được với A2L thật — các test FD ghi rõ là giả định A3.
"""

from __future__ import annotations

from pathlib import Path

from xcptool.a2l import load
from xcptool.a2l.parser import parse
from xcptool.a2l.types import DaqListCanId

EXAMPLE = Path(__file__).parents[3] / "examples" / "xcp_daq_example.a2l"


def _a2l(if_data_body: str) -> str:
    return f"""
/begin PROJECT p ""
  /begin MODULE m ""
    /begin IF_DATA XCP
{if_data_body}
    /end IF_DATA
  /end MODULE
/end PROJECT
"""


def _can(body: str) -> str:
    return f"/begin XCP_ON_CAN\n{body}\n/end XCP_ON_CAN"


def test_xcp_daq_example_a2l() -> None:
    info = load(EXAMPLE).can_info

    assert info is not None
    assert (info.master_id, info.slave_id) == (0x7E0, 0x7E1)
    assert info.baudrate == 500000
    assert info.sample_point == 75
    assert info.extended is False
    assert info.max_dlc_required is True
    assert info.is_fd is False
    assert info.daq_list_ids == ()


def test_ba_daq_list_can_id_fixed() -> None:
    """Mẫu của pyxcp (`ifdata_CAN.a2l`): list 0/1/2 → 0x310/0x320/0x330."""
    body = "\n".join(f"""
/begin DAQ_LIST_CAN_ID
    {n} /* for DAQ_LIST {n} */
    FIXED {cid}
/end DAQ_LIST_CAN_ID""" for n, cid in ((0, "0x310"), (1, "0x320"), (2, "0x330")))
    info = parse(_a2l(_can("""
0x0100
CAN_ID_BROADCAST 0x0100
CAN_ID_MASTER 0x0200
CAN_ID_MASTER_INCREMENTAL
CAN_ID_SLAVE 0x0300
BAUDRATE 500000
""" + body))).can_info

    assert info is not None
    assert info.daq_list_ids == (
        DaqListCanId(0, True, 0x310), DaqListCanId(1, True, 0x320),
        DaqListCanId(2, True, 0x330))
    assert any("CAN_ID_MASTER_INCREMENTAL" in n for n in info.notes)


def test_variable_khong_co_can_id() -> None:
    info = parse(_a2l(_can("""
0x0100
CAN_ID_MASTER 0x6A0
CAN_ID_SLAVE 0x6A1
/begin DAQ_LIST_CAN_ID 1 VARIABLE /end DAQ_LIST_CAN_ID
"""))).can_info

    assert info is not None
    assert info.daq_list_ids == (DaqListCanId(1, False, None),)


def test_id_29_bit_bit31() -> None:
    info = parse(_a2l(_can("""
0x0100
CAN_ID_MASTER 0x80000123
CAN_ID_SLAVE 0x80000124
"""))).can_info

    assert info is not None
    assert (info.master_id, info.slave_id) == (0x123, 0x124)
    assert info.extended is True


def test_thieu_truong_thi_none() -> None:
    info = parse(_a2l(_can("0x0100\nCAN_ID_MASTER 0x6A0\nCAN_ID_SLAVE 0x6A1"))).can_info

    assert info is not None
    assert info.baudrate is None
    assert info.sample_point is None
    assert info.is_fd is False
    assert info.fd_data_baudrate is None


def test_khoi_can_fd_long_trong_xcp_on_can_gia_dinh_A3() -> None:
    info = parse(_a2l(_can("""
0x0100
CAN_ID_MASTER 0x6A0
CAN_ID_SLAVE 0x6A1
BAUDRATE 500000
/begin CAN_FD
  MAX_DLC 64
  CAN_FD_DATA_TRANSFER_BAUDRATE 2000000
  SAMPLE_POINT 70
/end CAN_FD
"""))).can_info

    assert info is not None
    assert info.is_fd is True
    assert info.fd_data_baudrate == 2_000_000
    assert info.fd_data_sample_point == 70


def test_khoi_xcp_on_can_fd_la_anh_em_cua_xcp_on_can_gia_dinh_A3() -> None:
    """Tên block mà parser hiện tại (XcpProtocolInfo) đã nhận: `XCP_ON_CAN_FD`."""
    info = parse(_a2l("""
/begin XCP_ON_CAN_FD
  0x0100
  CAN_ID_MASTER 0x6A0
  CAN_ID_SLAVE 0x6A1
  BAUDRATE 500000
  CAN_FD_DATA_TRANSFER_BAUDRATE 4000000
/end XCP_ON_CAN_FD
""")).can_info

    assert info is not None
    assert info.is_fd is True
    assert (info.master_id, info.slave_id) == (0x6A0, 0x6A1)
    assert info.fd_data_baudrate == 4_000_000


def test_khong_co_xcp_on_can_thi_can_info_none() -> None:
    assert parse(_a2l("/begin PROTOCOL_LAYER 0x0100 /end PROTOCOL_LAYER")).can_info is None


def test_block_hong_khong_nem() -> None:
    info = parse(_a2l(_can("0x0100\nCAN_ID_MASTER\nBAUDRATE abc\nCAN_ID_SLAVE 0x6A1"))).can_info

    assert info is not None
    assert info.master_id is None
    assert info.baudrate is None
    assert info.slave_id == 0x6A1
