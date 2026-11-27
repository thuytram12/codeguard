# CodeGuard – Giám sát phòng thi Tin học

> Trong repo còn có app **Chấm Tự Luận** (chấm bài viết tay bằng AI) ở thư mục [`chamtuluan/`](chamtuluan/README.md).

Hệ thống giám sát máy học sinh trong giờ kiểm tra lập trình. Học sinh được dùng:

- **Code::Blocks**: viết, biên dịch, chạy chương trình C/C++ bình thường
- **Python IDLE**: viết và chạy code Python
- **Notepad**
- **Chrome**, nhưng chỉ ở trang **VNOJ** để xem đề và nộp bài

Khi học sinh mở chương trình khác (trang web khác, Zalo, Word, cmd…):

- Màn hình học sinh hiện **cảnh báo đỏ**. Em vẫn làm bài tiếp được.
- Máy thầy **nhận báo ngay** và ghi vào nhật ký (giờ nào, mở gì, bao lâu).
- Cuối giờ, thầy tải file Excel để xem lại và quyết định xử lý.

> Không dùng Safe Exam Browser nữa, nên Code::Blocks và Python biên dịch, chạy bình thường.

---

## Các file

| File | Dùng ở đâu | Để làm gì |
|---|---|---|
| `chay_may_thay.bat` | Máy thầy | Bấm đúp để chạy chương trình máy thầy |
| `maythay.py` | Máy thầy | Chương trình máy thầy |
| `trangthay.html` | Máy thầy | Trang theo dõi (tự mở trong trình duyệt) |
| `danhsach.txt` | Máy thầy | Danh sách lớp, kèm mã vào bài |
| `quydinh.json` | Máy thầy | Danh sách chương trình được phép (thường không cần sửa) |
| `mo_tuong_lua.bat` | Máy thầy | Mở tường lửa (chạy 1 lần) |
| `giamsat.pyw` | **Máy học sinh** | Chương trình giám sát |
| `goi_hoc_sinh/` | Máy thầy | Python chạy kèm, dùng để tạo gói `GiamSat.zip` cho máy học sinh **chưa cài Python** |

Máy thầy cần Python (không cần cài thêm thư viện nào). **Máy học sinh không cần cài Python.**

---

## A. Chuẩn bị (làm 1 lần)

### Trên máy thầy
1. Tải cả thư mục này về máy, ví dụ để ở `D:\CodeGuard`. Trên GitHub: nút **Code → Download ZIP**, rồi giải nén.
2. Mở `danhsach.txt` bằng Notepad, **xoá tên mẫu** và ghi tên học sinh, mỗi dòng một em. Có thể copy cột tên từ Excel rồi dán vào. Lưu lại.
3. Bấm chuột phải vào `mo_tuong_lua.bat` → **Run as administrator** → chờ báo "Da mo tuong lua" rồi bấm phím bất kỳ.
4. Bấm đúp `chay_may_thay.bat`. Một cửa sổ đen hiện ra và trình duyệt tự mở trang theo dõi.
   - Nếu Windows hỏi *"Allow access"*, tích **cả hai ô** (Private và Public) rồi bấm **Allow**.
   - Mở lại `danhsach.txt` sẽ thấy mỗi em đã có mã, ví dụ `Nguyễn Văn An;4821`.
5. Trên trang theo dõi, bấm **🖨 In mã vào bài**, in ra, cắt và phát cho từng em. Mã giữ nguyên cho các buổi sau, trừ khi thầy bấm **Tạo mã mới**.

### Trên máy học sinh (không cần cài Python)
Học sinh dùng gói **`GiamSat.zip`** (khoảng 9 MB). Gói có sẵn Python chạy kèm, không cần cài đặt. Các file Python bên trong là bản gốc, có chữ ký số của Python Software Foundation, nên Windows Defender không chặn.

