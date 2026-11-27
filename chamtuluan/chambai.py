# -*- coding: utf-8 -*-
"""
Chấm Tự Luận – chấm bài kiểm tra tự luận viết tay bằng AI (Claude).

Chạy trên máy thầy/cô:  python chambai.py
Trình duyệt sẽ tự mở trang http://127.0.0.1:8800

Cần: Python 3.9+, thư viện anthropic (chay.bat tự cài), khoá API của Anthropic.
"""
import base64
import datetime
import hashlib
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
from urllib.parse import parse_qs, unquote, urlparse

try:
    import anthropic
except ImportError:  # vẫn mở được giao diện, chỉ báo lỗi khi chấm
    anthropic = None
try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:  # chỉ cần khi dùng chức năng che tên
    Image = None

THU_MUC = os.path.dirname(os.path.abspath(__file__))
DU_LIEU = os.path.join(THU_MUC, 'dulieu')
CAU_HINH = os.path.join(THU_MUC, 'cauhinh.json')
TRANG = os.path.join(THU_MUC, 'trang.html')
CONG = 8800
SO_LUONG_CHAM_CUNG_LUC = 3
SO_BAI_MAU = 4  # số bài giáo viên đã duyệt (cùng đề) gửi kèm làm mẫu khi chấm
SO_VI_DU_MOI_DANG = 3  # số câu mẫu lấy từ đề khác có cùng dạng bài, cho mỗi câu
SO_VI_DU_TOI_DA = 12  # tổng số câu mẫu từ đề khác trong một lần chấm

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


def khoi_noi_dung(duong_dan, mime, du_lieu=None):
    if du_lieu is None:
        with open(duong_dan, 'rb') as f:
            du_lieu = f.read()
    b64 = base64.standard_b64encode(du_lieu).decode('ascii')
    if mime == 'application/pdf':
        return {'type': 'document',
                'source': {'type': 'base64', 'media_type': mime, 'data': b64}}
    return {'type': 'image',
            'source': {'type': 'base64', 'media_type': mime, 'data': b64}}


def can_che(de, chi_so_trang):
    """Trang thứ chi_so_trang (tính từ 0) của bài có phải che tên không."""
    return bool(de.get('vung_che')) and (chi_so_trang == 0 or de.get('che_moi_trang'))


def anh_da_che(de, duong_dan, mime, chi_so_trang):
    """Trả về (bytes, mime) của trang đã che vùng ghi tên; None nếu trang này không cần che."""
    if not can_che(de, chi_so_trang):
        return None
    if mime == 'application/pdf':
        raise RuntimeError('Bài này tải lên dạng PDF từ phiên bản cũ nên không che tên được. '
                           'Hãy xoá bài và tải lại (app sẽ tự tách PDF thành ảnh).')
    if Image is None:
        raise RuntimeError('Chức năng che tên cần thư viện pillow. Chạy lại chay.bat để cài tự động.')
    im = ImageOps.exif_transpose(Image.open(duong_dan)).convert('RGB')
    w, h = im.size
    ve = ImageDraw.Draw(im)
    for v in de['vung_che']:
        ve.rectangle([v['x'] * w, v['y'] * h, (v['x'] + v['w']) * w, (v['y'] + v['h']) * h], fill='black')
    out = io.BytesIO()
    im.save(out, 'JPEG', quality=88)
    return out.getvalue(), 'image/jpeg'


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


def chuan_vung_che(ds):
    kq = []
    for v in (ds or [])[:10]:
        try:
            x, y, w, h = (min(1.0, max(0.0, float(v[k]))) for k in ('x', 'y', 'w', 'h'))
        except (KeyError, TypeError, ValueError):
            raise ValueError('Vùng che tên không hợp lệ')
        w, h = min(w, 1 - x), min(h, 1 - y)
        if w > 0.005 and h > 0.005:
            kq.append({'x': round(x, 4), 'y': round(y, 4), 'w': round(w, 4), 'h': round(h, 4)})
    return kq


