"""A2L file parser — tokenizer, block-tree builder, and extraction helpers.

Design
------
1. strip_comments(text)   — remove /* ... */ and // ... comments
2. tokenize(text)         — split into tokens; quoted strings kept intact
3. _Block(name, tokens, children)
       name     = block-type keyword (MEASUREMENT, CHARACTERISTIC, …)
       tokens   = all non-block tokens inside the block, INCLUDING the block
                  identifier at [0] for named blocks
       children = nested _Block list
4. parse_tree(text) -> _Block  — virtual ROOT block whose children are the
                                 top-level blocks in the file
5. _extract_*()           — pull fields out of a _Block
6. parse(text) -> A2LDatabase  — public entry point

Token layout (after /begin KEYWORD was consumed, so b.name = "KEYWORD"):

  MEASUREMENT:
    [0] name/identifier
    [1] description  (quoted string)
    [2] datatype
    [3] compu_method_ref
    [4] resolution   (ignored)
    [5] accuracy     (ignored)
    [6] lower_limit
    [7] upper_limit
    keyword ECU_ADDRESS <addr>
    keyword MATRIX_DIM  <n> [<m> …]

  CHARACTERISTIC:
    [0] name/identifier
    [1] description  (quoted string)
    [2] char_type    (VALUE | VAL_BLK | CURVE | MAP)
    [3] address      (hex)
    [4] record_layout_name
    [5] max_diff     (ignored)
    [6] compu_method_ref
    [7] lower_limit
    [8] upper_limit
    keyword NUMBER <n>   (only for VAL_BLK)

  RECORD_LAYOUT:
    [0] name/identifier
    keyword FNC_VALUES <position> <datatype> <index_mode> <addr_type>

  IF_DATA XCP / DAQ  (cấp MODULE — xem examples/xcp_daq_example.a2l:88-122):
    [0] DAQ_CONFIG_TYPE (STATIC | DYNAMIC)
    [1] MAX_DAQ  [2] MAX_EVENT_CHANNEL  [3] MIN_DAQ
    (phần còn lại — OPTIMISATION_TYPE… — không trích ở đây)
    child /begin EVENT → mỗi /begin EVENT lồng bên trong:
      [0] name  [1] short_name  [2] EVENT_CHANNEL_NUMBER  [3] DAQ|STIM|DAQ_STIM
      [4] MAX_DAQ_LIST  [5] TIME_CYCLE  [6] TIME_UNIT  [7] PRIORITY
    child /begin DAQ_LIST (chỉ khi STATIC, MIN_DAQ>0 — KHÔNG có ví dụ thật
    trong repo, xem hedge trong StaticDaqList/types.py):
      [0] DAQ_LIST_NUMBER, keyword MAX_ODT/MAX_ODT_ENTRIES/EVENT_FIXED,
      child /begin PREDEFINED (marker, không tham số)

  MEASUREMENT / IF_DATA XCP / DAQ_EVENT (event của riêng 1 signal — xem
  examples/xcp_daq_example.a2l:150-156):
    /begin DAQ_EVENT /begin FIXED_EVENT_LIST EVENT <n> /end FIXED_EVENT_LIST /end DAQ_EVENT
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .types import (
    A2LDatabase, Characteristic, CharacteristicTypeDef, EventChannel, Instance,
    Measurement, MeasurementTypeDef, RecordLayout, StaticDaqList, StructComponent,
    StructTypeDef, XcpDaqInfo, XcpProtocolInfo,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal block tree
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    """One A2L /begin…/end block."""
    name: str                          # block-type keyword
    tokens: list[str]                  # flat non-block token list (identifier at [0])
    children: list[_Block] = field(default_factory=list)

    def get(self, keyword: str, n: int) -> list[str] | None:
        """Return the *n* tokens after the first occurrence of *keyword*, or None."""
        for i, tok in enumerate(self.tokens):
            if tok == keyword:
                result = self.tokens[i + 1: i + 1 + n]
                if len(result) == n:
                    return result
        return None


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_RE_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
_RE_LINE_COMMENT  = re.compile(r'//[^\n]*')
_RE_TOKEN         = re.compile(r'"[^"]*"|\S+')


def strip_comments(text: str) -> str:
    """Remove /* … */ (multiline) and // … (line) comments."""
    text = _RE_BLOCK_COMMENT.sub(' ', text)   # space prevents token merging
    text = _RE_LINE_COMMENT.sub('', text)
    return text


