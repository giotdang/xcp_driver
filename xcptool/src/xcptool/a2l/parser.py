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
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .types import A2LDatabase, Characteristic, Measurement, RecordLayout

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

    # MATRIX_DIM may be followed by one or more integer values
    matrix_dim: list[int] = []
    for i, tok in enumerate(t):
        if tok == "MATRIX_DIM":
            j = i + 1
            while j < len(t):
                try:
                    matrix_dim.append(int(t[j]))
                    j += 1
                except ValueError:
                    break
            break

    return Measurement(
        name=name,
        description=description,
        datatype=datatype,
        address=address,
        lower_limit=lower_limit,
        upper_limit=upper_limit,
        compu_method=compu_method,
        matrix_dim=matrix_dim,
    )


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

        for child in block.children:
            _visit(child)

    for child in root.children:
        _visit(child)

    return db
