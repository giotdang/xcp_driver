"""A2L database loader: parse a file and resolve record-layout types."""
from __future__ import annotations

from pathlib import Path

from .parser import parse
from .types import A2LDatabase


def load(path: str | Path) -> A2LDatabase:
    """Parse an A2L file and return a fully resolved A2LDatabase.

    Steps:
    1. Read the file as UTF-8 (replace undecodable bytes).
    2. ``parse()`` — build measurements, characteristics, record_layouts.
    3. ``_resolve()`` — fill Characteristic.datatype from RecordLayout.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    db = parse(text)
    _resolve(db)
    return db


def _resolve(db: A2LDatabase) -> None:
    """Propagate RecordLayout.datatype → Characteristic.datatype (và tương tự
    cho CharacteristicTypeDef — struct-leaf template cần datatype thật
    TRƯỚC khi _resolve_instances() cần tính byte size của nó)."""
    for char in db.characteristics.values():
        rl = db.record_layouts.get(char.record_layout)
        if rl:
            char.datatype = rl.datatype
    for tmpl in db.characteristic_types.values():
        rl = db.record_layouts.get(tmpl.record_layout)
        if rl:
            tmpl.datatype = rl.datatype
