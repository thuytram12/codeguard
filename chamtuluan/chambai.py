# -*- coding: utf-8 -*-
"""
Chấm Tự Luận – chấm bài kiểm tra tự luận viết tay bằng AI (Claude).

Chạy trên máy thầy/cô:  python chambai.py
Trình duyệt sẽ tự mở trang http://127.0.0.1:8800

Cần: Python 3.9+, thư viện anthropic (chay.bat tự cài), khoá API của Anthropic.
"""
import base64
import datetime
import io
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

try:
    import anthropic
except ImportError:  # vẫn mở được giao diện, chỉ báo lỗi khi chấm
    anthropic = None

THU_MUC = os.path.dirname(os.path.abspath(__file__))
DU_LIEU = os.path.join(THU_MUC, 'dulieu')
CAU_HINH = os.path.join(THU_MUC, 'cauhinh.json')
TRANG = os.path.join(THU_MUC, 'trang.html')
CONG = 8800
SO_LUONG_CHAM_CUNG_LUC = 3

MO_HINH = 'claude-opus-5-5'
DO_KY = 'high'  # mức suy nghĩ khi chấm: low | medium | high | xhigh | max

KIEU_TEP = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
    'image/gif': '.gif', 'application/pdf': '.pdf',
}

khoa = threading.RLock()
hang_doi = queue.Queue()


# ---------------------------------------------------------------- tiện ích

def bay_gio():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def ma_moi():
    return uuid.uuid4().hex[:10]


def an_toan_id(s):
    if not s or not re.fullmatch(r'[0-9a-f]{10}', s):
        raise ValueError('Mã không hợp lệ')
    return s


