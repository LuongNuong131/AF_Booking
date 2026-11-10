# Báo cáo Agent, ticket QC và ảnh note

## Báo cáo cá nhân

Agent mở **Báo cáo**; QC/Admin chọn **Báo cáo ngày của tôi** trong trang báo cáo.
Báo cáo dùng ngày làm việc của hệ thống (`BUSINESS_TIMEZONE`, mặc định Việt Nam).
Một booking có nhiều cập nhật của cùng Agent trong ngày chỉ tính một booking.
Số lần cập nhật được tính riêng. Trạng thái cuối là trạng thái ở note cuối của
chính Agent trong ngày, kể cả khi booking sau đó chuyển sang người khác.

Excel gồm bảng tổng hợp và danh sách booking, được lọc theo tài khoản trên server.
Báo cáo cá nhân không cấp quyền truy cập báo cáo toàn đội cho Agent.

## Ticket QC

Tại booking, mở **Ticket gửi QC**, mô tả lỗi và việc cần làm với khách hàng, rồi
chọn **Tạo ticket**. QC/Admin nhận thông báo trong chuông; thông báo vẫn được giữ
khi họ offline. Web Push dùng cấu hình VAPID và quyền thông báo đã có nếu được bật.

Trang **Ticket** cho Agent xem ticket của mình; QC/Admin xem hàng chờ toàn đội.
Mặc định **Chờ QC** gồm tất cả ticket chưa thao tác, cả các ngày trước. Bộ lọc ngày
là ngày tạo ticket. QC ghi kết quả và chọn **Đánh dấu đã thao tác**; thao tác được
lưu cùng người xử lý và thời gian. Tạo ticket hoặc đánh dấu lại sau một lần retry
không nhân đôi dữ liệu/thông báo. QC/Admin có thể xuất Excel theo bộ lọc.

Task nhắc việc cá nhân vẫn hoạt động độc lập với ticket gửi QC.

## Release

1. Sao lưu database theo quy trình vận hành hiện có.
2. Áp dụng migration `0014` bằng `alembic upgrade head` trên backend. Paid Render
   dùng pre-deploy command; service Free cần chạy migration qua môi trường quản trị
   đã cấu hình database. Giữ khóa database trong secret manager.
3. Deploy backend rồi frontend. Kiểm tra `/health` và `/api/v1/ready`.
4. Đăng nhập Agent để kiểm tra báo cáo riêng, Excel và tạo ticket. Đăng nhập QC để
   kiểm tra chuông thông báo, hàng chờ và đánh dấu đã thao tác.
5. Bật kho ảnh theo [hướng dẫn R2](note-images-vi.md). Khi chưa cấu hình kho ảnh,
   các chức năng báo cáo, ticket và note văn bản tiếp tục hoạt động.

R2 dùng các khóa `S3_*` chỉ trên backend. Chỉ bật đầy đủ bốn trường endpoint,
bucket, access key và secret key trong cùng lần lưu cấu hình.
