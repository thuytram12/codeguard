#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeGuard – chương trình chạy trên MÁY THẦY.

Cách chạy: bấm đúp file  chay_may_thay.bat  (hoặc mở file này bằng Python).
Trang theo dõi tự mở trong trình duyệt tại  http://localhost:8765

Chỉ dùng thư viện có sẵn của Python, không cần cài thêm gì.
"""

import csv
import datetime
import hashlib
import io
import json
import os
import random
import secrets
import shutil
import socket
import sys
import threading
import time
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# ----------------------------------------------------------------------------
# Cấu hình
# ----------------------------------------------------------------------------
PHIEN_BAN = '1.0'
CONG_WEB = 8765            # cổng học sinh kết nối tới
CONG_TIM = 8766            # cổng UDP để máy học sinh tự tìm máy thầy
GIAY_MAT_TIN_HIEU = 10     # quá số giây này không nhận tín hiệu => "mất tín hiệu"
CHU_KY_GUI = 2             # máy học sinh gửi tín hiệu mỗi bao nhiêu giây
SO_LAN_SAI_MA = 5          # sai mã quá số lần này thì khoá tạm
GIAY_KHOA_SAI_MA = 60

THU_MUC = os.path.dirname(os.path.abspath(__file__))
FILE_DANH_SACH = os.path.join(THU_MUC, 'danhsach.txt')
FILE_QUY_DINH = os.path.join(THU_MUC, 'quydinh.json')
FILE_TRANG_THAI = os.path.join(THU_MUC, 'trangthai.json')
FILE_GIAM_SAT = os.path.join(THU_MUC, 'giamsat.pyw')
FILE_TRANG_THAY = os.path.join(THU_MUC, 'trangthay.html')
THU_MUC_KET_QUA = os.path.join(THU_MUC, 'ketqua')

QUY_DINH_MAC_DINH = {
    "ghi_chu": "Danh sách chương trình học sinh được phép dùng. Sửa xong bấm 'Tải lại quy định' trên trang của thầy.",
    "chuong_trinh_duoc_phep": [
        {"ten": "Code::Blocks",
         "tien_trinh": ["codeblocks.exe", "cblauncher.exe", "cb_console_runner.exe", "gdb.exe"]},
        {"ten": "Python IDLE",
         "tien_trinh": ["python.exe", "pythonw.exe", "python3*.exe", "pythonw3*.exe", "py.exe", "pyw.exe"]},
        {"ten": "Notepad",
         "tien_trinh": ["notepad.exe"]}
    ],
    "trinh_duyet": [
        {"ten": "Chrome (VNOJ)",
         "tien_trinh": ["chrome.exe"],
         "tieu_de_phai_chua": ["VNOJ", "VNOI"]}
    ],
    "cua_so_dong_lenh": {
        "ten": "Cửa sổ chạy chương trình",
        "lop_cua_so": ["ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"],
        "tieu_de_cam": ["cmd.exe", "command prompt", "dấu nhắc lệnh", "powershell", "pwsh"]
    },
    "bo_qua_lop_cua_so": [
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW",
        "MultitaskingViewFrame", "XamlExplorerHostIslandWindow", "ForegroundStaging",
        "TaskSwitcherWnd", "#32768", "NotifyIconOverflowWindow",
        "TopLevelWindowForOverflowXamlIsland"
    ],
    "bo_qua_tien_trinh": ["startmenuexperiencehost.exe", "shellexperiencehost.exe", "lockapp.exe"]
}

# ----------------------------------------------------------------------------
# Trạng thái (dùng chung giữa các luồng, luôn giữ khoá khi đọc/ghi)
# ----------------------------------------------------------------------------
khoa = threading.RLock()
danh_sach = []            # [(ten, ma)] theo thứ tự trong danhsach.txt
ma_cua = {}               # ten -> ma
quy_dinh = {}
quy_dinh_ver = ''
ma_bam_goc = ''
sai_ma = {}               # ten -> [so_lan, khoa_den]
token_cua = {}            # token -> ten
trang_thai = {}
co_thay_doi = False


def in_ra(*a):
    try:
        print(*a, flush=True)
    except Exception:
        try:
            print(*(str(x).encode('ascii', 'replace').decode() for x in a), flush=True)
        except Exception:
            pass


def gio(t):
    if not t:
        return ''
    return datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S')


def ngay_gio(t):
    if not t:
        return ''
    return datetime.datetime.fromtimestamp(t).strftime('%d/%m/%Y %H:%M:%S')


def dinh_dang_giay(s):
    s = int(round(s or 0))
    if s < 60:
        return '%d giây' % s
    if s < 3600:
        return '%d phút %d giây' % (s // 60, s % 60)
    return '%d giờ %d phút' % (s // 3600, (s % 3600) // 60)


def ma_bam_ma_nguon(noi_dung):
    """Mã băm của chương trình giám sát (bỏ qua dòng MAY_CHU vì dòng đó được điền tự động)."""
    dong = [d.rstrip() for d in noi_dung.splitlines() if not d.startswith('MAY_CHU =')]
    return hashlib.sha256('\n'.join(dong).strip().encode('utf-8')).hexdigest()[:16]


def ghi_file_an_toan(duong_dan, noi_dung, ma_hoa='utf-8'):
    tam = duong_dan + '.tam'
    with open(tam, 'w', encoding=ma_hoa, newline='') as f:
        f.write(noi_dung)
    for _ in range(5):
        try:
            os.replace(tam, duong_dan)
            return
        except OSError:
            time.sleep(0.2)
    os.replace(tam, duong_dan)


# ----------------------------------------------------------------------------
# Danh sách lớp & mã vào bài
# ----------------------------------------------------------------------------
def doc_van_ban(duong_dan):
    with open(duong_dan, 'rb') as f:
        du_lieu = f.read()
    for mh in ('utf-8-sig', 'cp1258', 'latin-1'):
        try:
            return du_lieu.decode(mh)
        except UnicodeDecodeError:
            pass
    return du_lieu.decode('utf-8', 'replace')


def tao_ma(da_co):
    r = random.SystemRandom()
    while True:
        m = '%04d' % r.randint(0, 9999)
        if m not in da_co:
            da_co.add(m)
            return m


def ghi_danh_sach():
    dong = ['# Danh sách lớp – mỗi dòng: Họ tên;Mã vào bài',
            '# Muốn thêm học sinh: ghi thêm tên (không cần mã), chương trình sẽ tự tạo mã.',
            '# Muốn đổi mã một em: xoá phần ";mã" của em đó rồi chạy lại chương trình.',
            '']
    dong += ['%s;%s' % (t, m) for t, m in danh_sach]
    ghi_file_an_toan(FILE_DANH_SACH, '\n'.join(dong) + '\n', 'utf-8-sig')


def doc_danh_sach():
    global danh_sach, ma_cua
    if not os.path.exists(FILE_DANH_SACH):
        danh_sach = []
        ma_cua = {}
        ghi_danh_sach()
        return
    ds = []
    da_thay = set()
    for dong in doc_van_ban(FILE_DANH_SACH).splitlines():
        dong = dong.strip()
        if not dong or dong.startswith('#'):
            continue
        for tach in (';', '\t'):
            if tach in dong:
                ten, ma = dong.split(tach, 1)
                break
        else:
            ten, ma = dong, ''
        ten = ' '.join(ten.split())
        ma = ma.strip()
        if not ten:
            continue
        goc, i = ten, 2
        while ten in da_thay:
            ten = '%s (%d)' % (goc, i)
            i += 1
        da_thay.add(ten)
        ds.append([ten, ma])
    ma_da_co = set()
    can_ghi = False
    for muc in ds:
        if not muc[1] or muc[1] in ma_da_co:
            muc[1] = ''
            can_ghi = True
        else:
            ma_da_co.add(muc[1])
    for muc in ds:
        if not muc[1]:
            muc[1] = tao_ma(ma_da_co)
    danh_sach = [tuple(m) for m in ds]
    ma_cua = dict(danh_sach)
    if can_ghi:
        ghi_danh_sach()


def tao_ma_moi_tat_ca():
    global danh_sach, ma_cua
    da_co = set()
    danh_sach = [(t, tao_ma(da_co)) for t, _ in danh_sach]
    ma_cua = dict(danh_sach)
    ghi_danh_sach()


# ----------------------------------------------------------------------------
# Quy định & chương trình giám sát
# ----------------------------------------------------------------------------
def doc_quy_dinh():
    global quy_dinh, quy_dinh_ver
    if not os.path.exists(FILE_QUY_DINH):
        ghi_file_an_toan(FILE_QUY_DINH, json.dumps(QUY_DINH_MAC_DINH, ensure_ascii=False, indent=2))
    try:
        qd = json.loads(doc_van_ban(FILE_QUY_DINH))
    except ValueError as e:
        in_ra('!! File quydinh.json bị lỗi (%s). Tạm dùng quy định mặc định.' % e)
        qd = QUY_DINH_MAC_DINH
    for k, v in QUY_DINH_MAC_DINH.items():
        qd.setdefault(k, v)
    quy_dinh = qd
    quy_dinh_ver = hashlib.sha256(json.dumps(qd, sort_keys=True).encode()).hexdigest()[:12]


def doc_ma_bam_goc():
    global ma_bam_goc
    try:
        ma_bam_goc = ma_bam_ma_nguon(doc_van_ban(FILE_GIAM_SAT))
    except OSError:
        ma_bam_goc = ''
        in_ra('!! Không thấy file giamsat.pyw cạnh maythay.py.')


# ----------------------------------------------------------------------------
# Lưu / nạp trạng thái buổi thi
# ----------------------------------------------------------------------------
def hs_moi(ten):
    return {
        'ten': ten, 'token': None, 'may': '', 'nguoi_dung': '', 'he_dieu_hanh': '', 'ip': '',
        'gio_vao': None, 'lan_cuoi': None, 'hien_tai': None,
        'so_vi_pham': 0, 'tong_giay_vi_pham': 0.0, 'vp_mo': None,
        'so_mat_tin_hieu': 0, 'mat_tin_hieu': False, 'mat_tu': None,
        'da_tat': False, 'so_lan_tat': 0, 'sua_giam_sat': False,
        'seq': 0, 'nhat_ky': [],
    }


def trang_thai_moi(link=''):
    return {
        'buoi': {'trang_thai': 'cho', 'bat_dau': None, 'ket_thuc': None, 'link': link, 'tao_luc': time.time()},
        'hoc_sinh': {},
        'su_kien': [],
    }


def dong_bo_hoc_sinh():
    """Đảm bảo mỗi tên trong danh sách đều có bản ghi."""
    hs = trang_thai['hoc_sinh']
    for ten, _ in danh_sach:
        if ten not in hs:
            hs[ten] = hs_moi(ten)
        else:
            mau = hs_moi(ten)
            for k, v in mau.items():
                hs[ten].setdefault(k, v)
    token_cua.clear()
    for ten, r in hs.items():
        if r.get('token') and ten in ma_cua:
            token_cua[r['token']] = ten


def nap_trang_thai():
    global trang_thai
    trang_thai = trang_thai_moi()
    if os.path.exists(FILE_TRANG_THAI):
        try:
            tt = json.loads(doc_van_ban(FILE_TRANG_THAI))
            if isinstance(tt, dict) and 'buoi' in tt:
                trang_thai = tt
                trang_thai.setdefault('su_kien', [])
                trang_thai.setdefault('hoc_sinh', {})
        except ValueError:
            in_ra('!! File trangthai.json bị lỗi, bắt đầu buổi mới.')
    dong_bo_hoc_sinh()


def danh_dau():
    global co_thay_doi
    co_thay_doi = True


def luu_neu_can(bat_buoc=False):
    global co_thay_doi
    with khoa:
        if not (co_thay_doi or bat_buoc):
            return
        noi_dung = json.dumps(trang_thai, ensure_ascii=False)
        co_thay_doi = False
    try:
        ghi_file_an_toan(FILE_TRANG_THAI, noi_dung)
    except OSError as e:
        in_ra('!! Không lưu được trạng thái:', e)
        danh_dau()


def ghi(hs, loai, noi_dung, t=None, **them):
    t = t or time.time()
    e = {'t': t, 'loai': loai, 'noi_dung': noi_dung}
    e.update(them)
    hs['nhat_ky'].append(e)
    sk = trang_thai['su_kien']
    sk.append({'t': t, 'ten': hs['ten'], 'loai': loai, 'noi_dung': noi_dung})
    del sk[:-300]
    danh_dau()
    return len(hs['nhat_ky']) - 1


def dong_vi_pham(hs, t):
    i = hs.get('vp_mo')
    if i is None:
        return
    hs['vp_mo'] = None
    if 0 <= i < len(hs['nhat_ky']):
        e = hs['nhat_ky'][i]
        giay = max(0.0, t - e['t'])
        e['giay'] = round(giay, 1)
        hs['tong_giay_vi_pham'] += giay
    danh_dau()


# ----------------------------------------------------------------------------
# Xử lý yêu cầu của học sinh
# ----------------------------------------------------------------------------
def loi(s, **kw):
    d = {'ok': False, 'loi': s}
    d.update(kw)
    return d


def thong_tin_buoi():
    b = trang_thai['buoi']
    return {'buoi': b['trang_thai'], 'link': b.get('link', ''), 'chu_ky': CHU_KY_GUI}


def xu_ly_vao(body, ip):
    ten = ' '.join(str(body.get('ten', '')).split())
    ma = str(body.get('ma', '')).strip()
    may = str(body.get('may', ''))[:80]
    now = time.time()
    with khoa:
        if trang_thai['buoi']['trang_thai'] == 'ket_thuc':
            return loi('Buổi thi đã kết thúc, không vào được nữa.')
        ma_dung = ma_cua.get(ten)
        if ma_dung is None:
            return loi('Không có tên này trong danh sách lớp.')
        s = sai_ma.get(ten)
        if s and s[1] > now:
            return loi('Em nhập sai mã quá nhiều lần. Chờ %d giây rồi thử lại.' % (s[1] - now + 1))
        if ma != ma_dung:
            s = sai_ma.setdefault(ten, [0, 0])
            s[0] += 1
            if s[0] >= SO_LAN_SAI_MA:
                s[0] = 0
                s[1] = now + GIAY_KHOA_SAI_MA
                hs = trang_thai['hoc_sinh'][ten]
                ghi(hs, 'canh_bao', 'Nhập sai mã %d lần liên tiếp từ máy %s (IP %s)' % (SO_LAN_SAI_MA, may, ip))
            return loi('Sai mã vào bài. Em kiểm tra lại mã thầy phát.')
        sai_ma.pop(ten, None)
        hs = trang_thai['hoc_sinh'][ten]
        dang_hoat_dong = (hs['token'] and hs['lan_cuoi'] and not hs['da_tat']
                          and now - hs['lan_cuoi'] < GIAY_MAT_TIN_HIEU)
        if dang_hoat_dong and hs['may'] != may:
            ghi(hs, 'canh_bao', 'Máy khác (%s, IP %s) thử vào bằng tên này trong lúc em đang làm bài' % (may, ip))
            return loi('Tên này đang được dùng trên máy khác. Em báo thầy.')
        vao_lai = hs['token'] is not None
        if hs['token']:
            token_cua.pop(hs['token'], None)
        if hs['vp_mo'] is not None:
            dong_vi_pham(hs, hs['lan_cuoi'] or now)
        token = secrets.token_hex(16)
        token_cua[token] = ten
        hs.update(token=token, may=may, ip=ip,
                  nguoi_dung=str(body.get('nguoi_dung', ''))[:80],
                  he_dieu_hanh=str(body.get('he_dieu_hanh', ''))[:80],
                  lan_cuoi=now, da_tat=False, seq=0, mat_tin_hieu=False, mat_tu=None,
                  hien_tai=None)
        if not hs['gio_vao']:
            hs['gio_vao'] = now
        ghi(hs, 'vao', '%s từ máy %s (IP %s)' % ('Vào lại' if vao_lai else 'Vào làm bài', may, ip))
        ma_bam = str(body.get('ma_bam', ''))
        if ma_bam_goc and ma_bam != ma_bam_goc:
            if not hs['sua_giam_sat']:
                hs['sua_giam_sat'] = True
            ghi(hs, 'canh_bao', 'Chương trình giám sát trên máy em KHÁC bản của thầy (bản cũ hoặc đã bị sửa)')
        kq = {'ok': True, 'token': token, 'ten': ten, 'quy_dinh': quy_dinh, 'qd_ver': quy_dinh_ver,
              'so_vi_pham': hs['so_vi_pham']}
        kq.update(thong_tin_buoi())
        return kq


def xu_ly_su_kien(hs, sk, t):
    loai = sk.get('loai')
    buoi = trang_thai['buoi']
    dang_thi = buoi['trang_thai'] == 'dang_thi'
    if loai == 'vi_pham':
        if not dang_thi and not (buoi['ket_thuc'] and t <= buoi['ket_thuc']):
            return
        dong_vi_pham(hs, t)
        ud = str(sk.get('ung_dung', ''))[:120]
        td = str(sk.get('tieu_de', ''))[:300]
        hs['so_vi_pham'] += 1
        hs['vp_mo'] = ghi(hs, 'vi_pham', '%s – %s' % (ud, td) if td else ud, t,
                          ung_dung=ud, tieu_de=td, tien_trinh=str(sk.get('tien_trinh', ''))[:80], giay=None)
    elif loai == 'het_vi_pham':
        dong_vi_pham(hs, t)
    elif loai == 'tat':
        dong_vi_pham(hs, t)
        hs['da_tat'] = True
        if dang_thi:
            hs['so_lan_tat'] += 1
            ghi(hs, 'tat', 'Em tự đóng chương trình giám sát trong giờ thi', t)
        else:
            ghi(hs, 'he_thong', 'Đã đóng chương trình giám sát', t)


def xu_ly_tin(body):
    now = time.time()
    with khoa:
        ten = token_cua.get(str(body.get('token', '')))
        if not ten:
            return loi('Phiên làm bài không còn hiệu lực. Em đăng nhập lại.', ma_loi='phien')
        hs = trang_thai['hoc_sinh'][ten]
        try:
            lech = now - float(body.get('gio_may', now))
        except (TypeError, ValueError):
            lech = 0.0
        hs['lan_cuoi'] = now
        if hs['mat_tin_hieu']:
            hs['mat_tin_hieu'] = False
            ghi(hs, 'co_tin_hieu', 'Có tín hiệu lại (mất %s)' % dinh_dang_giay(now - (hs['mat_tu'] or now)))
        ht = body.get('hien_tai')
        if isinstance(ht, dict):
            hs['hien_tai'] = {'nhan': str(ht.get('nhan', ''))[:120],
                              'tieu_de': str(ht.get('tieu_de', ''))[:300],
                              'hop_le': ht.get('hop_le')}
        su_kien = body.get('su_kien') or []
        if isinstance(su_kien, list):
            for sk in su_kien[:500]:
                if not isinstance(sk, dict):
                    continue
                try:
                    seq = int(sk.get('seq', 0))
                    t = float(sk.get('t', now)) + lech
                except (TypeError, ValueError):
                    continue
                if seq <= hs['seq']:
                    continue
                hs['seq'] = seq
                xu_ly_su_kien(hs, sk, min(t, now))
        danh_dau()
        kq = {'ok': True, 'da_nhan': hs['seq'], 'so_vi_pham': hs['so_vi_pham'], 'qd_ver': quy_dinh_ver}
        if body.get('qd_ver') != quy_dinh_ver:
            kq['quy_dinh'] = quy_dinh
        kq.update(thong_tin_buoi())
        return kq


# ----------------------------------------------------------------------------
# Việc của thầy
# ----------------------------------------------------------------------------
def tinh_trang(hs, buoi, now):
    if not hs['token'] and not hs['gio_vao']:
        return 'chua_vao'
    if buoi == 'ket_thuc':
        return 'xong'
    if hs['da_tat']:
        return 'da_tat'
    if not hs['token'] or not hs['lan_cuoi'] or now - hs['lan_cuoi'] > GIAY_MAT_TIN_HIEU:
        return 'mat_tin_hieu'
    if hs['vp_mo'] is not None:
        return 'vi_pham'
    if buoi == 'cho':
        return 'cho'
    return 'dang_lam'


def tong_quan():
    now = time.time()
    with khoa:
        b = trang_thai['buoi']
        ds = []
        for i, (ten, _) in enumerate(danh_sach):
            hs = trang_thai['hoc_sinh'][ten]
            giay_vp = hs['tong_giay_vi_pham']
            if hs['vp_mo'] is not None:
                giay_vp += max(0.0, (hs['lan_cuoi'] or now) - hs['nhat_ky'][hs['vp_mo']]['t'])
            ds.append({
                'stt': i + 1, 'ten': ten, 'tinh_trang': tinh_trang(hs, b['trang_thai'], now),
                'may': hs['may'], 'ip': hs['ip'], 'gio_vao': hs['gio_vao'], 'lan_cuoi': hs['lan_cuoi'],
                'hien_tai': hs['hien_tai'], 'so_vi_pham': hs['so_vi_pham'],
                'giay_vi_pham': round(giay_vp), 'so_mat_tin_hieu': hs['so_mat_tin_hieu'],
                'so_lan_tat': hs['so_lan_tat'], 'sua_giam_sat': hs['sua_giam_sat'],
                'so_canh_bao': sum(1 for e in hs['nhat_ky'] if e['loai'] == 'canh_bao'),
            })
        return {
            'bay_gio': now, 'phien_ban': PHIEN_BAN,
            'buoi': b, 'dia_chi': dia_chi_ip(), 'cong': CONG_WEB,
            'hoc_sinh': ds, 'su_kien': trang_thai['su_kien'][-80:][::-1],
            'quy_dinh': quy_dinh, 'giay_mat_tin_hieu': GIAY_MAT_TIN_HIEU,
        }


def nhat_ky_cua(ten):
    with khoa:
        hs = trang_thai['hoc_sinh'].get(ten)
        if not hs:
            return loi('Không có học sinh này')
        return {'ok': True, 'ten': ten, 'nhat_ky': hs['nhat_ky'], 'may': hs['may'], 'ip': hs['ip'],
                'nguoi_dung': hs['nguoi_dung'], 'he_dieu_hanh': hs['he_dieu_hanh']}


def bat_dau():
    with khoa:
        b = trang_thai['buoi']
        if b['trang_thai'] != 'cho':
            return loi('Buổi thi không ở trạng thái chờ.')
        b['trang_thai'] = 'dang_thi'
        b['bat_dau'] = time.time()
        danh_dau()
    luu_neu_can(True)
    in_ra('>> Đã BẮT ĐẦU buổi thi lúc', gio(time.time()))
    return {'ok': True}


def ket_thuc():
    with khoa:
        b = trang_thai['buoi']
        if b['trang_thai'] != 'dang_thi':
            return loi('Buổi thi chưa bắt đầu.')
        now = time.time()
        for hs in trang_thai['hoc_sinh'].values():
            if hs['vp_mo'] is not None:
                dong_vi_pham(hs, min(now, (hs['lan_cuoi'] or now) + CHU_KY_GUI))
        b['trang_thai'] = 'ket_thuc'
        b['ket_thuc'] = now
        danh_dau()
    luu_neu_can(True)
    thu_muc = luu_ket_qua()
    in_ra('>> Đã KẾT THÚC buổi thi. Kết quả lưu tại:', thu_muc)
    return {'ok': True, 'thu_muc': thu_muc}


def buoi_moi():
    global trang_thai
    with khoa:
        if trang_thai['buoi']['trang_thai'] == 'dang_thi':
            return loi('Đang trong giờ thi. Thầy bấm "Kết thúc" trước.')
        da_co_du_lieu = any(h['gio_vao'] for h in trang_thai['hoc_sinh'].values())
    if da_co_du_lieu:
        luu_ket_qua()
    with khoa:
        trang_thai = trang_thai_moi(trang_thai['buoi'].get('link', ''))
        sai_ma.clear()
        dong_bo_hoc_sinh()
        danh_dau()
    luu_neu_can(True)
    return {'ok': True}


def dat_lai(ten):
    with khoa:
        hs = trang_thai['hoc_sinh'].get(ten)
        if not hs:
            return loi('Không có học sinh này')
        if hs['token']:
            token_cua.pop(hs['token'], None)
        if hs['vp_mo'] is not None:
            dong_vi_pham(hs, hs['lan_cuoi'] or time.time())
        hs['token'] = None
        hs['da_tat'] = False
        sai_ma.pop(ten, None)
        ghi(hs, 'he_thong', 'Thầy cho phép em đăng nhập lại (đặt lại phiên)')
    return {'ok': True}


def dat_link(link):
    link = str(link or '').strip()[:500]
    if link and not link.lower().startswith(('http://', 'https://')):
        link = 'https://' + link
    with khoa:
        trang_thai['buoi']['link'] = link
        danh_dau()
    return {'ok': True, 'link': link}


def tao_ma_moi():
    with khoa:
        if trang_thai['buoi']['trang_thai'] == 'dang_thi':
            return loi('Không đổi mã trong giờ thi.')
        tao_ma_moi_tat_ca()
    return {'ok': True}


def tai_lai_quy_dinh():
    with khoa:
        doc_quy_dinh()
    return {'ok': True, 'qd_ver': quy_dinh_ver}


# ----------------------------------------------------------------------------
# Xuất kết quả
# ----------------------------------------------------------------------------
TEN_LOAI = {'vao': 'Vào bài', 'vi_pham': 'VI PHẠM', 'mat_tin_hieu': 'Mất tín hiệu',
            'co_tin_hieu': 'Có tín hiệu lại', 'tat': 'Tự đóng giám sát', 'canh_bao': 'Cảnh báo',
            'he_thong': 'Thông tin'}


def csv_tong_hop():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['STT', 'Họ tên', 'Máy', 'Giờ vào', 'Số lần vi phạm', 'Tổng thời gian vi phạm (giây)',
                'Số lần mất tín hiệu', 'Số lần tự đóng giám sát', 'Giám sát bị sửa/khác bản',
                'Số cảnh báo khác', 'Các chương trình vi phạm'])
    with khoa:
        for i, (ten, _) in enumerate(danh_sach):
            hs = trang_thai['hoc_sinh'][ten]
            dem = Counter(e.get('ung_dung', '') for e in hs['nhat_ky'] if e['loai'] == 'vi_pham')
            w.writerow([i + 1, ten, hs['may'], ngay_gio(hs['gio_vao']) or 'Không vào',
                        hs['so_vi_pham'], round(hs['tong_giay_vi_pham']), hs['so_mat_tin_hieu'],
                        hs['so_lan_tat'], 'CÓ' if hs['sua_giam_sat'] else '',
                        sum(1 for e in hs['nhat_ky'] if e['loai'] == 'canh_bao'),
                        '; '.join('%s ×%d' % (k, v) for k, v in dem.most_common())])
    return out.getvalue()


def csv_nhat_ky():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Họ tên', 'Thời gian', 'Loại', 'Nội dung', 'Thời lượng (giây)'])
    with khoa:
        dong = []
        for ten, _ in danh_sach:
            for e in trang_thai['hoc_sinh'][ten]['nhat_ky']:
                dong.append((e['t'], ten, e))
        dong.sort(key=lambda x: x[0])
        for t, ten, e in dong:
            w.writerow([ten, ngay_gio(t), TEN_LOAI.get(e['loai'], e['loai']), e['noi_dung'],
                        '' if e.get('giay') is None else e['giay']])
    return out.getvalue()


def luu_ket_qua():
    with khoa:
        t = trang_thai['buoi'].get('bat_dau') or trang_thai['buoi'].get('tao_luc') or time.time()
    ten_tm = datetime.datetime.fromtimestamp(t).strftime('buoi_%Y-%m-%d_%Hh%M')
    tm = os.path.join(THU_MUC_KET_QUA, ten_tm)
    os.makedirs(tm, exist_ok=True)
    ghi_file_an_toan(os.path.join(tm, 'tonghop.csv'), csv_tong_hop(), 'utf-8-sig')
    ghi_file_an_toan(os.path.join(tm, 'nhatky.csv'), csv_nhat_ky(), 'utf-8-sig')
    luu_neu_can(True)
    try:
        shutil.copyfile(FILE_TRANG_THAI, os.path.join(tm, 'trangthai.json'))
    except OSError:
        pass
    return tm


# ----------------------------------------------------------------------------
# Trang HTML nhỏ (in mã, trang tải về cho học sinh)
# ----------------------------------------------------------------------------
def thoat_html(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def trang_in_ma():
    ip = dia_chi_ip()
    dia_chi = ('%s:%d' % (ip[0], CONG_WEB)) if ip else '(xem trên trang của thầy)'
    the = ''.join(
        '<div class="the"><div class="t">%s</div><div class="m">Mã vào bài: <b>%s</b></div>'
        '<div class="g">Máy thầy: %s</div></div>' % (thoat_html(t), thoat_html(m), thoat_html(dia_chi))
        for t, m in danh_sach)
    return ('<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>In mã vào bài</title>'
            '<style>body{font-family:"Segoe UI",Arial,sans-serif;margin:16px;color:#111}'
            'h1{font-size:18px}.goi{columns:3;column-gap:10px}'
            '.the{break-inside:avoid;border:1px dashed #555;padding:10px 12px;margin:0 0 10px;border-radius:4px}'
            '.t{font-weight:700;font-size:16px}.m{font-size:15px;margin-top:4px}.m b{font-size:20px;letter-spacing:2px}'
            '.g{font-size:12px;color:#555;margin-top:4px}@media print{.an{display:none}}'
            'button{font-size:16px;padding:8px 16px}</style></head><body>'
            '<div class="an"><h1>Mã vào bài – %d học sinh</h1>'
            '<p>Bấm nút để in, rồi cắt theo đường nét đứt và phát cho từng em.</p>'
            '<button onclick="print()">In</button><hr></div><div class="goi">%s</div></body></html>'
            % (len(danh_sach), the))


TRANG_HOC_SINH = '''<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>CodeGuard – Tải chương trình</title>
<style>body{font-family:"Segoe UI",Arial,sans-serif;background:#f3f6fa;margin:0;color:#1d2733}
.k{max-width:620px;margin:40px auto;background:#fff;border-radius:12px;padding:24px 28px;box-shadow:0 2px 10px rgba(0,0,0,.08)}
h1{color:#0b4f9c;font-size:22px;margin-top:0}a.n{display:inline-block;background:#0b4f9c;color:#fff;padding:12px 20px;
border-radius:8px;text-decoration:none;font-weight:700;font-size:18px}li{margin:6px 0;line-height:1.5}</style></head>
<body><div class="k"><h1>Chương trình giám sát phòng thi</h1>
<p><a class="n" href="/taive/giamsat.pyw" download>Tải giamsat.pyw</a></p>
<ol><li>Bấm nút trên để tải về. Nếu Chrome hỏi, bấm <b>Giữ lại</b> (Keep).</li>
<li>Mở thư mục <b>Tải xuống</b>, bấm đúp vào file <b>giamsat.pyw</b>.</li>
<li>Nếu không mở được: bấm chuột phải vào file → <b>Open with</b> → <b>Python</b>
(hoặc mở bằng IDLE rồi bấm <b>F5</b>).</li>
<li>Chọn tên, nhập mã thầy phát, bấm <b>Vào làm bài</b>. Không đóng cửa sổ giám sát trong giờ thi.</li></ol>
</div></body></html>'''


# ----------------------------------------------------------------------------
# Mạng
# ----------------------------------------------------------------------------
_ip_cache = [0, []]


def dia_chi_ip():
    if time.time() - _ip_cache[0] < 30:
        return _ip_cache[1]
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(r[4][0])
    except OSError:
        pass
    kq = []
    for ip in ips:
        if ip not in kq and not ip.startswith('127.') and not ip.startswith('169.254.'):
            kq.append(ip)
    _ip_cache[0] = time.time()
    _ip_cache[1] = kq
    return kq


class XuLy(BaseHTTPRequestHandler):
    server_version = 'CodeGuard/' + PHIEN_BAN
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def gui(self, ma, kieu, du_lieu, them=None):
        if isinstance(du_lieu, str):
            du_lieu = du_lieu.encode('utf-8')
        self.send_response(ma)
        self.send_header('Content-Type', kieu)
        self.send_header('Content-Length', str(len(du_lieu)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (them or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(du_lieu)

    def gui_json(self, obj, ma=200):
        self.gui(ma, 'application/json; charset=utf-8', json.dumps(obj, ensure_ascii=False))

    def doc_json(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 2_000_000:
            raise ValueError('quá lớn')
        du_lieu = self.rfile.read(n) if n else b'{}'
        obj = json.loads(du_lieu.decode('utf-8') or '{}')
        if not isinstance(obj, dict):
            raise ValueError('sai dạng')
        return obj

    def la_thay(self):
        """Chỉ máy thầy (mở bằng localhost) mới được dùng trang quản lý."""
        ip = self.client_address[0]
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]').lower()
        return ip in ('127.0.0.1', '::1') and host in ('localhost', '127.0.0.1', '::1')

    def cam(self):
        self.gui(403, 'text/plain; charset=utf-8', 'Trang này chỉ mở được trên máy thầy (http://localhost:%d)' % CONG_WEB)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)
        if p == '/api/danhsach':
            with khoa:
                self.gui_json({'ok': True, 'ten': [t for t, _ in danh_sach],
                               'buoi': trang_thai['buoi']['trang_thai'], 'phien_ban': PHIEN_BAN})
            return
        if p == '/taive/giamsat.pyw':
            try:
                nd = doc_van_ban(FILE_GIAM_SAT)
            except OSError:
                self.gui(404, 'text/plain; charset=utf-8', 'Không thấy giamsat.pyw')
                return
            host = self.headers.get('Host') or ''
            if host and not host.startswith(('localhost', '127.')):
                if ':' not in host:
                    host += ':80'
                nd = '\n'.join(("MAY_CHU = %r" % host) if d.startswith('MAY_CHU =') else d
                               for d in nd.splitlines()) + '\n'
            self.gui(200, 'application/octet-stream', nd.encode('utf-8'),
                     {'Content-Disposition': 'attachment; filename="giamsat.pyw"'})
            return
        if not self.la_thay():
            if p in ('/', '/index.html'):
                self.gui(200, 'text/html; charset=utf-8', TRANG_HOC_SINH)
            else:
                self.cam()
            return
        # ---- chỉ máy thầy ----
        if p in ('/', '/index.html'):
            try:
                with open(FILE_TRANG_THAY, 'rb') as f:
                    self.gui(200, 'text/html; charset=utf-8', f.read())
            except OSError:
                self.gui(500, 'text/plain; charset=utf-8', 'Thiếu file trangthay.html')
        elif p == '/api/tongquan':
            self.gui_json(tong_quan())
        elif p == '/api/nhatky':
            self.gui_json(nhat_ky_cua((q.get('ten') or [''])[0]))
        elif p == '/inma':
            self.gui(200, 'text/html; charset=utf-8', trang_in_ma())
        elif p in ('/xuat/tonghop.csv', '/xuat/nhatky.csv'):
            nd = csv_tong_hop() if 'tonghop' in p else csv_nhat_ky()
            ten = ('tonghop_' if 'tonghop' in p else 'nhatky_') + datetime.datetime.now().strftime('%Y%m%d_%H%M') + '.csv'
            self.gui(200, 'text/csv; charset=utf-8', '﻿' + nd,
                     {'Content-Disposition': 'attachment; filename="%s"' % ten})
        else:
            self.gui(404, 'text/plain; charset=utf-8', 'Không có trang này')

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            body = self.doc_json()
        except (ValueError, UnicodeDecodeError):
            self.gui_json(loi('Dữ liệu gửi lên không hợp lệ'), 400)
            return
        if p == '/api/vao':
            self.gui_json(xu_ly_vao(body, self.client_address[0]))
            return
        if p == '/api/tin':
            self.gui_json(xu_ly_tin(body))
            return
        if not self.la_thay() or self.headers.get('X-CodeGuard') != '1':
            self.cam()
            return
        viec = {
            '/api/batdau': bat_dau,
            '/api/ketthuc': ket_thuc,
            '/api/buoimoi': buoi_moi,
            '/api/taomamoi': tao_ma_moi,
            '/api/tailaiquydinh': tai_lai_quy_dinh,
            '/api/datlai': lambda: dat_lai(str(body.get('ten', ''))),
            '/api/link': lambda: dat_link(body.get('link')),
            '/api/luuketqua': lambda: {'ok': True, 'thu_muc': luu_ket_qua()},
        }.get(p)
        if not viec:
            self.gui_json(loi('Không có chức năng này'), 404)
            return
        self.gui_json(viec())


def nghe_tim_kiem():
    """Trả lời máy học sinh đang tìm máy thầy trong mạng LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', CONG_TIM))
    except OSError as e:
        in_ra('!! Không mở được cổng tìm kiếm %d (%s). Học sinh sẽ phải gõ địa chỉ máy thầy.' % (CONG_TIM, e))
        return
    tra_loi = json.dumps({'codeguard': 1, 'cong': CONG_WEB}).encode()
    while True:
        try:
            du_lieu, dia_chi = s.recvfrom(1024)
            if du_lieu.startswith(b'CODEGUARD_TIM'):
                s.sendto(tra_loi, dia_chi)
        except OSError:
            time.sleep(0.5)