def tokenize(text: str) -> list[str]:
    """Split cleaned A2L text into tokens; quoted strings are a single token."""
    return _RE_TOKEN.findall(text)


# ---------------------------------------------------------------------------
# Block-tree builder
# ---------------------------------------------------------------------------

def _parse_block_body(tokens: list[str], pos: int) -> tuple[_Block, int]:
    """Parse one /begin…/end block whose /begin has already been consumed.

    *pos* must point at the block-type token.  Returns (block, next_pos).
    """
    if pos >= len(tokens):
        return _Block("UNKNOWN", []), pos

    block_type = tokens[pos]
    pos += 1

    block_tokens: list[str] = []
    children: list[_Block] = []

    while pos < len(tokens):
        tok = tokens[pos]
        if tok == '/end':
            pos += 1                    # skip /end
            if pos < len(tokens):
                pos += 1               # skip the closing block-type label
            break
        elif tok == '/begin':
            pos += 1                   # skip /begin, recurse
            child, pos = _parse_block_body(tokens, pos)
            children.append(child)
        else:
            block_tokens.append(tok)
            pos += 1

    return _Block(name=block_type, tokens=block_tokens, children=children), pos


def parse_tree(text: str) -> _Block:
    """Parse the full A2L text into a virtual ROOT _Block.

    All top-level /begin…/end blocks become children of ROOT.
    Stray tokens outside any block go into ROOT.tokens.
    """
    tokens = tokenize(strip_comments(text))
    root = _Block(name="ROOT", tokens=[], children=[])
    pos = 0
    while pos < len(tokens):
        tok = tokens[pos]
        if tok == '/begin':
            pos += 1
            child, pos = _parse_block_body(tokens, pos)
            root.children.append(child)
        else:
            root.tokens.append(tok)
            pos += 1
    return root


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def _to_float(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return float(int(s, 0))  # hex / octal fallback


def _to_int(s: str) -> int:
    return int(s, 0)  # handles 0x… and plain decimal


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_matrix_dim(t: list[str]) -> list[int]:
    """MATRIX_DIM <n> [<m> …] — 0 hoặc nhiều số nguyên theo sau keyword."""
    for i, tok in enumerate(t):
        if tok == "MATRIX_DIM":
            dims: list[int] = []
            j = i + 1
            while j < len(t):
                try:
                    dims.append(int(t[j]))
                    j += 1
                except ValueError:
                    break
            return dims
    return []


def _extract_measurement_event_channel(b: _Block) -> int | None:
    """DAQ_EVENT/FIXED_EVENT_LIST/EVENT <n> lồng trong IF_DATA XCP của một
    MEASUREMENT — xem examples/xcp_daq_example.a2l:150-156. Chỉ lấy event
    ĐẦU TIÊN nếu FIXED_EVENT_LIST khai nhiều dòng EVENT — Measurement/
    DaqListConfig hiện chỉ mô hình 1 event/signal (multi-event measurement
    ngoài phạm vi hiện tại)."""
    for child in b.children:
        if child.name != "IF_DATA" or not child.tokens or child.tokens[0] != "XCP":
            continue
        for daq_event in child.children:
            if daq_event.name != "DAQ_EVENT":
                continue
            for fel in daq_event.children:
                if fel.name != "FIXED_EVENT_LIST":
                    continue
                ev = fel.get("EVENT", 1)
                if ev:
                    return _to_int(ev[0])
    return None


def _extract_measurement(b: _Block) -> Measurement | None:
    t = b.tokens
    if len(t) < 8:
        return None

    name         = t[0]
    description  = t[1].strip('"')
    datatype     = t[2]
    compu_method = t[3]
    # t[4] = resolution (ignored), t[5] = accuracy (ignored)
    lower_limit  = _to_float(t[6])
    upper_limit  = _to_float(t[7])

    addr_tok = b.get("ECU_ADDRESS", 1)
    address  = _to_int(addr_tok[0]) if addr_tok else 0

    matrix_dim = _extract_matrix_dim(t)

    return Measurement(
        name=name,
        description=description,
        datatype=datatype,
        address=address,
        lower_limit=lower_limit,
        upper_limit=upper_limit,
        compu_method=compu_method,
        matrix_dim=matrix_dim,
        event_channel=_extract_measurement_event_channel(b),
    )


def _extract_measurement_type(b: _Block) -> MeasurementTypeDef | None:
    t = b.tokens
    if len(t) < 8:
        return None
    return MeasurementTypeDef(
        name=t[0], description=t[1].strip('"'), datatype=t[2],
        compu_method=t[3], lower_limit=_to_float(t[6]), upper_limit=_to_float(t[7]),
        matrix_dim=_extract_matrix_dim(t),
    )


def _extract_instance(b: _Block) -> Instance | None:
    t = b.tokens
    if len(t) < 4:
        return None
    return Instance(
        name=t[0], description=t[1].strip('"'), type_name=t[2],
        address=_to_int(t[3]), matrix_dim=_extract_matrix_dim(t),
    )


def _extract_struct_component(b: _Block) -> StructComponent | None:
    t = b.tokens
    if len(t) < 3:
        return None
    return StructComponent(
        name=t[0], type_name=t[1], offset=_to_int(t[2]),
        matrix_dim=_extract_matrix_dim(t),
    )


def _extract_struct_type(b: _Block) -> StructTypeDef | None:
    t = b.tokens
    if len(t) < 3:
        return None
    components = [
        c for c in (
            _extract_struct_component(child)
            for child in b.children if child.name == "STRUCTURE_COMPONENT"
        ) if c is not None
    ]
    return StructTypeDef(name=t[0], size=_to_int(t[2]), components=components)


def _extract_characteristic(b: _Block) -> Characteristic | None:
    t = b.tokens
    if len(t) < 9:
        return None

    name          = t[0]
    description   = t[1].strip('"')
    char_type     = t[2]
    address       = _to_int(t[3])
    record_layout = t[4]
    # t[5] = max_diff (ignored)
    compu_method  = t[6]
    lower_limit   = _to_float(t[7])
    upper_limit   = _to_float(t[8])

    number_tok = b.get("NUMBER", 1)
    array_size = int(number_tok[0]) if number_tok else 1

    return Characteristic(
        name=name,
        description=description,
        char_type=char_type,
        address=address,
        record_layout=record_layout,
        lower_limit=lower_limit,
        upper_limit=upper_limit,
        compu_method=compu_method,
        array_size=array_size,
    )


def _extract_characteristic_type(b: _Block) -> CharacteristicTypeDef | None:
    t = b.tokens
    if len(t) < 8:
        return None
    number_tok = b.get("NUMBER", 1)
    return CharacteristicTypeDef(
        name=t[0], description=t[1].strip('"'), char_type=t[2],
        record_layout=t[3], compu_method=t[5],
        lower_limit=_to_float(t[6]), upper_limit=_to_float(t[7]),
        array_size=int(number_tok[0]) if number_tok else 1,
    )


def _extract_record_layout(b: _Block) -> RecordLayout | None:
    if not b.tokens:
        return None
    name = b.tokens[0]

    # FNC_VALUES <position> <datatype> <index_mode> <addr_type>
    fnc = b.get("FNC_VALUES", 4)
    if fnc is None:
        return None
    datatype = fnc[1]   # fnc[0]=position, fnc[1]=datatype

    return RecordLayout(name=name, datatype=datatype)


def _extract_xcp_protocol_info(b: _Block) -> XcpProtocolInfo | None:
    """Trích xuất thông số XCP (MAX_CTO, MAX_DTO, CAN FD parameters) từ IF_DATA XCP."""
    info = XcpProtocolInfo()

    for child in b.children:
        if child.name == "PROTOCOL_LAYER":
            # PROTOCOL_LAYER token layout: [0] version, rồi T1..Tn (SỐ LƯỢNG
            # THAY ĐỔI theo ASAP2_VERSION — test_can_fd_payload.py dùng A2L
            # ASAP2_VERSION 1.60 với 5 giá trị T1-T5, còn
            # examples/xcp_daq_example.a2l khai ASAP2_VERSION 1.71 với 7
            # giá trị T1-T7), rồi [MAX_CTO] [MAX_DTO]
            # [BYTE_ORDER_MSB_LAST|BYTE_ORDER_MSB_FIRST] [ADDRESS_GRANULARITY]…
            # Số T không cố định nên neo theo vị trí BYTE_ORDER_* (luôn có,
            # luôn ngay sau MAX_DTO) thay vì index cứng.
            tokens = child.tokens
            byte_order_idx = next(
                (i for i, tok in enumerate(tokens)
                 if tok in ("BYTE_ORDER_MSB_LAST", "BYTE_ORDER_MSB_FIRST")),
                None,
            )
            if byte_order_idx is not None and byte_order_idx >= 2:
                try:
                    info.max_cto = _to_int(tokens[byte_order_idx - 2])
                    info.max_dto = _to_int(tokens[byte_order_idx - 1])
                except (ValueError, IndexError):
                    pass
            for tok in tokens:
                if tok == "BYTE_ORDER_MSB_LAST":
                    info.byte_order = "little"
                elif tok == "BYTE_ORDER_MSB_FIRST":
                    info.byte_order = "big"

        elif child.name == "XCP_ON_CAN_FD":
            info.is_fd = True
            for tok in child.tokens:
                if tok == "CAN_FD_MAX_DLC_REQUIRED":
                    info.max_dlc_required = True
                elif tok.startswith("CAN_FD_MAX_DLC_"):
                    try:
                        info.can_fd_max_dlc = int(tok.replace("CAN_FD_MAX_DLC_", ""))
                    except ValueError:
                        pass

        elif child.name == "XCP_ON_CAN":
            for tok in child.tokens:
                if tok == "MAX_DLC_REQUIRED":
                    info.max_dlc_required = True

    return info


def _extract_event_channel(b: _Block) -> EventChannel | None:
    """Một /begin EVENT ... /end EVENT lồng trong DAQ/EVENT — xem
    examples/xcp_daq_example.a2l:101-110. t[3] (DAQ|STIM|DAQ_STIM) bỏ qua —
    STIM ngoài phạm vi (CLAUDE.md: Disabled Features)."""
    t = b.tokens
    if len(t) < 8:
        return None
    return EventChannel(
        name=t[0].strip('"'),
        short_name=t[1].strip('"'),
        number=_to_int(t[2]),
        max_daq_list=_to_int(t[4]),
        time_cycle=_to_int(t[5]),
        time_unit=_to_int(t[6]),
        priority=_to_int(t[7]),
    )


def _extract_static_daq_list(b: _Block) -> StaticDaqList | None:
    """Một /begin DAQ_LIST ... /end DAQ_LIST — xem hedge đầy đủ ở
    StaticDaqList (types.py): không có ví dụ thật trong repo để đối chiếu
    field order, field nào thiếu thì bỏ qua (None) thay vì đoán bừa."""
    t = b.tokens
    if not t:
        return None

    max_odt_tok = b.get("MAX_ODT", 1)
    max_odt_entries_tok = b.get("MAX_ODT_ENTRIES", 1)
    fixed_event_tok = b.get("EVENT_FIXED", 1)
    predefined = any(c.name == "PREDEFINED" for c in b.children)

    return StaticDaqList(
        number=_to_int(t[0]),
        max_odt=_to_int(max_odt_tok[0]) if max_odt_tok else None,
        max_odt_entries=_to_int(max_odt_entries_tok[0]) if max_odt_entries_tok else None,
        predefined=predefined,
        fixed_event=_to_int(fixed_event_tok[0]) if fixed_event_tok else None,
    )


def _extract_xcp_daq(
    b: _Block,
) -> tuple[XcpDaqInfo | None, dict[int, EventChannel], dict[int, StaticDaqList]]:
    """Trích /begin DAQ ... /end DAQ (cấp MODULE, sibling của PROTOCOL_LAYER
    trong cùng IF_DATA XCP) — DAQ_CONFIG_TYPE/MAX_DAQ/MAX_EVENT_CHANNEL/
    MIN_DAQ, các /begin EVENT lồng bên trong, và /begin DAQ_LIST nếu có.
    Xem examples/xcp_daq_example.a2l:88-122."""
    for child in b.children:
        if child.name != "DAQ":
            continue
        t = child.tokens
        if len(t) < 4:
            return None, {}, {}

        daq_info = XcpDaqInfo(
            dynamic_daq=(t[0] == "DYNAMIC"),
            max_daq=_to_int(t[1]),
            max_event_channel=_to_int(t[2]),
            min_daq=_to_int(t[3]),
        )

        events: dict[int, EventChannel] = {}
        for event_wrapper in child.children:
            if event_wrapper.name != "EVENT":
                continue
            for ev_block in event_wrapper.children:
                if ev_block.name != "EVENT":
                    continue
                ev = _extract_event_channel(ev_block)
                if ev is not None:
                    events[ev.number] = ev

        static_lists: dict[int, StaticDaqList] = {}
        for daq_list_block in child.children:
            if daq_list_block.name != "DAQ_LIST":
                continue
            sl = _extract_static_daq_list(daq_list_block)
            if sl is not None:
                static_lists[sl.number] = sl

        return daq_info, events, static_lists

    return None, {}, {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(text: str) -> A2LDatabase:
    """Parse A2L *text* and return a populated A2LDatabase.

    Record-layout → characteristic resolution is NOT done here; call
    ``database.load()`` (which calls ``_resolve``) for a fully resolved DB.

    Per-block parse errors are logged as warnings and skipped so one bad
    block does not corrupt the entire database.
    """
    root = parse_tree(text)
    db = A2LDatabase()

    def _visit(block: _Block) -> None:
        bname = block.tokens[0] if block.tokens else "?"
        if block.name == "MEASUREMENT":
            try:
                m = _extract_measurement(block)
                if m:
                    db.measurements[m.name] = m
            except Exception as exc:
                _log.warning("Skipping MEASUREMENT %r: %s", bname, exc)

        elif block.name == "CHARACTERISTIC":
            try:
                c = _extract_characteristic(block)
                if c:
                    db.characteristics[c.name] = c
            except Exception as exc:
                _log.warning("Skipping CHARACTERISTIC %r: %s", bname, exc)

        elif block.name == "RECORD_LAYOUT":
            try:
                rl = _extract_record_layout(block)
                if rl:
                    db.record_layouts[rl.name] = rl
            except Exception as exc:
                _log.warning("Skipping RECORD_LAYOUT %r: %s", bname, exc)

        elif block.name == "TYPEDEF_STRUCTURE":
            try:
                st = _extract_struct_type(block)
                if st:
                    db.struct_types[st.name] = st
            except Exception as exc:
                _log.warning("Skipping TYPEDEF_STRUCTURE %r: %s", bname, exc)

        elif block.name == "TYPEDEF_CHARACTERISTIC":
            try:
                ct = _extract_characteristic_type(block)
                if ct:
                    db.characteristic_types[ct.name] = ct
            except Exception as exc:
                _log.warning("Skipping TYPEDEF_CHARACTERISTIC %r: %s", bname, exc)

        elif block.name == "TYPEDEF_MEASUREMENT":
            try:
                mt = _extract_measurement_type(block)
                if mt:
                    db.measurement_types[mt.name] = mt
            except Exception as exc:
                _log.warning("Skipping TYPEDEF_MEASUREMENT %r: %s", bname, exc)

        elif block.name == "INSTANCE":
            try:
                inst = _extract_instance(block)
                if inst:
                    db.instances[inst.name] = inst
            except Exception as exc:
                _log.warning("Skipping INSTANCE %r: %s", bname, exc)

        elif (block.name == "IF_DATA" and block.tokens and block.tokens[0] == "XCP"
              and any(c.name in ("PROTOCOL_LAYER", "DAQ", "XCP_ON_CAN", "XCP_ON_CAN_FD")
                      for c in block.children)):
            # Điều kiện any(...) phân biệt IF_DATA XCP cấp MODULE (có các
            # child này) với IF_DATA XCP lồng trong MEASUREMENT (chỉ có
            # DAQ_EVENT, xem _extract_measurement_event_channel) — thiếu
            # điều kiện này thì measurement nào cũng ghi đè db.protocol_info
            # bằng giá trị mặc định trống, vì _extract_xcp_protocol_info
            # không tìm thấy PROTOCOL_LAYER trong IF_DATA của measurement.
            try:
                proto = _extract_xcp_protocol_info(block)
                if proto:
                    db.protocol_info = proto
            except Exception as exc:
                _log.warning("Skipping IF_DATA XCP (protocol): %s", exc)
            try:
                daq_info, events, static_lists = _extract_xcp_daq(block)
                if daq_info is not None:
                    db.daq_info = daq_info
                    db.events = events
                    db.static_daq_lists = static_lists
            except Exception as exc:
                _log.warning("Skipping IF_DATA XCP (DAQ): %s", exc)

        for child in block.children:
            _visit(child)

    for child in root.children:
        _visit(child)

    return db