def chuan_dang(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip().lower()


def tong_toi_da(de):
    return lam_tron(sum(float(c.get('diem', 0)) for c in de.get('cau', [])), 0.01)


def so_vn(x):
    if x is None or x == '':
        return ''
    return ('%g' % round(float(x), 2)).replace('.', ',')


def chon_bai_mau(de_id, tru_id=None):
    """Bài giáo viên đã duyệt, được phép làm mẫu. Ưu tiên bài GV có sửa so với AI, rồi bài mới duyệt."""
    ds = [b for b in ds_bai(de_id)
          if b.get('duyet') and b['duyet'].get('lam_mau', True) and b['id'] != tru_id]
    ds.sort(key=lambda b: b['duyet'].get('luc', ''), reverse=True)
    ds.sort(key=lambda b: not b['duyet'].get('co_sua'))
    return ds[:SO_BAI_MAU]


def van_ban_bai_mau(cac_bai):
    dong = ['BÀI MẪU GIÁO VIÊN ĐÃ CHẤM',
            'Đây là bài của học sinh khác cùng đề, giáo viên đã duyệt điểm. Hãy cho điểm theo đúng cách '
            'và mức độ khắt khe của giáo viên trong các bài mẫu. Chỗ ghi "AI chấm ban đầu" là chỗ giáo viên '
            'đã sửa điểm của AI: tránh lặp lại sai lệch đó.', '']
    for i, b in enumerate(cac_bai, 1):
        ai = {chuan_so(c['so']): c for c in (b.get('ket_qua') or {}).get('cau', [])}
        dong.append(f'--- Bài mẫu {i} ---')
        for c in b['duyet']['cau']:
            dong.append(f"Câu {c['so']}, học sinh viết:\n{c.get('chep_lai') or '(bỏ trống)'}")
            dong_diem = f"Điểm giáo viên cho: {so_vn(c['diem'])}/{so_vn(c.get('toi_da'))}"
            a = ai.get(chuan_so(c['so']))
            if a and abs(float(a['diem']) - float(c['diem'])) > 1e-9:
                dong_diem += f" (AI chấm ban đầu: {so_vn(a['diem'])})"
            dong.append(dong_diem)
            if c.get('nhan_xet'):
                dong.append('Nhận xét của giáo viên: ' + c['nhan_xet'])
        dong.append('')
    return '\n'.join(dong)


def vi_du_cung_dang(de):
    """Các câu giáo viên đã duyệt ở ĐỀ KHÁC, có cùng 'dạng bài' với câu trong đề này."""
    can = {chuan_dang(c.get('dang')) for c in de.get('cau', []) if chuan_dang(c.get('dang'))}
    if not can or not os.path.isdir(DU_LIEU):
        return []
    theo_dang = {}
    for ten in os.listdir(DU_LIEU):
        if ten == de['id'] or not re.fullmatch(r'[0-9a-f]{10}', ten):
            continue
        de_khac = doc_de(ten)
        if not de_khac:
            continue
        cau_khac = {chuan_so(c['so']): c for c in de_khac.get('cau', []) if chuan_dang(c.get('dang')) in can}
        if not cau_khac:
            continue
        for b in ds_bai(ten):
            gv = b.get('duyet')
            if not gv or gv.get('lam_mau') is False:
                continue
            ai = {chuan_so(c['so']): c for c in (b.get('ket_qua') or {}).get('cau', [])} \
                if b.get('trang_thai') == 'xong' else {}
            for c in gv['cau']:
                g = cau_khac.get(chuan_so(c['so']))
                if not g:
                    continue
                a = ai.get(chuan_so(c['so']))
                theo_dang.setdefault(chuan_dang(g['dang']), []).append({
                    'dang': g['dang'], 'de': de_khac.get('ten', ''), 'noidung': g.get('noidung', ''),
                    'dapan': g.get('dapan', ''), 'toi_da': c.get('toi_da', g['diem']),
                    'chep_lai': c.get('chep_lai', ''), 'diem': c['diem'], 'nhan_xet': c.get('nhan_xet', ''),
                    'diem_ai': a['diem'] if a else None,
                    'co_sua': bool(a) and abs(float(a['diem']) - float(c['diem'])) > 1e-9,
                    'luc': gv.get('luc', '')})
    kq = []
    for dang in sorted(theo_dang):
        ds = sorted(theo_dang[dang], key=lambda x: x['luc'], reverse=True)
        ds.sort(key=lambda x: not x['co_sua'])
        kq += ds[:SO_VI_DU_MOI_DANG]
    return kq[:SO_VI_DU_TOI_DA]


def van_ban_vi_du(ds):
    dong = ['VÍ DỤ CHẤM TỪ ĐỀ KHÁC CÙNG DẠNG BÀI',
            'Đây là các câu cùng dạng ở đề khác, giáo viên đã duyệt điểm. Thang điểm có thể khác đề này; '
            'hãy học cách giáo viên cho điểm và mức độ khắt khe, không chép điểm số.', '']
    for i, v in enumerate(ds, 1):
        dong.append(f"--- Ví dụ {i} · dạng: {v['dang']} · đề: {v['de']} ---")
        if v['noidung']:
            dong.append('Đề: ' + v['noidung'])
        if v['dapan']:
            dong.append('Đáp án và thang điểm: ' + v['dapan'])
        dong.append('Học sinh viết:\n' + (v['chep_lai'] or '(bỏ trống)'))
        d = f"Điểm giáo viên cho: {so_vn(v['diem'])}/{so_vn(v['toi_da'])}"
        if v['co_sua']:
            d += f" (AI chấm ban đầu: {so_vn(v['diem_ai'])})"
        dong.append(d)
        if v['nhan_xet']:
            dong.append('Nhận xét của giáo viên: ' + v['nhan_xet'])
        dong.append('')
    return '\n'.join(dong)


def cham_mot_bai(de_id, bai_id):
    de = doc_de(de_id)
    with khoa:
        bai = doc_bai(de_id, bai_id)
        if not de or not bai:
            return
        bai['trang_thai'] = 'dang_cham'
        bai['loi'] = ''
        ghi_bai(bai)

    cap_nhat = {}
    try:
        if anthropic is None:
            raise RuntimeError('Chưa cài thư viện anthropic. Chạy lại chay.bat để cài tự động.')
        api_key = lay_khoa_api()
        if not api_key:
            raise RuntimeError('Chưa nhập khoá API. Bấm ⚙ Cài đặt ở góc trên trang.')
        client = anthropic.Anthropic(api_key=api_key, max_retries=4)

        # 1) Đề + đáp án: giống nhau cho mọi bài cùng đề -> đặt đầu để dùng bộ nhớ đệm.
        noi_dung = []
        for t in de.get('tep', []):
            noi_dung.append(khoi_noi_dung(os.path.join(tm_de(de_id), 'tep', t['ten']), t['mime']))
        noi_dung.append({'type': 'text', 'text': van_ban_de(de),
                         'cache_control': {'type': 'ephemeral'}})
        # 2) Cách chấm của giáo viên: lưu ý chung + bài mẫu đã duyệt (chỉ gửi chữ, không gửi ảnh).
        phong_cach = ((doc_json(CAU_HINH, {}) or {}).get('phong_cach') or '').strip()
        bai_mau = chon_bai_mau(de_id, bai_id)
        phan_gv = []
        if phong_cach:
            phan_gv.append('THÓI QUEN CHẤM CỦA GIÁO VIÊN (áp dụng cho mọi đề):\n' + phong_cach)
        vi_du = vi_du_cung_dang(de)
        if vi_du:
            phan_gv.append(van_ban_vi_du(vi_du))
        if bai_mau:
            phan_gv.append(van_ban_bai_mau(bai_mau))
        if phan_gv:
            noi_dung.append({'type': 'text', 'text': '\n\n'.join(phan_gv),
                             'cache_control': {'type': 'ephemeral'}})
        # 3) Bài làm của học sinh.
        ghi = f"BÀI LÀM CỦA HỌC SINH CẦN CHẤM ({len(bai['trang'])} trang, theo thứ tự):"
        if de.get('vung_che'):
            ghi += '\n(Vùng ghi họ tên đã được che để bảo mật, không cần đọc tên.)'
        noi_dung.append({'type': 'text', 'text': ghi})
        for i, t in enumerate(bai['trang']):
            duong = os.path.join(tm_bai(de_id, bai_id), t['ten'])
            che = anh_da_che(de, duong, t['mime'], i)
            noi_dung.append({'type': 'text', 'text': f'Trang {i + 1}:'})
            noi_dung.append(khoi_noi_dung(duong, che[1], che[0]) if che else khoi_noi_dung(duong, t['mime']))
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
        kq['so_bai_mau'] = len(bai_mau)
        kq['so_vi_du_dang'] = len(vi_du)

        u = tra_loi.usage
        cap_nhat = {
            'ket_qua': kq, 'trang_thai': 'xong', 'loi': '', 'cham_luc': bay_gio(),
            'thong_ke': {
                'giay': round(time.time() - bat_dau, 1),
                'mo_hinh': tra_loi.model,
                'token_vao': (u.input_tokens or 0) + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
                'token_ra': u.output_tokens,
            },
        }
    except Exception as e:  # noqa: BLE001 – mọi lỗi đều hiện cho thầy/cô thấy
        cap_nhat = {'trang_thai': 'loi', 'loi': mo_ta_loi(e)}

    # Đọc lại bài rồi mới ghi: trong lúc chấm, thầy/cô có thể đã đổi tên hoặc duyệt điểm.
    with khoa:
        bai = doc_bai(de_id, bai_id)
        if not bai:
            return  # bài đã bị xoá
        bai.update(cap_nhat)
        kq = cap_nhat.get('ket_qua') or {}
        if not bai.get('hoten') and kq.get('hoten_tren_bai'):
            bai['hoten'] = kq['hoten_tren_bai'].strip()
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


def ket_qua_cuoi(b):
    """Điểm chính thức: bản giáo viên duyệt; chưa duyệt thì dùng điểm AI."""
    if b.get('duyet'):
        return b['duyet']
    if b.get('trang_thai') == 'xong':
        return b.get('ket_qua')
    return None


def bang_ket_qua(de_id):
    de = doc_de(de_id)
    cau = [str(c['so']) for c in de.get('cau', [])]
    hang = [['STT', 'Họ và tên'] + [f'Câu {s}' for s in cau]
            + ['Tổng điểm', 'Giáo viên đã duyệt', 'Tổng điểm AI', 'Cần xem lại', 'Nhận xét chung']]
    for i, b in enumerate(ds_bai(de_id), 1):
        kq = ket_qua_cuoi(b)
        ai = b.get('ket_qua') or {}
        dong = [i, b.get('hoten') or '(chưa rõ tên)']
        if kq:
            diem = {chuan_so(c['so']): c['diem'] for c in kq.get('cau', [])}
            dong += [diem.get(chuan_so(s), '') for s in cau]
            dong += [kq.get('tong_diem', ''), 'Có' if b.get('duyet') else '',
                     ai.get('tong_diem', '') if b.get('trang_thai') == 'xong' else '',
                     '' if b.get('duyet') else ai.get('can_xem_lai', ''), kq.get('nhan_xet_chung', '')]
        else:
            dong += [''] * len(cau)
            dong += ['', '', '', 'Chưa chấm xong' if b.get('trang_thai') != 'loi' else 'Lỗi: ' + b.get('loi', ''), '']
        hang.append(dong)
    return hang


def xuat_du_lieu(de_id=None, an_danh=True):
    """Gói các bài giáo viên đã duyệt thành tệp zip, dùng để đánh giá hoặc huấn luyện AI sau này."""
    if de_id:
        ds_de = [an_toan_id(de_id)]
    else:
        ds_de = [t for t in (os.listdir(DU_LIEU) if os.path.isdir(DU_LIEU) else [])
                 if re.fullmatch(r'[0-9a-f]{10}', t)]
    mau = []
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for did in ds_de:
            de = doc_de(did)
            if not de:
                continue
            cac_bai = [b for b in ds_bai(did) if b.get('duyet')]
            if not cac_bai:
                continue
            z.writestr(f'de/{did}.json', json.dumps(de, ensure_ascii=False, indent=1))
            for t in de.get('tep', []):
                duong = os.path.join(tm_de(did), 'tep', t['ten'])
                if os.path.isfile(duong):
                    z.write(duong, f'de/{did}/{t["ten"]}')
            for b in cac_bai:
                anh = []
                for i, t in enumerate(b['trang']):
                    duong = os.path.join(tm_bai(did, b['id']), t['ten'])
                    if not os.path.isfile(duong):
                        continue
                    che = None
                    if an_danh:
                        try:
                            che = anh_da_che(de, duong, t['mime'], i)
                        except RuntimeError:
                            che = None  # PDF cũ / thiếu pillow: giữ nguyên, có ghi chú trong DOC_TRUOC
                    if che:
                        ten_che = os.path.splitext(t['ten'])[0] + '_che.jpg'
                        z.writestr(f'anh/{b["id"]}/{ten_che}', che[0])
                        anh.append(f'anh/{b["id"]}/{ten_che}')
                    else:
                        z.write(duong, f'anh/{b["id"]}/{t["ten"]}')
                        anh.append(f'anh/{b["id"]}/{t["ten"]}')
                ai = json.loads(json.dumps(b.get('ket_qua'))) if b.get('trang_thai') == 'xong' else None
                if an_danh:
                    hs = 'HS_' + hashlib.sha1((did + b['id']).encode()).hexdigest()[:8]
                    if ai:
                        ai['hoten_tren_bai'] = ''
                else:
                    hs = b.get('hoten', '')
                mau.append({'de_id': did, 'mon': de.get('mon'), 'bai_id': b['id'], 'hoc_sinh': hs,
                            'anh': anh, 'ai': ai,
                            'mo_hinh_ai': (b.get('thong_ke') or {}).get('mo_hinh') if ai else None,
                            'giao_vien': b['duyet']})
        z.writestr('dulieu.jsonl', '\n'.join(json.dumps(m, ensure_ascii=False) for m in mau))
        z.writestr('DOC_TRUOC.txt', (
            'DỮ LIỆU BÀI LÀM ĐÃ ĐƯỢC GIÁO VIÊN DUYỆT ĐIỂM\n'
            f'Xuất lúc {bay_gio()}. Số bài: {len(mau)}. Ẩn danh: {"có" if an_danh else "KHÔNG"}.\n\n'
            'dulieu.jsonl: mỗi dòng là một bài.\n'
            '  anh        : ảnh bài làm (thư mục anh/)\n'
            '  ai         : kết quả AI chấm (bản chép lại, điểm từng ý, nhận xét)\n'
            '  giao_vien  : bản giáo viên đã duyệt (bản chép lại đã sửa, điểm, nhận xét) = nhãn đúng\n'
            'de/: đề, đáp án, thang điểm.\n\n'
            'LƯU Ý: chế độ ẩn danh thay họ tên trong dữ liệu và che vùng ghi tên trên ảnh (nếu đề có\n'
            'đặt vùng che, tệp *_che.jpg). Đề chưa đặt vùng che thì ảnh vẫn còn họ tên học sinh.\n'
            'Hãy xem lại ảnh trước khi chia sẻ. Chỉ dùng hoặc chia sẻ dữ liệu này khi đã có sự đồng ý theo\n'
            'quy định bảo vệ dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP).\n'))
    return out.getvalue(), len(mau)


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
                              'phong_cach': (doc_json(CAU_HINH, {}) or {}).get('phong_cach', ''),
                              'tu_bien_moi_truong': bool(os.environ.get('ANTHROPIC_API_KEY')),
                              'co_thu_vien': anthropic is not None, 'co_pillow': Image is not None,
                              'mo_hinh': MO_HINH})
        if p == ['api', 'dangbai']:
            dem = {}
            if os.path.isdir(DU_LIEU):
                for ten in os.listdir(DU_LIEU):
                    d = doc_json(os.path.join(DU_LIEU, ten, 'de.json'))
                    for c in (d or {}).get('cau', []):
                        if c.get('dang'):
                            dem.setdefault(chuan_dang(c['dang']), [c['dang'], 0])[1] += 1
            return self.json(sorted((v for v in dem.values()), key=lambda v: -v[1]))
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
        if p == ['api', 'dulieu.zip']:
            q = parse_qs(urlparse(self.path).query)
            noi_dung, n = xuat_du_lieu((q.get('de') or [''])[0] or None, (q.get('an_danh') or ['1'])[0] != '0')
            if not n:
                raise ValueError('Chưa có bài nào được giáo viên duyệt điểm')
            ten_tep = f'dulieu_chamtuluan_{datetime.datetime.now():%Y%m%d_%H%M}.zip'
            return self.gui(200, 'application/zip', noi_dung,
                            {'Content-Disposition': f'attachment; filename="{ten_tep}"'})
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
            if bai_id != 'de' and parse_qs(urlparse(self.path).query).get('che') == ['1']:
                b = doc_bai(de_id, bai_id)
                i = next((k for k, t in enumerate(b['trang']) if t['ten'] == ten), 0)
                try:
                    che = anh_da_che(doc_de(de_id), duong, mime, i)
                except RuntimeError as e:
                    raise ValueError(str(e))
                if che:
                    return self.gui(200, che[1], che[0])
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
            if k:
                ch['api_key'] = k
            if 'phong_cach' in d:
                ch['phong_cach'] = str(d['phong_cach']).strip()[:5000]
            ghi_json(CAU_HINH, ch)
            return self.json({'ok': True})
        if p == ['api', 'de']:
            return self.json(self.luu_de(d))
        if len(p) == 4 and p[:2] == ['api', 'de'] and p[3] == 'bai':
            return self.json(self.them_bai(p[2], d))
        if len(p) == 4 and p[:2] == ['api', 'de'] and p[3] == 'chamtatca':
            n = 0
            for b in ds_bai(p[2]):
                if b.get('trang_thai') in ('moi', 'loi') or (d.get('cham_lai') and b.get('trang_thai') == 'xong' and not b.get('duyet')):
                    xep_hang_cham(p[2], b['id'])
                    n += 1
            return self.json({'so_bai': n})
        if len(p) == 5 and p[:2] == ['api', 'bai'] and p[4] == 'cham':
            xep_hang_cham(p[2], an_toan_id(p[3]))
            return self.json({'ok': True})
        if len(p) == 5 and p[:2] == ['api', 'bai'] and p[4] == 'duyet':
            return self.json(self.duyet_bai(p[2], an_toan_id(p[3]), d))
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
                            'dang': re.sub(r'\s+', ' ', str(c.get('dang', ''))).strip()[:80],
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
                'vung_che': chuan_vung_che(d.get('vung_che', (cu or {}).get('vung_che', []))),
                'che_moi_trang': bool(d.get('che_moi_trang', (cu or {}).get('che_moi_trang', False))),
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

    def duyet_bai(self, de_id, bai_id, d):
        with khoa:
            de = doc_de(de_id)
            b = doc_bai(de_id, bai_id)
            if not de or not b:
                raise ValueError('Không tìm thấy bài')
            if d.get('bo_duyet'):
                b.pop('duyet', None)
                ghi_bai(b)
                return b
            cau_de = {chuan_so(c['so']): c for c in de['cau']}
            ai = {chuan_so(c['so']): c for c in (b.get('ket_qua') or {}).get('cau', [])} \
                if b.get('trang_thai') == 'xong' else {}
            cau, co_sua = [], not ai
            for c in d.get('cau', []):
                g = cau_de.get(chuan_so(c.get('so', '')))
                if not g:
                    continue
                try:
                    diem = float(str(c.get('diem', '')).replace(',', '.'))
                except ValueError:
                    raise ValueError(f"Điểm câu {g['so']} chưa nhập hoặc không phải là số")
                if diem < 0 or diem > float(g['diem']) + 1e-9:
                    raise ValueError(f"Điểm câu {g['so']} phải từ 0 đến {so_vn(g['diem'])}")
                chep = str(c.get('chep_lai', '')).strip()
                a = ai.get(chuan_so(g['so']))
                if not a or abs(float(a['diem']) - diem) > 1e-9 or (a.get('chep_lai') or '').strip() != chep:
                    co_sua = True
                cau.append({'so': g['so'], 'toi_da': float(g['diem']), 'diem': round(diem, 2),
                            'chep_lai': chep, 'nhan_xet': str(c.get('nhan_xet', '')).strip()})
            if len(cau) != len(de['cau']):
                raise ValueError('Chưa có điểm cho đủ các câu')
            b['duyet'] = {'cau': cau, 'tong_diem': round(sum(c['diem'] for c in cau), 2),
                          'nhan_xet_chung': str(d.get('nhan_xet_chung', '')).strip(),
                          'lam_mau': bool(d.get('lam_mau', True)), 'co_sua': co_sua, 'luc': bay_gio()}
            ghi_bai(b)
            return b

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