def doc_json(duong_dan, mac_dinh=None):
    try:
        with open(duong_dan, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return mac_dinh


def ghi_json(duong_dan, du_lieu):
    os.makedirs(os.path.dirname(duong_dan), exist_ok=True)
    tam = duong_dan + '.tam'
    with open(tam, 'w', encoding='utf-8') as f:
        json.dump(du_lieu, f, ensure_ascii=False, indent=1)
    os.replace(tam, duong_dan)


def lam_tron(x, buoc=0.25):
    return round(round(float(x) / buoc) * buoc, 2)


def tm_de(de_id):
    return os.path.join(DU_LIEU, an_toan_id(de_id))


def tm_bai(de_id, bai_id):
    return os.path.join(tm_de(de_id), 'bai', an_toan_id(bai_id))


def doc_de(de_id):
    return doc_json(os.path.join(tm_de(de_id), 'de.json'))


def doc_bai(de_id, bai_id):
    return doc_json(os.path.join(tm_bai(de_id, bai_id), 'bai.json'))


def ghi_bai(bai):
    ghi_json(os.path.join(tm_bai(bai['de_id'], bai['id']), 'bai.json'), bai)


def ds_bai(de_id):
    goc = os.path.join(tm_de(de_id), 'bai')
    kq = []
    if os.path.isdir(goc):
        for ten in os.listdir(goc):
            b = doc_json(os.path.join(goc, ten, 'bai.json'))
            if b:
                kq.append(b)
    kq.sort(key=lambda b: (b.get('stt', 0), b.get('tao_luc', '')))
    return kq


def luu_tep(thu_muc, ten_goc, tep):
    """tep = {mime, data(base64)} -> trả về tên file đã lưu."""
    mime = tep.get('mime', '')
    if mime not in KIEU_TEP:
        raise ValueError('Chỉ nhận ảnh JPG/PNG/WEBP/GIF hoặc PDF')
    du_lieu = base64.b64decode(tep['data'])
    if len(du_lieu) > 30 * 1024 * 1024:
        raise ValueError('Tệp quá lớn (tối đa 30 MB)')
    os.makedirs(thu_muc, exist_ok=True)
    ten = ten_goc + KIEU_TEP[mime]
    with open(os.path.join(thu_muc, ten), 'wb') as f:
        f.write(du_lieu)
    return {'ten': ten, 'mime': mime}


def khoi_noi_dung(duong_dan, mime):
    with open(duong_dan, 'rb') as f:
        b64 = base64.standard_b64encode(f.read()).decode('ascii')
    if mime == 'application/pdf':
        return {'type': 'document',
                'source': {'type': 'base64', 'media_type': mime, 'data': b64}}
    return {'type': 'image',
            'source': {'type': 'base64', 'media_type': mime, 'data': b64}}


def lay_khoa_api():
    k = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if k:
        return k
    return (doc_json(CAU_HINH, {}) or {}).get('api_key', '').strip()


# ---------------------------------------------------------------- chấm bài

HUONG_DAN = """Bạn là giáo viên chấm bài kiểm tra tự luận cho học sinh phổ thông Việt Nam.
Bạn nhận: đề bài, đáp án/thang điểm của giáo viên, rồi ảnh (hoặc PDF) bài làm viết tay của một học sinh.

Cách chấm:
- Đọc kỹ chữ viết tay. Chép lại phần bài làm của từng câu đúng như học sinh viết (kể cả chỗ sai), công thức toán viết bằng LaTeX đặt trong $...$. Chỗ không đọc được thì ghi [không đọc được].
- Chấm theo thang điểm của giáo viên. Nếu thang điểm chia ý thì chấm từng ý.
- Cách giải khác đáp án nhưng đúng và chặt chẽ vẫn được đủ điểm tương ứng.
- Bước sau dùng kết quả sai của bước trước thì không cho điểm phần kết quả đó, nhưng vẫn cho điểm phương pháp nếu thang điểm có tách điểm phương pháp.
- Chỉ có đáp số mà không có lập luận khi đề yêu cầu trình bày: cho điểm theo thang điểm, nếu thang điểm không nói thì chỉ cho phần điểm của đáp số.
- Không trừ điểm vì chữ xấu hay lỗi chính tả, trừ khi làm sai ý toán học.
- Điểm mỗi câu là bội của 0,25 và không vượt quá điểm tối đa của câu. Câu bỏ trống được 0 điểm.
- Nhận xét ngắn gọn, cụ thể, viết cho học sinh đọc: đúng ở đâu, sai ở bước nào, vì sao mất điểm.
- Ảnh mờ, thiếu trang, lẫn bài của người khác, hoặc bạn không chắc về cách cho điểm: đặt do_tin_cay thấp và ghi lý do vào can_xem_lai. Nếu không có gì cần xem lại thì can_xem_lai là chuỗi rỗng.
- Ghi họ tên học sinh nếu thấy trên bài, không thấy thì để chuỗi rỗng.
Trả lời bằng tiếng Việt."""

LUOC_DO = {
    'type': 'object',
    'properties': {
        'hoten_tren_bai': {'type': 'string'},
        'cau': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'so': {'type': 'string', 'description': 'Số câu, đúng như trong đề, vd "1", "2a"'},
                    'chep_lai': {'type': 'string'},
                    'cac_y': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'y': {'type': 'string'},
                                'diem': {'type': 'number'},
                                'toi_da': {'type': 'number'},
                                'nhan_xet': {'type': 'string'},
                            },
                            'required': ['y', 'diem', 'toi_da', 'nhan_xet'],
                            'additionalProperties': False,
                        },
                    },
                    'diem': {'type': 'number'},
                    'nhan_xet': {'type': 'string'},
                },
                'required': ['so', 'chep_lai', 'cac_y', 'diem', 'nhan_xet'],
                'additionalProperties': False,
            },
        },
        'nhan_xet_chung': {'type': 'string'},
        'do_tin_cay': {'type': 'string', 'enum': ['cao', 'trung_binh', 'thap']},
        'can_xem_lai': {'type': 'string'},
    },
    'required': ['hoten_tren_bai', 'cau', 'nhan_xet_chung', 'do_tin_cay', 'can_xem_lai'],
    'additionalProperties': False,
}


