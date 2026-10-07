# XCP Driver — Project Guide

## Project Overview

XCP (Universal Measurement and Calibration Protocol) v1.0 slave implementation cho Infineon AURIX TriCore TC2xx, dựa trên **Vector Informatik XcpBasic v1.30.04** (refactored). Mục đích: cho phép công cụ đo lường/hiệu chỉnh (CANape, INCA) truy cập ECU qua CAN để đọc tín hiệu (DAQ) và ghi tham số hiệu chỉnh (CAL).

## Truy xuất code — dùng codegraph thay vì tìm kiểm thủ công trong workspace

## Persistent Memory — dùng agentmemory thay vì file .md

Project này đã cài đặt [agentmemory](https://github.com/rohitg00/agentmemory) (MCP server `agentmemory`, đã kết nối trong Claude Code ở user scope) làm nơi lưu trữ memory xuyên suốt các phiên làm việc, **thay thế** cho hệ thống file `memory/*.md` mặc định.

- **Ưu tiên dùng agentmemory MCP tools** (`memory_save`, `memory_recall`, `memory_smart_search`, v.v.) để lưu và truy xuất context về project này — không tạo thêm file `.md` mới trong hệ thống auto-memory nội bộ.
- Nếu MCP tools của `agentmemory` chưa nạp trong phiên hiện tại (do server mới kết nối giữa phiên), có thể gọi trực tiếp REST API tại `http://localhost:3111`:
  - Lưu: `POST /agentmemory/remember` — body `{content, type, concepts: [...], files: [...], project: "xcp_driver"}` (**`concepts` và `files` phải là mảng**, không phải chuỗi phân tách dấu phẩy).
  - Truy xuất: `POST /agentmemory/search` — body `{query, limit}`.
- Server `agentmemory` chạy nền, cần được khởi động thủ công (lệnh `agentmemory` trong terminal) sau mỗi lần khởi động máy — không tự chạy cùng hệ thống.
- Các file `memory/*.md` cũ (ở `~/.claude/projects/.../memory/` và bản copy tại `.claude/memory/` trong repo) vẫn được **giữ nguyên làm backup**, không xoá — nhưng không phải nguồn memory chính thức nữa.
