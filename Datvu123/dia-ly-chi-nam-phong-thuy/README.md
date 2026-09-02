---
title: Địa Lý Chỉ Nam - Phong Thuỷ Nhà Đất
emoji: 🧭
colorFrom: green
colorTo: yellow
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Hướng nhà hợp tuổi và năm làm nhà theo Bát trạch
---

# 🧭 Địa Lý Chỉ Nam · Phong thuỷ nhà đất

Nhập ngày sinh — app tính ra cung mệnh, tám hướng tốt xấu, những năm làm nhà được,
cách bố trí cửa bếp giường, và luận hình thế thửa đất từ ảnh bạn tải lên.

## Có gì

- **La bàn Bát trạch** — cung phi từ năm sinh và giới tính, tám hướng với đủ tám du niên (Sinh Khí, Thiên Y, Diên Niên, Phục Vị, Hoạ Hại, Lục Sát, Ngũ Quỷ, Tuyệt Mệnh).
- **Năm làm nhà** — bảng 12 năm tới, xét đồng thời Kim Lâu, Hoang Ốc và Tam Tai; năm nào sạch cả ba thì đánh dấu làm được. Kèm mục hoá giải khi phạm tuổi.
- **Bố trí** — cửa chính, phòng ngủ, bàn thờ, bàn làm việc đặt vào cung tốt; bếp và nhà vệ sinh theo lối *toạ hung hướng cát*.
- **Thửa đất** — tải ảnh sổ đỏ / bản vẽ / ảnh vệ tinh, chạm 4 góc, app đo tỉ lệ mặt tiền–mặt hậu, độ méo, độ vuông vức rồi luận theo phong thuỷ hình thể. Điền bề ngang thật thì quy đổi ra mét và ước tính diện tích.

## Tính bằng cách nào

Mọi con số đều là **phép tính có quy tắc**, không phải phỏng đoán:

- **Âm lịch** — thuật toán Hồ Ngọc Đức (tính ngày sóc và kinh độ mặt trời, múi giờ +7), nên người sinh trước Tết được tính đúng vào năm âm trước đó.
- **Cung phi bát trạch** — từ hai chữ số cuối năm âm lịch và giới tính. Đã đối chiếu khớp với các nguồn tra cứu: nam 1990→Khảm, nam 1985→Càn, nam 1983→Cấn, nam 1989→Khôn, nữ 1987→Khôn, nữ 1986→Khảm, nam 2000→Ly.
- **Bát biến du niên** — suy trực tiếp từ quy tắc biến hào giữa quái mệnh và quái hướng (biến hào 3 → Sinh Khí, hào 2 → Tuyệt Mệnh, cả ba hào → Diên Niên...) thay vì chép bảng. Đã đối chiếu khớp trọn hàng cung Càn và cung Khảm của bảng chuẩn.
- **Kim Lâu** — tuổi mụ chia 9, dư 1/3/6/8 là phạm (Thân, Thê, Tử, Lục Súc).
- **Hoang Ốc** — cộng chữ số hàng chục với hàng đơn vị của tuổi mụ, đếm trên 6 cung. Đã đối chiếu khớp **toàn bộ 33 tuổi phạm** thường được lưu truyền (12, 14, 15, 18, 21, ... 74, 75).
- **Tam Tai** — theo nhóm tam hợp của chi tuổi.
- **Hình thế đất** — hình học thuần tuý: công thức giày tính diện tích, tỉ lệ mặt hậu trên mặt tiền, độ lệch góc so với 90°, độ vuông vức so với hình chữ nhật bao ngoài.

Toàn bộ 57 phép kiểm thử đối chiếu đều đạt.

## Quyền riêng tư

Không có backend. Mọi tính toán và xử lý ảnh chạy trong trình duyệt trên máy bạn;
ảnh thửa đất **không được tải lên đâu cả**.

## Lưu ý

Các công thức ở đây được tính đúng theo tài liệu cổ, nhưng "tính đúng theo công thức"
khác với "đúng trong thực tế". Phong thuỷ được giới khoa học xếp vào **nguỵ khoa học**,
và bản thân nó có nhiều trường phái mâu thuẫn nhau — Bát trạch, Huyền không phi tinh và
Loan đầu có thể cho ba kết luận khác nhau về cùng một căn nhà. Hãy dùng app này làm kênh
tham khảo bên cạnh những yếu tố quyết định thật: pháp lý, giá, hướng nắng gió, đường sá
và khả năng tài chính.