def van_ban_de(de):
    dong = [f"ĐỀ KIỂM TRA: {de.get('ten', '')}",
            f"Môn: {de.get('mon', '')}   Lớp: {de.get('lop', '')}",
            f"Tổng điểm: {tong_toi_da(de)}", '']
    for c in de.get('cau', []):
        dong.append(f"=== Câu {c['so']} ({c['diem']} điểm) ===")
        if c.get('noidung'):
            dong.append('Đề: ' + c['noidung'])
        if c.get('dapan'):
            dong.append('Đáp án và thang điểm:\n' + c['dapan'])
        dong.append('')
    if de.get('ghichu'):
        dong.append('Lưu ý của giáo viên khi chấm:\n' + de['ghichu'])
    if de.get('tep'):
        dong.append('(Đề/đáp án gốc của giáo viên kèm ở các tệp trên.)')
    return '\n'.join(dong)


def chuan_so(s):
    s = str(s).strip().lower()
    s = re.sub(r'^(câu|cau|bài|bai)\s*', '', s)
    return re.sub(r'[\s.:)]+$', '', s).replace(' ', '')


def tong_toi_da(de):
    return lam_tron(sum(float(c.get('diem', 0)) for c in de.get('cau', [])), 0.01)


def cham_mot_bai(de_id, bai_id):
    de = doc_de(de_id)
    bai = doc_bai(de_id, bai_id)
    if not de or not bai:
        return
    bai['trang_thai'] = 'dang_cham'
    bai['loi'] = ''
    ghi_bai(bai)

    try:
        if anthropic is None:
            raise RuntimeError('Chưa cài thư viện anthropic. Chạy lại chay.bat để cài tự động.')
        api_key = lay_khoa_api()
        if not api_key:
            raise RuntimeError('Chưa nhập khoá API. Bấm ⚙ Cài đặt ở góc trên trang.')
        client = anthropic.Anthropic(api_key=api_key, max_retries=4)

        # Phần đề + đáp án: giống nhau cho mọi bài của cùng đề -> đặt trước để dùng bộ nhớ đệm.
        noi_dung = []
        for t in de.get('tep', []):
            noi_dung.append(khoi_noi_dung(os.path.join(tm_de(de_id), 'tep', t['ten']), t['mime']))
        noi_dung.append({'type': 'text', 'text': van_ban_de(de),
                         'cache_control': {'type': 'ephemeral'}})
        # Phần bài làm của học sinh.
        noi_dung.append({'type': 'text', 'text': f"BÀI LÀM CỦA HỌC SINH ({len(bai['trang'])} trang, theo thứ tự):"})
        for i, t in enumerate(bai['trang'], 1):
            noi_dung.append({'type': 'text', 'text': f'Trang {i}:'})
            noi_dung.append(khoi_noi_dung(os.path.join(tm_bai(de_id, bai_id), t['ten']), t['mime']))
        noi_dung.append({'type': 'text', 'text': 'Hãy chấm bài làm này. Trả kết quả cho đủ mọi câu trong đề, đúng thứ tự trong đề.'})

        bat_dau = time.time()
        with client.beta.messages.stream(
            model=MO_HINH,
            max_tokens=64000,
            system=HUONG_DAN,
            messages=[{'role': 'user', 'content': noi_dung}],
            output_config={'effort': DO_KY,
                           'format': {'type': 'json_schema', 'schema': LUOC_DO}},
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
        ) as stream:
            tra_loi = stream.get_final_message()

        if tra_loi.stop_reason == 'refusal':
            raise RuntimeError('AI từ chối chấm bài này. Thầy/cô vui lòng chấm tay.')
        if tra_loi.stop_reason == 'max_tokens':
            raise RuntimeError('Câu trả lời của AI bị cắt giữa chừng. Bấm Chấm lại.')
        van_ban = next((b.text for b in tra_loi.content if b.type == 'text'), '')
        kq = json.loads(van_ban)

        # Chuẩn hoá điểm: bội 0,25, không vượt điểm tối đa của câu.
        cau_de = {chuan_so(c['so']): c for c in de.get('cau', [])}
        for c in kq['cau']:
            goc = cau_de.get(chuan_so(c['so']))
            d = max(0.0, lam_tron(c.get('diem', 0)))
            if goc is not None:
                c['so'] = goc['so']
                c['toi_da'] = float(goc['diem'])
                d = min(d, c['toi_da'])
            c['diem'] = d
        kq['tong_diem'] = lam_tron(sum(c['diem'] for c in kq['cau']), 0.01)

        u = tra_loi.usage
        bai['ket_qua'] = kq
        bai['trang_thai'] = 'xong'
        bai['cham_luc'] = bay_gio()
        bai['thong_ke'] = {
            'giay': round(time.time() - bat_dau, 1),
            'mo_hinh': tra_loi.model,
            'token_vao': (u.input_tokens or 0) + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
            'token_ra': u.output_tokens,
        }
        if not bai.get('hoten') and kq.get('hoten_tren_bai'):
            bai['hoten'] = kq['hoten_tren_bai'].strip()
    except Exception as e:  # noqa: BLE001 – mọi lỗi đều hiện cho thầy/cô thấy
        bai['trang_thai'] = 'loi'
        bai['loi'] = mo_ta_loi(e)
    ghi_bai(bai)


