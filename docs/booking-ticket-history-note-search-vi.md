# Ticket trong booking và giao diện tìm ghi chú

## Danh sách ticket trong thông tin booking

Khung **Danh sách ticket** luôn hiển thị trong booking, phía trên form tạo ticket:

- Hai nhóm **Đang chờ QC** và **Đã xử lý**, có tổng số và phân trang riêng (5 ticket/trang).
- Nếu booking chỉ có ticket đã xử lý, khung tự mở nhóm này ở lần tải đầu.
- Mỗi dòng có tiêu đề, trích nội dung, người tạo, thời gian và số ảnh. Ticket đã xử lý bổ sung người xử lý, thời gian và kết quả xử lý.
- Bấm tiêu đề mở đúng ticket ở trang Ticket với bộ lọc booking/trạng thái tương ứng; xem toàn bộ nội dung và ảnh tại đó.
- **Tạo ticket** mở form và đặt con trỏ vào phần chọn lỗi. Sau khi tạo xong, danh sách cập nhật. Nút **Làm mới** tải lại cả hai nhóm.

Phạm vi quyền giữ nguyên: Agent xem ticket do mình tạo; QC/Admin xem mọi ticket của booking. Không cần migration.

## Summary → Tìm ghi chú

- Ô từ khóa riêng, bộ lọc ngày / Agent / trạng thái, nút đặt lại và lọc nhanh hôm nay / 7 ngày / 30 ngày / ghi chú của tôi.
- Nếu để trống cả hai ngày, hệ thống dùng 30 ngày gần nhất; mỗi lần tìm tối đa 180 ngày, tính cả ngày đầu và cuối. Các mốc nhanh dùng ngày nghiệp vụ do backend cung cấp.
- Kết quả đếm **booking**, mỗi booking hiển thị ghi chú khớp mới nhất và số ghi chú khớp trong phạm vi đã lọc. Nội dung dài có nút đọc toàn bộ; từ khóa được tô nổi bật, nội dung luôn được hiển thị như văn bản.
- Bấm **Tìm kiếm** để áp dụng thay đổi. Kết quả hiện tại luôn ghi bộ lọc đã áp dụng; phân trang không tự áp dụng bản nháp vừa sửa.
- Bộ lọc và số trang nằm trong URL, hỗ trợ tải lại, chia sẻ đường dẫn và Back/Forward. Trang vượt tổng số hiện tại được điều chỉnh về trang cuối.
- Có trạng thái hướng dẫn ban đầu, đang tải, không có kết quả, lỗi và thử lại; bố cục hỗ trợ điện thoại và chế độ tối.
