# Quản lý ticket cho Admin và biểu đồ trong Excel

## Admin quản lý dữ liệu ticket

Vào **Admin → Quản lý ticket** hoặc chọn **Quản lý ticket** ở trang Ticket. Màn hình mặc định hiển thị mọi trạng thái, có thể lọc theo booking, người tạo, ngày tạo và trạng thái.

- **Mở ticket**: xem tiêu đề, toàn bộ nội dung, booking, người tạo, ảnh và kết quả xử lý.
- **Sửa ticket**: sửa tiêu đề, gợi ý lỗi, nội dung tiếng Anh, trạng thái và kết quả xử lý. Chọn gợi ý lỗi sẽ tạo lại tiêu đề kèm mã booking; nút **Dùng tiêu đề gợi ý** khôi phục mẫu nếu Admin đã sửa tiêu đề riêng để test.
- Chuyển sang đã xử lý sẽ ghi nhận Admin thực hiện. Sửa nội dung ticket đã được QC xử lý giữ nguyên QC và thời điểm xử lý ban đầu. Chuyển lại chờ QC xóa kết quả xử lý cũ.
- Nếu ticket đã được người khác sửa hoặc xử lý trong lúc form đang mở, hệ thống giữ bản nháp và yêu cầu đóng form/mở lại ticket để đối chiếu. Không ghi đè bản mới bằng dữ liệu cũ.
- **Xóa**: nhập lý do để chuyển ticket vào thùng rác. Vào **Thùng rác** để khôi phục; nội dung và ảnh được giữ lại. Xóa vĩnh viễn tiếp tục dùng bước xem trước và xác nhận của thùng rác hiện có, đồng thời đưa ảnh vào hàng chờ dọn kho riêng tư.

Chỉ Admin có quyền sửa/xóa ticket. Agent và QC giữ quyền xem ticket theo phạm vi cũ; QC vẫn xử lý và gộp ticket như trước. Không cần thêm migration cho lần cập nhật này.

## Dashboard biểu đồ trong file Excel

Báo cáo Excel ở trang Báo cáo và Báo cáo của tôi mở bằng sheet **Visual dashboard**, gồm các chỉ số chính và biểu đồ:

- Xu hướng booking, cập nhật và hoàn tất theo ngày.
- Khối lượng công việc theo Agent.
- Phân bố trạng thái cuối của booking.
- Tỷ lệ hoàn tất booking.
- Số booking theo station.
- Phân loại Hotel / Transportation / Unclassified.

Các sheet Executive summary, Booking detail và các bảng tổng hợp vẫn có đầy đủ để đối chiếu. Biểu đồ là biểu đồ Excel có thể chỉnh sửa. Sheet **Chart data** chứa dữ liệu số làm nguồn cho biểu đồ và được ẩn để gọn file; có thể dùng Unhide trong Excel nếu muốn xem hoặc chỉnh nguồn.

Báo cáo ngày cá nhân và báo cáo ngày nhóm phiên bản cũ cũng có tab **Visual dashboard** bổ sung, với các biểu đồ phù hợp dữ liệu của từng loại báo cáo. Thứ tự các sheet dữ liệu cũ được giữ lại trong các bản xuất này. CSV tiếp tục là bảng dữ liệu thuần.

### Cách đọc số liệu

- Biểu đồ sử dụng đúng phạm vi Agent / nhóm và các bộ lọc đã áp dụng khi xuất báo cáo; Agent không nhận dữ liệu của người khác trong dữ liệu nguồn biểu đồ.
- Báo cáo trung tâm đếm booking phân biệt; cập nhật là số note. Một booking có nhiều Agent cùng tham gia có thể xuất hiện trong số liệu của nhiều Agent, như bảng hiệu suất hiện tại.
- Báo cáo daily-record cũ đếm từng dòng cập nhật, không gọi các lượt cập nhật là booking phân biệt.
- Các biểu đồ nhiều nhóm giữ nhóm lớn nhất và gộp phần còn lại thành **Other categories**. Tổng của biểu đồ vẫn bằng tổng dữ liệu nguồn; sheet chi tiết giữ mọi dòng.
- Báo cáo không có hoạt động hiển thị thông báo trống và các chỉ số 0, không tạo điểm dữ liệu giả.
- Thời gian và ngày sử dụng timezone nghiệp vụ của báo cáo.
