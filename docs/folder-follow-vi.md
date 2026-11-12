# Follow folder và follow booking

Workspace dùng tên **Follow / Theo dõi**. Nút Follow booking giữ chức năng theo dõi
một booking theo tháng. Nút **Follow folder / Theo dõi folder** có tại thông tin
booking và trang folder: theo dõi toàn bộ folder CW + station, kể cả các tháng tạo mới.
Mỗi folder chỉ chiếm một dòng trong danh sách theo dõi.

Trong Workspace → Following / Đang theo dõi, chọn **Folder** (mặc định) hoặc **Booking**.
Mở folder từ danh sách để chọn tháng. Bỏ theo dõi folder không bỏ những booking đã
được theo dõi riêng, và ngược lại. Theo dõi là lựa chọn cá nhân, không thay đổi quyền
truy cập của bất kỳ người dùng nào.

Khi người khác thêm note, người theo dõi folder nhận thông báo cho booking cụ thể
được cập nhật. Các tháng tương lai tự được bao phủ mà không tạo subscription riêng
cho từng tháng. Người follow cả folder và booking chỉ nhận một thông báo cho một
lần cập nhật; các cập nhật chưa đọc được gộp như trước. Người tự cập nhật không tự
nhận thông báo; thông báo takeover được ưu tiên để tránh gửi trùng.

Tối đa 200 folder và 200 booking riêng cho mỗi user. Danh sách phân trang ở server.
Folder vào thùng rác tạm ẩn, restore giữ follow; purge folder xóa subscription của
folder. Tài khoản không thể purge khi còn subscription tham chiếu chưa được xử lý.

Migration `0017_folder_followers` chỉ tạo bảng `folder_followers`, không đổi hay
xóa `booking_watchers`. Tính năng phân công folder/nhập Excel ở PR #3 đã được hủy;
không đưa code, dữ liệu hoặc migration phân công đó lên main.

API mới: `GET/PUT/DELETE /api/v1/folders/{CW-STATION}/follow` và
`GET /api/v1/following/folders?page=1&size=10`. API `/watch` và `/watching` của booking
được giữ tương thích; chữ Watch chỉ được thay bằng Follow trên giao diện.

Render đang cấu hình tự deploy branch main, chạy `alembic upgrade head` khi khởi động.
Sau khi push cần xác minh đúng commit đã live trên Render và frontend Vercel.