def canh_gac():
    """Phát hiện máy học sinh mất tín hiệu và lưu trạng thái định kỳ."""
    while True:
        time.sleep(2)
        try:
            with khoa:
                if trang_thai['buoi']['trang_thai'] == 'dang_thi':
                    now = time.time()
                    for hs in trang_thai['hoc_sinh'].values():
                        if (hs['token'] and not hs['da_tat'] and not hs['mat_tin_hieu'] and hs['lan_cuoi']
                                and now - hs['lan_cuoi'] > GIAY_MAT_TIN_HIEU):
                            hs['mat_tin_hieu'] = True
                            hs['mat_tu'] = hs['lan_cuoi']
                            hs['so_mat_tin_hieu'] += 1
                            ghi(hs, 'mat_tin_hieu',
                                'Mất tín hiệu (máy tắt, mất mạng hoặc chương trình giám sát bị tắt ngang)',
                                hs['lan_cuoi'])
            luu_neu_can()
        except Exception as e:  # không để luồng canh gác chết
            in_ra('!! Lỗi canh gác:', e)


def khoi_dong():
    with khoa:
        doc_danh_sach()
        doc_quy_dinh()
        doc_ma_bam_goc()
        nap_trang_thai()


def main(mo_trinh_duyet=True):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    os.chdir(THU_MUC)
    khoi_dong()
    try:
        may_chu = ThreadingHTTPServer(('0.0.0.0', CONG_WEB), XuLy)
    except OSError as e:
        in_ra('!! Không mở được cổng %d: %s' % (CONG_WEB, e))
        in_ra('   Có thể chương trình máy thầy ĐANG CHẠY ở một cửa sổ khác. Hãy đóng cửa sổ đó rồi chạy lại.')
        input('Bấm Enter để thoát...')
        return
    may_chu.daemon_threads = True
    threading.Thread(target=nghe_tim_kiem, daemon=True).start()
    threading.Thread(target=canh_gac, daemon=True).start()

    in_ra('=' * 64)
    in_ra('  CodeGuard %s – MÁY THẦY đang chạy' % PHIEN_BAN)
    in_ra('=' * 64)
    in_ra('  Danh sách lớp: %d học sinh (file danhsach.txt)' % len(danh_sach))
    ips = dia_chi_ip()
    if ips:
        in_ra('  Địa chỉ máy thầy cho học sinh:')
        for ip in ips:
            in_ra('      %s:%d      (tải chương trình: http://%s:%d )' % (ip, CONG_WEB, ip, CONG_WEB))
    else:
        in_ra('  !! Chưa thấy máy thầy nối mạng.')
    in_ra('  Trang theo dõi của thầy: http://localhost:%d' % CONG_WEB)
    in_ra('  KHÔNG đóng cửa sổ này trong giờ thi.')
    in_ra('=' * 64)
    if not danh_sach:
        in_ra('  !! danhsach.txt đang trống. Thầy ghi tên học sinh vào rồi chạy lại chương trình.')
    if mo_trinh_duyet:
        threading.Timer(1.0, lambda: webbrowser.open('http://localhost:%d' % CONG_WEB)).start()
    try:
        may_chu.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        luu_neu_can(True)
        in_ra('Đã dừng máy thầy.')


if __name__ == '__main__':
    main('--khong-mo' not in sys.argv)