**Lấy gói về máy học sinh**, chọn 1 trong 2 cách:
- **Cách 1, tải từ máy thầy (dễ nhất).** Khi máy thầy đang chạy, học sinh mở Chrome, gõ địa chỉ ghi trên trang theo dõi (dòng *"Tải chương trình giám sát"*, ví dụ `http://192.168.1.5:8765`), rồi bấm **Tải GiamSat.zip**. Nếu Chrome hỏi thì bấm **Giữ lại / Keep**.
- **Cách 2, chép qua USB/Zalo.** Trên trang theo dõi, thầy bấm **⬇ Gói cho học sinh** để lưu `GiamSat.zip`, rồi chép sang các máy.

Cả hai cách đều **ghi sẵn địa chỉ máy thầy** vào gói, học sinh không phải gõ.

**Giải nén** (chỉ làm 1 lần): bấm chuột phải vào `GiamSat.zip` → **Extract All** (Giải nén tất cả) → **Extract**. Được thư mục `GiamSat`, có thể để ra Desktop.

> Máy nào đã cài Python thì cũng có thể chỉ tải 1 file `giamsat.pyw` và bấm đúp vào file đó.

---

## B. Trước giờ thi (mỗi buổi)

1. Máy thầy: bấm đúp `chay_may_thay.bat`. **Không đóng cửa sổ đen này** trong giờ thi.
2. Ghi lên bảng **địa chỉ máy thầy** hiện ở đầu trang theo dõi, ví dụ `192.168.1.5`.
3. Dán link kỳ thi VNOJ vào ô **Link kỳ thi VNOJ** rồi bấm **Lưu link**. Máy học sinh sẽ có nút "Mở trang đề VNOJ".
4. Học sinh mở thư mục `GiamSat` và bấm đúp **`Chay giam sat`**. Nếu Windows hỏi thì bấm **Run / Chạy**.
   - Chương trình kết nối máy thầy. Nếu không được, em gõ địa chỉ trên bảng rồi bấm **Kết nối**.
   - Em chọn tên, nhập mã thầy phát, bấm **Vào làm bài**.
5. Trên trang theo dõi, chờ đủ học sinh có trạng thái **"Đã vào – chờ"**.
6. Bấm **▶ Bắt đầu buổi thi**. Từ lúc này mọi lần rời khỏi chương trình được phép đều bị tính là vi phạm. Chrome trên máy học sinh tự mở trang đề.

## C. Trong giờ thi – đọc trang theo dõi

| Trạng thái | Ý nghĩa |
|---|---|
| 🟢 **Đang làm** | Em đang ở chương trình được phép |
| 🔴 **ĐANG VI PHẠM** | Em đang mở chương trình hoặc trang không được phép |
| 🟠 **Mất tín hiệu** | Hơn 10 giây không nhận được tín hiệu: máy tắt, mất mạng, hoặc chương trình giám sát bị tắt ngang |
| 🟣 **Tự đóng giám sát** | Em tự bấm đóng chương trình giám sát |
| ⚪ **Chưa vào** | Em chưa đăng nhập |

- Cột **Đang mở**: chương trình và tiêu đề cửa sổ em đang dùng ngay lúc này.
- **Bấm vào tên một em** để xem toàn bộ nhật ký của em đó.
- Tích **"Kêu khi có vi phạm"** để máy thầy kêu bíp mỗi khi có vi phạm mới.
- Tích **"Xếp vi phạm lên đầu"** để đưa các em có vấn đề lên trên.
- Một em đổi máy giữa giờ, hoặc bị báo *"Tên này đang được dùng trên máy khác"*: bấm vào tên em → **Cho đăng nhập lại**.

## D. Cuối giờ

