# Seed memory cho agentmemory

Nơi để **memory soạn trong phiên cloud** nằm chờ cho tới khi được đẩy vào
`agentmemory` trên máy cá nhân.

## Vì sao cần

`agentmemory` chạy như một tiến trình nền trên máy bạn, phục vụ ở
`localhost:3111`. Phiên Claude Code chạy trên cloud (claude.ai/code) nằm trong
container riêng — `localhost` ở đó là chính container, không phải máy bạn — nên
phiên cloud **không** gọi được `memory_save` hay REST API của agentmemory.

Cách đi vòng: phiên cloud ghi memory thành file JSON trong repo (được commit nên
không mất khi container bị thu hồi), rồi bạn chạy script này trên máy mình.

## Cách dùng

```bash
agentmemory                                    # bật server (cửa sổ riêng)
python3 tools/agentmemory/push_seed.py --dry-run   # xem sẽ đẩy những gì
python3 tools/agentmemory/push_seed.py             # đẩy thật
```

Không truyền tham số thì script đẩy **mọi** file `seed_*.json` trong thư mục
này. Chỉ định một file cụ thể:

```bash
python3 tools/agentmemory/push_seed.py tools/agentmemory/seed_2026-10-07_xcp_event_mapping.json
```

Tuỳ chọn: `--url` (mặc định `http://localhost:3111`), `--timeout`.

Script chỉ dùng thư viện chuẩn của Python, không cần cài gì thêm. Mã thoát khác
0 nếu có memory nào không đẩy được.

## Định dạng file seed

Một JSON array, mỗi phần tử là body của `POST /agentmemory/remember`:

```json
{
  "content": "Nội dung memory, viết đủ ý để đứng một mình.",
  "type": "issue",
  "concepts": ["xcptool", "DAQ"],
  "files": ["xcptool/src/xcptool/master/daq.py"],
  "project": "xcp_driver"
}
```

`concepts` và `files` **phải là mảng** — script chặn ngay nếu bạn viết thành
chuỗi phân tách dấu phẩy (xem `.claude/CLAUDE.md`).

## Sau khi đẩy xong

Script không chống trùng — agentmemory không có API để biết memory đã tồn tại
hay chưa. Đẩy một file **một lần**; đẩy lại sẽ tạo bản sao. Xong rồi thì xoá
file seed đó đi (hoặc đổi tên bỏ tiền tố `seed_`) để lần sau không đẩy nhầm.
