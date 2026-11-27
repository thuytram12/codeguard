# Chấm Tự Luận – chấm bài kiểm tra viết tay bằng AI

Thầy/cô nhập đề và đáp án kèm thang điểm, chụp hoặc scan bài làm viết tay của học sinh rồi tải lên. AI (Claude) sẽ:

- đọc chữ viết tay và chép lại bài làm từng câu (công thức toán hiện đúng dạng),
- chấm theo thang điểm của thầy/cô, từng ý, điểm làm tròn tới 0,25,
- viết nhận xét cho từng câu và nhận xét chung,
- đánh dấu **"Nên xem lại"** khi ảnh mờ, thiếu trang hoặc AI không chắc.

Cuối cùng bấm **Tải Excel** để lấy bảng điểm cả lớp.

> Phiên bản đầu tập trung vào môn **Toán**, nhưng đề và thang điểm do thầy/cô nhập nên dùng được cho môn khác.

## Cần chuẩn bị

1. **Python 3.9 trở lên** trên máy thầy/cô (Windows: tải ở python.org, khi cài nhớ tích *Add Python to PATH*).
2. **Máy có Internet** (bài được gửi tới AI của Anthropic để chấm).
3. **Khoá API của Anthropic**: vào <https://console.anthropic.com> → đăng ký → nạp tiền (Billing) → **API Keys** → *Create Key*. Khoá có dạng `sk-ant-...`.

## Cách dùng

1. Tải thư mục `chamtuluan` về máy, ví dụ `D:\ChamTuLuan`.
2. Bấm đúp **`chay.bat`**. Lần đầu nó tự cài thư viện `anthropic` (cần Internet), sau đó trình duyệt tự mở trang `http://127.0.0.1:8800`.
   Không có Windows: mở cửa sổ lệnh trong thư mục, chạy `pip install anthropic` rồi `python chambai.py`.
3. Bấm **⚙ Cài đặt**, dán khoá API, bấm **Lưu** (chỉ làm 1 lần).
4. Bấm **+ Tạo đề mới**:
   - Nhập từng câu: số câu, điểm tối đa, đề bài, **đáp án và thang điểm**. Thang điểm càng chia ý rõ thì AI chấm càng sát.
   - Đề có hình vẽ hoặc đáp án có sẵn trong file: tải ảnh/PDF ở mục *Tệp đề / đáp án*.
   - Bấm **Lưu đề**.
5. Ở tab **Bài làm & kết quả**, tải bài lên:
   - *Các ảnh đã chọn là của 1 học sinh*: chọn tất cả các trang bài của một em (đúng thứ tự), có thể gõ tên.
   - *Mỗi ảnh / mỗi PDF là bài của 1 học sinh*: chọn ảnh của cả lớp cùng lúc, mỗi em một ảnh (hoặc mỗi em một file PDF scan nhiều trang). AI tự đọc họ tên trên bài.
6. AI chấm ngay, mỗi bài khoảng 30 giây đến vài phút, 3 bài cùng lúc. Bấm vào một dòng để xem ảnh bài làm cạnh phần AI chép lại, điểm và nhận xét; có thể sửa tên hoặc **Chấm lại**.
7. Bấm **⬇ Tải Excel** để lấy bảng điểm.

## Mẹo để AI chấm chính xác

- Chụp thẳng, đủ sáng, không bị bóng, cả trang nằm trong khung. Scan PDF là tốt nhất.
- Thang điểm nên ghi rõ từng ý và điểm của ý, các cách giải khác được chấp nhận, lỗi nào trừ bao nhiêu.
- Luôn xem lại các bài có nhãn **Nên xem lại** trước khi công bố điểm.

## Chi phí

Mỗi bài tính tiền theo lượng ảnh và chữ gửi đi và nhận về. Phần đề/đáp án được lưu đệm nên các bài sau cùng đề rẻ hơn. Xem chi phí thực tế trong trang *Usage* của console.anthropic.com.

## Dữ liệu và bảo mật

- Toàn bộ đề, ảnh bài làm và kết quả lưu trong thư mục `dulieu/` trên máy thầy/cô. Khoá API lưu trong `cauhinh.json`. Hai thứ này không được đưa lên GitHub (đã có trong `.gitignore`).
- Ảnh bài làm được gửi tới Anthropic để chấm. Nên dặn học sinh chỉ ghi họ tên, không ghi thông tin cá nhân khác lên bài.
- Trang web chỉ mở được trên chính máy này (`127.0.0.1`), máy khác trong mạng không truy cập được.

## Các file

| File | Để làm gì |
|---|---|
| `chay.bat` | Bấm đúp để chạy (Windows) |
| `chambai.py` | Chương trình chính: máy chủ web nhỏ + gửi bài cho AI chấm |
| `trang.html` | Giao diện trên trình duyệt |

Tuỳ chỉnh trong đầu file `chambai.py`: `MO_HINH` (mô hình AI), `DO_KY` (mức suy nghĩ khi chấm, mặc định `high`), `SO_LUONG_CHAM_CUNG_LUC`, `CONG`.