def mo_ta_loi(e):
    if anthropic is not None:
        if isinstance(e, anthropic.AuthenticationError):
            return 'Khoá API không đúng. Kiểm tra lại trong ⚙ Cài đặt.'
        if isinstance(e, anthropic.PermissionDeniedError):
            return 'Khoá API không có quyền dùng mô hình này.'
        if isinstance(e, anthropic.BadRequestError):
            return 'Yêu cầu không hợp lệ (có thể ảnh/PDF quá lớn hoặc hết tiền trong tài khoản): ' + str(e.message)[:300]
        if isinstance(e, anthropic.RateLimitError):
            return 'Gửi quá nhiều bài cùng lúc. Chờ một lát rồi bấm Chấm lại.'
        if isinstance(e, anthropic.APIStatusError):
            return f'Máy chủ AI báo lỗi {e.status_code}. Thử lại sau.'
        if isinstance(e, anthropic.APIConnectionError):
            return 'Không kết nối được Internet tới máy chủ AI.'
    if isinstance(e, (ValueError, KeyError)):
        return 'Kết quả AI trả về không đọc được. Bấm Chấm lại.'
    return str(e)[:300]


def tho_cham():
    while True:
        de_id, bai_id = hang_doi.get()
        try:
            cham_mot_bai(de_id, bai_id)
        except Exception as e:  # noqa: BLE001
            print('Lỗi khi chấm:', e, file=sys.stderr)
        finally:
            hang_doi.task_done()


def xep_hang_cham(de_id, bai_id):
    with khoa:
        bai = doc_bai(de_id, bai_id)
        if not bai or bai.get('trang_thai') in ('cho_cham', 'dang_cham'):
            return
        bai['trang_thai'] = 'cho_cham'
        bai['loi'] = ''
        ghi_bai(bai)
    hang_doi.put((de_id, bai_id))


# ---------------------------------------------------------------- xuất Excel (.xlsx, không cần thư viện)

def _o(cot, hang):
    s = ''
    cot += 1
    while cot:
        cot, r = divmod(cot - 1, 26)
        s = chr(65 + r) + s
    return f'{s}{hang}'


