# Ghi chú dự án (Claude đọc file này đầu mỗi phiên)

Người dùng: giáo viên ở Việt Nam, dùng máy Windows, không phải lập trình viên. Trao đổi bằng tiếng Việt,
gọi là "thầy/cô". Giải thích đơn giản, đưa số liệu cụ thể, nói rõ chỗ nào chưa kiểm chứng.
Thích trao đổi kỹ trước khi làm: khi người dùng nói "trao đổi đã" thì không sửa code.

Repo có 2 app độc lập:
- **CodeGuard** (thư mục gốc): giám sát phòng thi Tin học qua mạng LAN. Đã xong, ít động tới.
- **Chấm Tự Luận** (`chamtuluan/`): chấm bài tự luận viết tay bằng Claude. **Dự án đang làm.**

## Chấm Tự Luận: cấu trúc

- `chambai.py`: máy chủ web (stdlib `http.server`, chỉ nghe 127.0.0.1:8800) + gọi Claude. Thư viện: `anthropic`, `pillow` (che tên).
- `trang.html`: giao diện một trang, JS thuần, KaTeX và pdf.js từ cdnjs.
- `chay.bat`: tự cài thư viện rồi chạy. `README.md`: hướng dẫn cho giáo viên.
- Dữ liệu ở `dulieu/<de_id>/de.json` và `dulieu/<de_id>/bai/<bai_id>/bai.json` + ảnh. Khoá API và "thói quen chấm" ở `cauhinh.json`. Cả hai bị gitignore.
- Gọi API: `client.beta.messages.stream`, model `claude-opus-5-5`, effort `high`, structured output (`LUOC_DO`),
  `fallbacks="default"` + beta `server-side-fallback-2026-07-01`. Đề + đáp án đặt đầu, có `cache_control`.
- Điểm AI được làm tròn 0,25 và giới hạn theo điểm tối đa từng câu. Số câu được chuẩn hoá bằng `chuan_so()`.
- Bài có `ket_qua` (AI) và `duyet` (giáo viên). Điểm chính thức = `duyet` nếu có. Kết quả AI được ghép vào bản đọc lại từ đĩa, nên không ghi đè thay đổi giáo viên làm trong lúc AI đang chấm.

## Tính năng đã có

Soạn đề (câu, điểm, đáp án, *dạng bài*, tệp đề/đáp án) · tải ảnh/PDF (PDF tách thành ảnh trong trình duyệt) ·
AI chấm 3 bài song song · giáo viên duyệt và sửa TeX, điểm, nhận xét · **bài mẫu**: tối đa 4 bài đã duyệt cùng đề + câu cùng dạng ở đề khác
(3 câu/dạng, tối đa 12), chỉ gửi chữ · thói quen chấm chung · thống kê độ sát AI so với giáo viên ·
che vùng tên trên ảnh (Pillow, toạ độ tỉ lệ) · lấy tên từ tên tệp · xuất Excel (.xlsx tự tạo, không cần thư viện) ·
xuất dữ liệu đã duyệt (zip, ẩn danh) để huấn luyện sau này.

## Quyết định đã chốt (kèm lý do)

- **Không tự huấn luyện AI lúc này.** Chọn "mức 3": dạy bằng bài mẫu + tích luỹ dữ liệu.
  Sau 1–2 năm, khi có vài nghìn bài đã duyệt, mới cân nhắc huấn luyện mô hình mở, bắt đầu với phần đọc chữ viết tay.
- **Chưa chuyển ảnh sang TeX trước khi chấm.** Chỉ giảm khoảng 10–25% chi phí, vì đầu ra (AI suy nghĩ) chiếm phần lớn tiền.
  OCR chạy trên máy kém với chữ viết tay và hình vẽ. Gửi PDF không rẻ hơn ảnh. Nếu làm thì làm 2 bước trong app:
  Haiku đọc ra TeX → giáo viên sửa → Opus chấm trên TeX.
- Cách giảm tiền nên làm trước: **chấm theo lô (Batch API, −50%)**, thang điểm rõ ràng. Hạ mức suy nghĩ thì cân nhắc vì dễ làm giảm chất lượng.
- Dữ liệu học sinh: che tên, ẩn danh khi xuất, nhắc Nghị định 13/2023/NĐ-CP.

## Trạng thái (cập nhật 27/11/2026)

- Code đã gộp vào `main` (PR #3, #4). Mới kiểm thử bằng client AI giả + Playwright.
- **Chưa chạy với khoá API thật, chưa chạy `chay.bat` trên Windows.** Chưa biết độ chính xác và chi phí thật.
- Giáo viên sẽ chạy thử trên 10–20 bài đã chấm tay, rồi báo lỗi, độ lệch và chi phí.

## Việc tiếp theo

1. Sửa lỗi từ lần chạy thử thật (ưu tiên số 1).
2. Theo kết quả thử: nếu AI lệch nhiều thì cải thiện chất lượng chấm (chấm 2 lần để gắn cờ, chấm theo câu cả lớp).
3. Khớp tên với danh sách lớp. Tách xấp bài scan thành từng bài (có thể dùng mã QR trên giấy làm bài).
4. Chấm theo lô (Batch API). Phiếu nhận xét học sinh. Thống kê lỗi sai phổ biến.

## Quy ước làm việc

- Kiểm thử bằng client giả (monkeypatch `chambai.anthropic.Anthropic`) + Playwright. CDN bị chặn trong container:
  dùng `npm i katex@0.16.9 pdfjs-dist@3.11.174` rồi `page.route` để phục vụ bản cài từ npm.
- Commit message tiếng Việt. Tạo PR khi người dùng yêu cầu, người dùng tự gộp.
- Cuối buổi, khi người dùng yêu cầu, cập nhật mục "Trạng thái" và "Việc tiếp theo" trong file này.
