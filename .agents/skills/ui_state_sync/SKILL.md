---
name: ui_state_sync
description: Hướng dẫn quản lý và đồng bộ trạng thái UI (enabled/disabled, visibility, consistency) để tránh lỗi bất đồng bộ trạng thái giữa lúc init, runtime event và save config.
---

# UI State Synchronization (Đồng bộ trạng thái giao diện)

## 1. Vấn đề cốt lõi
Khi xây dựng giao diện (Qt/PySide/QFluentWidgets), các widget điều khiển thường có trạng thái phụ thuộc chéo (ví dụ: `Data Bitrate` chỉ khả dụng khi `CAN FD = True` VÀ `Custom Bit Timing = False`).
Nếu logic `setEnabled`, `setVisible` bị viết phân tán rải rác ở nhiều hàm sự kiện riêng lẻ, ứng dụng rất dễ bị mất đồng bộ trạng thái khi:
- Nạp cấu hình ban đầu (`init` / `load_config`).
- Tương tác với các control liên quan (`checkbox toggled`, `dialog closed`).
- Lưu hoặc đọc lại cấu hình.

---

## 2. Nguyên tắc thiết kế bắt buộc

### Nguyên tắc 1: Centralized State Sync (Hàm đồng bộ tập trung)
- **Tuyệt đối không** gọi `widget.setEnabled()` hoặc `widget.setVisible()` rải rác ở nhiều event handler khác nhau.
- **Tạo duy nhất một hàm trung tâm** (ví dụ: `_sync_controls()` hoặc `_update_ui_state()`) để tính toán và áp dụng toàn bộ derived state của các control dựa trên trạng thái hiện tại.
- Mọi event handler chỉ làm 2 việc:
  1. Cập nhật biến trạng thái (`self._state_a = ...`).
  2. Gọi `self._sync_controls()`.

```python
# VÍ DỤ CHUẨN:
def _sync_controls(self) -> None:
    """Nơi duy nhất quyết định trạng thái enabled/disabled của các control."""
    is_fd = self.fd_cb.isChecked()
    custom_timing = self._custom_bit_timing

    self.bitrate_combo.setEnabled(not custom_timing)
    self.data_bitrate_combo.setEnabled(is_fd and not custom_timing)
    self._fd_label.setEnabled(is_fd)

def _on_fd_changed(self, state: int) -> None:
    # Không setEnabled trực tiếp ở đây, gọi hàm đồng bộ trung tâm
    self._sync_controls()

def _apply_initial_config(self) -> None:
    # Nạp dữ liệu xong -> gọi hàm đồng bộ trung tâm
    self._sync_controls()
```

### Nguyên tắc 2: Quy tắc kiểm tra 3 điểm (Lifecycle Checklist)
Khi thêm hoặc chỉnh sửa bất kỳ option/control nào có trạng thái phụ thuộc, bắt buộc phải kiểm tra qua đủ 3 điểm:
1. **Load ban đầu**: Trạng thái UI khi mở dialog với các tổ hợp config khác nhau.
2. **Runtime Events**: Trạng thái UI khi người dùng bật/tắt/thay đổi giá trị của từng option liên quan.
3. **Build/Save config**: Giá trị xuất ra khi nhấn OK/Save có phản ánh đúng các ràng buộc trạng thái hay không.

### Nguyên tắc 3: Kiểm thử tổ hợp (Combinatorial / Parametrized Testing)
- Khi có các cờ phụ thuộc chéo ($N$ điều kiện), bắt buộc phải viết Unit Test kiểm thử ma trận trạng thái cho tất cả các tổ hợp (ví dụ: $2 \times 2 = 4$ cases: `is_fd` True/False $\times$ `custom_timing` True/False).
