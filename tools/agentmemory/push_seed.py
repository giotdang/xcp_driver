#!/usr/bin/env python3
"""Đẩy một file seed memory vào agentmemory qua REST API.

Dùng khi memory được soạn trong một phiên Claude Code chạy trên cloud: phiên
đó không với tới agentmemory (localhost:3111 ở container không phải máy bạn),
nên memory được commit vào repo dưới dạng JSON rồi đẩy lên sau, trên máy có
agentmemory đang chạy.

    agentmemory                       # bật server, cửa sổ riêng
    python3 tools/agentmemory/push_seed.py --dry-run     # xem trước
    python3 tools/agentmemory/push_seed.py               # đẩy thật

Chỉ dùng thư viện chuẩn — không cần cài gì thêm.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://localhost:3111"
HERE = Path(__file__).resolve().parent
# Trường bắt buộc phải là MẢNG theo API (.claude/CLAUDE.md): truyền chuỗi phân
# tách dấu phẩy thì server nhận nhưng lưu sai, nên chặn ngay tại đây.
LIST_FIELDS = ("concepts", "files")


def load_entries(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"{path}: file seed phải là một JSON array")
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise SystemExit(f"{path}: phần tử #{i} không phải object")
        if not entry.get("content"):
            raise SystemExit(f"{path}: phần tử #{i} thiếu 'content'")
        for field in LIST_FIELDS:
            if field in entry and not isinstance(entry[field], list):
                raise SystemExit(
                    f"{path}: phần tử #{i} có '{field}' là "
                    f"{type(entry[field]).__name__}, API yêu cầu mảng")
    return data


def post(url: str, payload: dict, timeout: float) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seed", nargs="?", type=Path,
                    help="file seed .json (mặc định: mọi seed_*.json cạnh script này)")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"gốc API (mặc định {DEFAULT_URL})")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in ra, không gửi")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    seeds = [args.seed] if args.seed else sorted(HERE.glob("seed_*.json"))
    if not seeds:
        print("Không tìm thấy file seed nào.", file=sys.stderr)
        return 1

    entries: list[tuple[Path, dict]] = []
    for path in seeds:
        entries.extend((path, e) for e in load_entries(path))
    print(f"{len(entries)} memory từ {len(seeds)} file seed.")

    if args.dry_run:
        for path, entry in entries:
            head = entry["content"].split(". ")[0][:90]
            print(f"  [{entry.get('type', '?'):12}] {head}…   ({path.name})")
        print("\n--dry-run: chưa gửi gì. Bỏ cờ này để đẩy thật.")
        return 0

    endpoint = args.url.rstrip("/") + "/agentmemory/remember"
    failed = 0
    for path, entry in entries:
        status, body = post(endpoint, entry, args.timeout)
        head = entry["content"][:60].replace("\n", " ")
        if 200 <= status < 300:
            print(f"  OK  [{status}] {head}…")
        else:
            failed += 1
            reason = body or "không rõ"
            if status == 0:
                reason = (f"không kết nối được {args.url} ({reason}). "
                          "agentmemory đã chạy chưa?")
            print(f"  LỖI [{status}] {head}…\n        {reason}", file=sys.stderr)
            if status == 0:
                break   # server không lên thì các entry sau cũng vậy

    if failed:
        print(f"\n{failed}/{len(entries)} memory KHÔNG đẩy được.", file=sys.stderr)
        return 1
    print(f"\nĐã đẩy {len(entries)} memory vào agentmemory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