1. Bấm **■ Kết thúc**. Máy học sinh báo "Thầy đã kết thúc", các em có thể đóng chương trình.
2. Kết quả **tự lưu** vào thư mục `ketqua\buoi_<ngày>_<giờ>\`:
   - `tonghop.csv`: mỗi em một dòng gồm số lần vi phạm, tổng thời gian vi phạm, số lần mất tín hiệu, các chương trình đã mở…
   - `nhatky.csv`: toàn bộ diễn biến theo thời gian.
   - Hai file mở được bằng Excel. Có thể tải lại bất cứ lúc nào bằng nút **⬇ Tổng hợp** và **⬇ Nhật ký**.
3. Buổi sau, bấm **Buổi thi mới** để xoá trắng bảng. Kết quả buổi cũ vẫn còn trong `ketqua`.

> Nếu lỡ tắt máy thầy giữa giờ: chạy lại `chay_may_thay.bat`. Dữ liệu được lưu liên tục nên không mất. Máy học sinh tự kết nối lại.

---

## E. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Học sinh bấm "Tự tìm máy thầy" không thấy | Gõ địa chỉ máy thầy (ví dụ `192.168.1.5`) rồi bấm **Kết nối** |
| Học sinh gõ đúng địa chỉ vẫn không kết nối được | Máy thầy chưa chạy `mo_tuong_lua.bat` (chạy bằng **Run as administrator**). Kiểm tra máy học sinh và máy thầy có cùng mạng WiFi/LAN không |
| Máy thầy có nhiều địa chỉ | Thử lần lượt các địa chỉ hiện trên trang theo dõi. Thường là địa chỉ bắt đầu bằng `192.168.` |
| Cửa sổ đen báo "Không mở được cổng 8765" | Chương trình máy thầy đang chạy ở một cửa sổ khác. Đóng cửa sổ đó rồi chạy lại |
| Bấm `Chay giam sat` hiện chữ "CHUA GIAI NEN" | Em đang chạy thẳng trong file zip. Chuột phải vào `GiamSat.zip` → **Extract All**, rồi chạy trong thư mục `GiamSat` vừa giải nén |
| Bấm `Chay giam sat` thấy cửa sổ đen chớp rồi tắt | Bình thường. Cửa sổ giám sát sẽ hiện sau 1–3 giây |
| Bấm đúp `giamsat.pyw` không mở (máy có Python) | Chuột phải → **Open with** → **Python**, hoặc dùng gói `GiamSat.zip` |
| Báo "Sai mã vào bài" | Kiểm tra lại mã. Sai 5 lần liên tiếp sẽ bị khoá 60 giây |
| Bảng hiện "Giám sát bị sửa/khác bản" | File `giamsat.pyw` của em khác bản của thầy: bị sửa, hoặc là bản cũ. Cho em tải lại `GiamSat.zip` từ máy thầy |
| Muốn cho phép thêm chương trình (ví dụ Dev-C++) | Xem mục F |

## F. Sửa danh sách chương trình được phép (`quydinh.json`)

Mở `quydinh.json` bằng Notepad. Ví dụ, để cho phép **Dev-C++**, thêm vào mục `chuong_trinh_duoc_phep`:

```json
{"ten": "Dev-C++", "tien_trinh": ["devcpp.exe"]},
```

Để cho phép thêm trang web trong Chrome, thêm một chữ có trong tiêu đề trang vào `tieu_de_phai_chua`.

Lưu file rồi bấm **Tải lại quy định** trên trang theo dõi. Máy học sinh tự cập nhật sau vài giây, không cần khởi động lại.

Tên tiến trình (`.exe`) của một chương trình: mở **Task Manager** → tab **Details**.

---

## G. Nên biết

- Đây là chương trình **giám sát và cảnh báo**, không khoá cứng máy. Học sinh vẫn có thể mở chương trình khác, nhưng mọi lần đều bị ghi lại và báo cho thầy.
- Nếu em tắt chương trình giám sát hoặc tắt mạng, thầy thấy ngay trạng thái **Mất tín hiệu** hoặc **Tự đóng giám sát**.
- Trang theo dõi và các nút điều khiển **chỉ mở được trên chính máy thầy** (`http://localhost:8765`). Học sinh gõ địa chỉ máy thầy chỉ thấy trang tải chương trình.
- Chrome được nhận là "đang ở VNOJ" dựa vào **tiêu đề trang** có chữ "VNOJ" hoặc "VNOI".