def _xml(s):
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(s))
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def tao_xlsx(cac_hang, ten_trang='Ket qua'):
    hang_xml = []
    for r, hang in enumerate(cac_hang, 1):
        o = []
        for c, gt in enumerate(hang):
            ref = _o(c, r)
            kieu = ' s="1"' if r == 1 else ''
            if isinstance(gt, (int, float)) and not isinstance(gt, bool):
                o.append(f'<c r="{ref}"{kieu}><v>{gt}</v></c>')
            elif gt not in (None, ''):
                o.append(f'<c r="{ref}" t="inlineStr"{kieu}><is><t xml:space="preserve">{_xml(gt)}</t></is></c>')
        hang_xml.append(f'<row r="{r}">{"".join(o)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews>'
             '<cols><col min="1" max="1" width="5"/><col min="2" max="2" width="28"/></cols>'
             f'<sheetData>{"".join(hang_xml)}</sheetData></worksheet>')
    tep = {
        '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{_xml(ten_trang)}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf/><xf fontId="1" applyFont="1"/></cellXfs></styleSheet>',
        'xl/worksheets/sheet1.xml': sheet,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for ten, nd in tep.items():
            z.writestr(ten, nd)
    return out.getvalue()


def bang_ket_qua(de_id):
    de = doc_de(de_id)
    cau = [str(c['so']) for c in de.get('cau', [])]
    hang = [['STT', 'Họ và tên'] + [f'Câu {s}' for s in cau] + ['Tổng điểm', 'Cần xem lại', 'Nhận xét chung']]
    for i, b in enumerate(ds_bai(de_id), 1):
        kq = b.get('ket_qua') or {}
        diem = {chuan_so(c['so']): c['diem'] for c in kq.get('cau', [])}
        dong = [i, b.get('hoten') or '(chưa rõ tên)']
        dong += [diem.get(chuan_so(s), '') for s in cau]
        if b.get('trang_thai') == 'xong':
            dong += [kq.get('tong_diem', ''), kq.get('can_xem_lai', ''), kq.get('nhan_xet_chung', '')]
        else:
            dong += ['', 'Chưa chấm xong' if b.get('trang_thai') != 'loi' else 'Lỗi: ' + b.get('loi', ''), '']
        hang.append(dong)
    return hang


# ---------------------------------------------------------------- máy chủ web

class XuLy(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def gui(self, ma, kieu, noi_dung, them=None):
        if isinstance(noi_dung, str):
            noi_dung = noi_dung.encode('utf-8')
        self.send_response(ma)
        self.send_header('Content-Type', kieu)
        self.send_header('Content-Length', str(len(noi_dung)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (them or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(noi_dung)

    def json(self, du_lieu, ma=200):
        self.gui(ma, 'application/json; charset=utf-8', json.dumps(du_lieu, ensure_ascii=False))

    def doc_than(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 200 * 1024 * 1024:
            raise ValueError('Dữ liệu gửi lên quá lớn')
        return json.loads(self.rfile.read(n) or b'{}')

    def phan(self):
        return [unquote(x) for x in urlparse(self.path).path.strip('/').split('/') if x]

    def _bao_loi(self, fn):
        try:
            fn()
        except ValueError as e:
            self.json({'loi': str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            self.json({'loi': 'Lỗi máy chủ: ' + str(e)}, 500)

    def do_GET(self):
        self._bao_loi(self._get)

    def do_POST(self):
        self._bao_loi(self._post)

    def do_DELETE(self):
        self._bao_loi(self._delete)

    # ---- GET
    def _get(self):
        p = self.phan()
        if not p:
            with open(TRANG, 'rb') as f:
                return self.gui(200, 'text/html; charset=utf-8', f.read())
        if p == ['api', 'caidat']:
            k = lay_khoa_api()
            return self.json({'co_khoa': bool(k), 'duoi_khoa': k[-4:] if k else '',
                              'tu_bien_moi_truong': bool(os.environ.get('ANTHROPIC_API_KEY')),
                              'co_thu_vien': anthropic is not None, 'mo_hinh': MO_HINH})
        if p == ['api', 'de']:
            ds = []
            if os.path.isdir(DU_LIEU):
                for ten in os.listdir(DU_LIEU):
                    d = doc_json(os.path.join(DU_LIEU, ten, 'de.json'))
                    if d:
                        bs = ds_bai(d['id'])
                        d['so_bai'] = len(bs)
                        d['so_xong'] = sum(1 for b in bs if b.get('trang_thai') == 'xong')
                        ds.append(d)
            ds.sort(key=lambda d: d.get('tao_luc', ''), reverse=True)
            return self.json(ds)
        if len(p) == 3 and p[:2] == ['api', 'de']:
            de = doc_de(p[2])
            if not de:
                return self.json({'loi': 'Không tìm thấy đề'}, 404)
            de['tong'] = tong_toi_da(de)
            de['bai'] = ds_bai(p[2])
            return self.json(de)
        if len(p) == 4 and p[:2] == ['api', 'de'] and p[3] == 'ketqua.xlsx':
            de = doc_de(p[2])
            ten = re.sub(r'[^\w\-]+', '_', de.get('ten', 'ketqua'), flags=re.UNICODE)[:40]
            ten_tep = f"ketqua_{ten}_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx"
            return self.gui(200, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            tao_xlsx(bang_ket_qua(p[2])),
                            {'Content-Disposition': "attachment; filename=\"ketqua.xlsx\"; filename*=UTF-8''" + ten_tep})
        if len(p) == 5 and p[:2] == ['api', 'tep']:
            # /api/tep/<de>/<bai hoặc "de">/<tên>
            de_id, bai_id, ten = p[2], p[3], p[4]
            if not re.fullmatch(r'[\w\-]+\.(jpg|png|webp|gif|pdf)', ten):
                raise ValueError('Tên tệp không hợp lệ')
            thu_muc = os.path.join(tm_de(de_id), 'tep') if bai_id == 'de' else tm_bai(de_id, bai_id)
            duong = os.path.join(thu_muc, ten)
            if not os.path.isfile(duong):
                return self.json({'loi': 'Không có tệp'}, 404)
            mime = next((m for m, d in KIEU_TEP.items() if ten.endswith(d)), 'application/octet-stream')
            with open(duong, 'rb') as f:
                return self.gui(200, mime, f.read())
        self.json({'loi': 'Không có trang này'}, 404)

    # ---- POST
    def _post(self):
        p = self.phan()
        d = self.doc_than()
        if p == ['api', 'caidat']:
            k = (d.get('api_key') or '').strip()
            if k and not k.startswith('sk-ant-'):
                raise ValueError('Khoá API phải bắt đầu bằng sk-ant-')
            ch = doc_json(CAU_HINH, {}) or {}
            ch['api_key'] = k
            ghi_json(CAU_HINH, ch)
            return self.json({'ok': True})
        if p == ['api', 'de']:
            return self.json(self.luu_de(d))
        if len(p) == 4 and p[:2] == ['api', 'de'] and p[3] == 'bai':
            return self.json(self.them_bai(p[2], d))
        if len(p) == 4 and p[:2] == ['api', 'de'] and p[3] == 'chamtatca':
            n = 0
            for b in ds_bai(p[2]):
                if b.get('trang_thai') in ('moi', 'loi') or (d.get('cham_lai') and b.get('trang_thai') == 'xong'):
                    xep_hang_cham(p[2], b['id'])
                    n += 1
            return self.json({'so_bai': n})
        if len(p) == 5 and p[:2] == ['api', 'bai'] and p[4] == 'cham':
            xep_hang_cham(p[2], an_toan_id(p[3]))
            return self.json({'ok': True})
        if len(p) == 5 and p[:2] == ['api', 'bai'] and p[4] == 'sua':
            with khoa:
                b = doc_bai(p[2], an_toan_id(p[3]))
                if not b:
                    return self.json({'loi': 'Không tìm thấy bài'}, 404)
                if 'hoten' in d:
                    b['hoten'] = str(d['hoten']).strip()[:100]
                ghi_bai(b)
            return self.json({'ok': True})
        self.json({'loi': 'Không có chức năng này'}, 404)

    def luu_de(self, d):
        with khoa:
            de_id = d.get('id') or ma_moi()
            cu = doc_de(de_id) if d.get('id') else None
            cau = []
            for c in d.get('cau', []):
                so = str(c.get('so', '')).strip()
                if not so:
                    continue
                try:
                    diem = float(str(c.get('diem', 0)).replace(',', '.'))
                except ValueError:
                    raise ValueError(f'Điểm câu {so} không phải là số')
                cau.append({'so': so, 'diem': diem,
                            'noidung': str(c.get('noidung', '')).strip(),
                            'dapan': str(c.get('dapan', '')).strip()})
            if not cau:
                raise ValueError('Đề phải có ít nhất 1 câu')
            if len({c['so'].lower() for c in cau}) != len(cau):
                raise ValueError('Có hai câu trùng số')
            de = {
                'id': de_id,
                'ten': str(d.get('ten', '')).strip() or 'Đề không tên',
                'mon': str(d.get('mon', '')).strip() or 'Toán',
                'lop': str(d.get('lop', '')).strip(),
                'ghichu': str(d.get('ghichu', '')).strip(),
                'cau': cau,
                'tep': (cu or {}).get('tep', []),
                'tao_luc': (cu or {}).get('tao_luc', bay_gio()),
                'sua_luc': bay_gio(),
            }
            thu_muc_tep = os.path.join(tm_de(de_id), 'tep')
            giu = set(d.get('giu_tep', [t['ten'] for t in de['tep']]))
            for t in list(de['tep']):
                if t['ten'] not in giu:
                    de['tep'].remove(t)
                    try:
                        os.remove(os.path.join(thu_muc_tep, t['ten']))
                    except OSError:
                        pass
            for t in d.get('tep_moi', []):
                de['tep'].append(luu_tep(thu_muc_tep, 'tep_' + ma_moi(), t))
            ghi_json(os.path.join(tm_de(de_id), 'de.json'), de)
            return de

    def them_bai(self, de_id, d):
        if not doc_de(de_id):
            raise ValueError('Không tìm thấy đề')
        trang = d.get('trang') or []
        if not trang:
            raise ValueError('Chưa chọn ảnh bài làm')
        if len(trang) > 20:
            raise ValueError('Mỗi bài tối đa 20 trang')
        with khoa:
            bai_id = ma_moi()
            thu_muc = tm_bai(de_id, bai_id)
            luu = [luu_tep(thu_muc, f'trang_{i:02d}', t) for i, t in enumerate(trang, 1)]
            stt = max([b.get('stt', 0) for b in ds_bai(de_id)] + [0]) + 1
            bai = {'id': bai_id, 'de_id': de_id, 'stt': stt,
                   'hoten': str(d.get('hoten', '')).strip()[:100],
                   'trang': luu, 'trang_thai': 'moi', 'loi': '',
                   'tao_luc': bay_gio(), 'ket_qua': None}
            ghi_bai(bai)
        if d.get('cham_ngay', True):
            xep_hang_cham(de_id, bai_id)
        return bai

    # ---- DELETE
    def _delete(self):
        p = self.phan()
        if len(p) == 3 and p[:2] == ['api', 'de']:
            with khoa:
                shutil.rmtree(tm_de(p[2]), ignore_errors=True)
            return self.json({'ok': True})
        if len(p) == 4 and p[:2] == ['api', 'bai']:
            with khoa:
                b = doc_bai(p[2], an_toan_id(p[3]))
                if b and b.get('trang_thai') == 'dang_cham':
                    raise ValueError('Bài đang được chấm, chờ xong rồi xoá')
                shutil.rmtree(tm_bai(p[2], p[3]), ignore_errors=True)
            return self.json({'ok': True})
        self.json({'loi': 'Không có chức năng này'}, 404)


def khoi_phuc_hang_doi():
    """Bài đang chờ/đang chấm khi tắt máy lần trước -> đưa lại vào hàng đợi."""
    if not os.path.isdir(DU_LIEU):
        return
    for ten in os.listdir(DU_LIEU):
        if not re.fullmatch(r'[0-9a-f]{10}', ten):
            continue
        for b in ds_bai(ten):
            if b.get('trang_thai') in ('cho_cham', 'dang_cham'):
                b['trang_thai'] = 'cho_cham'
                ghi_bai(b)
                hang_doi.put((ten, b['id']))


def main():
    os.makedirs(DU_LIEU, exist_ok=True)
    for _ in range(SO_LUONG_CHAM_CUNG_LUC):
        threading.Thread(target=tho_cham, daemon=True).start()
    khoi_phuc_hang_doi()
    may_chu = ThreadingHTTPServer(('127.0.0.1', CONG), XuLy)
    dia_chi = f'http://127.0.0.1:{CONG}'
    print('=' * 60)
    print(' CHẤM TỰ LUẬN đang chạy tại', dia_chi)
    print(' Không đóng cửa sổ này khi đang chấm bài.')
    print('=' * 60)
    if anthropic is None:
        print('! Chưa cài thư viện anthropic: chạy  pip install anthropic')
    if '--khong-mo' not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(dia_chi)).start()
    try:
        may_chu.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
