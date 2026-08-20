================================================================================
xcptool - Hướng dẫn Cài đặt và Chạy (Dành cho Người mới)
================================================================================

Chào mừng bạn đến với xcptool! 
Đây là công cụ đo lường và hiệu chỉnh ECU qua giao thức CAN/XCP. Để bắt đầu sử dụng, bạn chỉ cần làm theo các bước rất đơn giản dưới đây:

--------------------------------------------------------------------------------
YÊU CẦU TRƯỚC KHI CÀI ĐẶT
--------------------------------------------------------------------------------
1. Máy tính của bạn cần được cài đặt sẵn Python phiên bản 3.11 trở lên.
2. Bạn có thể tải Python tại đây: https://www.python.org/downloads/
   * LƯU Ý QUAN TRỌNG: Trong quá trình cài đặt Python, ở màn hình đầu tiên, 
     hãy nhớ TÍCH CHỌN ô "Add python.exe to PATH" (hoặc "Add Python to PATH").

--------------------------------------------------------------------------------
BƯỚC 1: CÀI ĐẶT MÔI TRƯỜNG (Chỉ làm 1 lần duy nhất)
--------------------------------------------------------------------------------
1. Mở thư mục chứa mã nguồn xcptool.
2. Click đúp chuột vào file `setup.bat`.
3. Một cửa sổ đen (Console) sẽ hiện lên và tự động thực hiện các thao tác:
   - Kiểm tra phiên bản Python trên máy.
   - Tạo môi trường ảo (.venv) để không ảnh hưởng đến máy của bạn.
   - Tự động tải và cài đặt toàn bộ các thư viện cần thiết.
4. Quá trình này diễn ra mất khoảng 1-2 phút tùy tốc độ mạng. 
   Khi chạy xong, nếu thấy báo [SUCCESS] ở dòng cuối cùng, bạn có thể ấn phím 
   bất kỳ để đóng cửa sổ lại.

--------------------------------------------------------------------------------
BƯỚC 2: KHỞI CHẠY ỨNG DỤNG (Làm mỗi lần muốn sử dụng)
--------------------------------------------------------------------------------
1. Click đúp chuột vào file `run.bat`.
2. Một cửa sổ Console sẽ hiện lên để khởi động môi trường, sau đó giao diện
   chính của xcptool sẽ xuất hiện. (Lưu ý: Không tắt cửa sổ Console màu đen 
   khi đang dùng ứng dụng).

--------------------------------------------------------------------------------
LƯU Ý THÊM
--------------------------------------------------------------------------------
- Cấu hình mạng CAN: Nếu bạn cần thay đổi ID CAN hoặc tốc độ Bitrate cho 
  kênh CAN ảo/thực, bạn có thể cấu hình ở cửa sổ "Select CAN Interface"
  lúc mở phần mềm lên.
- Giao diện: Tại các bảng Trace, Measurement, Calibration, bạn có thể tự do 
  kéo thả độ rộng của các cột để xem thông tin thoải mái hơn.
  
Chúc bạn sử dụng phần mềm hiệu quả!
