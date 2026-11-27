#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeGuard – chương trình GIÁM SÁT chạy trên MÁY HỌC SINH.

Cách chạy: bấm đúp file này (hoặc mở bằng IDLE rồi bấm F5).
Chỉ dùng thư viện có sẵn của Python, không cần cài thêm gì.
"""
MAY_CHU = ''   # Địa chỉ máy thầy, ví dụ '192.168.1.5:8765'. Để trống: tự tìm trong mạng LAN.

import fnmatch
import getpass
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

PHIEN_BAN = '1.0'
CONG_MAC_DINH = 8765
CONG_TIM = 8766
LA_WINDOWS = sys.platform == 'win32'
FILE_NHO_MAY_CHU = os.path.join(os.path.expanduser('~'), '.codeguard_maychu')

# ----------------------------------------------------------------------------
# Đọc cửa sổ đang dùng (Windows)
# ----------------------------------------------------------------------------
if LA_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    _ten_tt_cache = {}

    def ten_tien_trinh(pid):
        if pid in _ten_tt_cache:
            return _ten_tt_cache[pid]
        ten = ''
        h = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                n = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    ten = os.path.basename(buf.value)
            finally:
                kernel32.CloseHandle(h)
        if len(_ten_tt_cache) > 500:
            _ten_tt_cache.clear()
        if ten:
            _ten_tt_cache[pid] = ten
        return ten

    def cua_so_dang_dung():
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        lop = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, lop, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return {'tien_trinh': ten_tien_trinh(pid.value), 'tieu_de': buf.value,
                'lop': lop.value, 'pid': pid.value}

    def khong_chiem_tieu_diem(widget):
        """Biến cửa sổ cảnh báo thành loại không giành bàn phím/chuột khỏi bài làm."""
        hwnd = user32.GetAncestor(widget.winfo_id(), 2) or widget.winfo_id()
        kieu = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, kieu | 0x08000000 | 0x00000080 | 0x00000008)
        return hwnd

    def hien_khong_chiem(hwnd):
        user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
        user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)

    def an_cua_so(hwnd):
        user32.ShowWindow(hwnd, 0)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
else:
    def cua_so_dang_dung():
        """Ngoài Windows (chỉ dùng để thử): đọc cửa sổ giả lập từ biến môi trường."""
        f = os.environ.get('CODEGUARD_GIA_LAP')
        if f and os.path.exists(f):
            try:
                with open(f, encoding='utf-8') as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return None
        return None


# ----------------------------------------------------------------------------
# Đánh giá cửa sổ có được phép hay không
# ----------------------------------------------------------------------------
def khop(ten, mau):
    ten = (ten or '').lower()
    return any(fnmatch.fnmatchcase(ten, m.lower()) for m in mau)


def danh_gia(cs, qd, pid_minh=None):
    """Trả về (hop_le, nhan). hop_le: True = được phép, False = vi phạm, None = bỏ qua (thanh tác vụ...)."""
    if not cs or not qd:
        return None, ''
    tt = cs.get('tien_trinh') or ''
    td = cs.get('tieu_de') or ''
    lop = cs.get('lop') or ''
    td_l = td.lower()
    if pid_minh is not None and cs.get('pid') == pid_minh:
        return True, 'Chương trình giám sát'
    if lop in qd.get('bo_qua_lop_cua_so', []) or khop(tt, qd.get('bo_qua_tien_trinh', [])):
        return None, ''
    dl = qd.get('cua_so_dong_lenh') or {}
    if lop in dl.get('lop_cua_so', []):
        if any(x.lower() in td_l for x in dl.get('tieu_de_cam', [])):
            return False, 'Dòng lệnh (cmd/PowerShell)'
        return True, dl.get('ten', 'Cửa sổ chạy chương trình')
    for tdu in qd.get('trinh_duyet', []):
        if khop(tt, tdu.get('tien_trinh', [])):
            if any(k.lower() in td_l for k in tdu.get('tieu_de_phai_chua', [])):
                return True, tdu.get('ten', 'Trình duyệt')
            ten_td = os.path.splitext(tt)[0].capitalize() or 'Trình duyệt'
            return False, '%s – trang không được phép' % ten_td
    for c in qd.get('chuong_trinh_duoc_phep', []):
        if khop(tt, c.get('tien_trinh', [])):
            return True, c.get('ten', tt)
    if tt.lower() == 'applicationframehost.exe' and td:
        return False, td
    if tt:
        ten = os.path.splitext(tt)[0]
        return False, ten[:1].upper() + ten[1:]
    return False, td or 'Chương trình không rõ'


def ma_bam_ma_nguon(noi_dung):
    dong = [d.rstrip() for d in noi_dung.splitlines() if not d.startswith('MAY_CHU =')]
    return hashlib.sha256('\n'.join(dong).strip().encode('utf-8')).hexdigest()[:16]


def ma_bam_cua_minh():
    try:
        with open(os.path.abspath(__file__), 'rb') as f:
            return ma_bam_ma_nguon(f.read().decode('utf-8-sig', 'replace'))
    except (OSError, NameError):
        return ''


def chuan_hoa_dia_chi(s):
    s = (s or '').strip()
    for tien_to in ('http://', 'https://'):
        if s.lower().startswith(tien_to):
            s = s[len(tien_to):]
    s = s.split('/')[0]
    if s and ':' not in s:
        s += ':%d' % CONG_MAC_DINH
    return s


def tim_may_thay(thoi_gian=3.0):
    """Gửi tin quảng bá trong mạng LAN để tìm máy thầy. Trả về 'ip:cong' hoặc ''."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.5)
        dich = {'255.255.255.255'}
        try:
            t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            t.connect(('10.255.255.255', 1))
            ip = t.getsockname()[0]
            t.close()
            dich.add('.'.join(ip.split('.')[:3]) + '.255')
        except OSError:
            pass
        try:
            for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                dich.add('.'.join(r[4][0].split('.')[:3]) + '.255')
        except OSError:
            pass
        het = time.time() + thoi_gian
        lan_gui = 0
        while time.time() < het:
            if time.time() - lan_gui > 1:
                for d in dich:
                    try:
                        s.sendto(b'CODEGUARD_TIM', (d, CONG_TIM))
                    except OSError:
                        pass
                lan_gui = time.time()
            try:
                du_lieu, (ip, _) = s.recvfrom(1024)
                tl = json.loads(du_lieu.decode())
                if tl.get('codeguard'):
                    return '%s:%d' % (ip, int(tl.get('cong', CONG_MAC_DINH)))
            except (socket.timeout, ValueError, OSError):
                pass
        return ''
    finally:
        s.close()


def mo_chrome(link):
    if not link:
        return
    if LA_WINDOWS:
        for bien, duoi in (('ProgramFiles', r'Google\Chrome\Application\chrome.exe'),
                           ('ProgramFiles(x86)', r'Google\Chrome\Application\chrome.exe'),
                           ('LocalAppData', r'Google\Chrome\Application\chrome.exe')):
            goc = os.environ.get(bien)
            if goc and os.path.exists(os.path.join(goc, duoi)):
                try:
                    subprocess.Popen([os.path.join(goc, duoi), link])
                    return
                except OSError:
                    pass
    webbrowser.open(link)


# ----------------------------------------------------------------------------
# Phần lõi: kết nối máy thầy + theo dõi cửa sổ (không dính giao diện)
# ----------------------------------------------------------------------------
class LoiMang(Exception):
    pass


class GiamSat:
    def __init__(self, may_chu=''):
        self.may_chu = may_chu
        self.khoa = threading.RLock()
        self.co_viec = threading.Event()
        self.dung = threading.Event()
        self.token = None
        self.ten = ''
        self.quy_dinh = None
        self.qd_ver = ''
        self.buoi = 'cho'
        self.link = ''
        self.chu_ky = 2
        self.so_vi_pham = 0
        self.seq = 0
        self.hang_doi = []
        self.vp = None              # vi phạm đang diễn ra: {'nhan', 'tieu_de', 't'}
        self.hien_tai = {'nhan': '', 'tieu_de': '', 'hop_le': None}
        self.ket_noi_ok = None
        self.lan_ok = 0.0
        self.loi_lien_tiep = 0
        self.het_phien = ''         # khác rỗng khi thầy đặt lại phiên / buổi mới
        self.pid_minh = os.getpid()
        self.luong = []

    # ---- mạng ----
    def goi(self, duong, du_lieu=None, thoi_gian=6):
        url = 'http://%s%s' % (self.may_chu, duong)
        try:
            if du_lieu is None:
                req = urllib.request.Request(url)
            else:
                req = urllib.request.Request(url, data=json.dumps(du_lieu).encode('utf-8'),
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=thoi_gian) as r:
                return json.loads(r.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise LoiMang(str(getattr(e, 'reason', e)))

    def tai_danh_sach(self):
        return self.goi('/api/danhsach')

    def vao(self, ten, ma):
        kq = self.goi('/api/vao', {
            'ten': ten, 'ma': ma, 'may': socket.gethostname(),
            'nguoi_dung': self._nguoi_dung(), 'he_dieu_hanh': platform.platform(),
            'ma_bam': ma_bam_cua_minh(), 'phien_ban': PHIEN_BAN})
        if kq.get('ok'):
            with self.khoa:
                self.token = kq['token']
                self.ten = kq.get('ten', ten)
                self.quy_dinh = kq.get('quy_dinh')
                self.qd_ver = kq.get('qd_ver', '')
                self.buoi = kq.get('buoi', 'cho')
                self.link = kq.get('link', '')
                self.chu_ky = max(1, int(kq.get('chu_ky', 2)))
                self.so_vi_pham = kq.get('so_vi_pham', 0)
                self.seq = 0
                self.hang_doi = []
                self.vp = None
                self.het_phien = ''
                self.ket_noi_ok = True
                self.lan_ok = time.time()
        return kq

    @staticmethod
    def _nguoi_dung():
        try:
            return getpass.getuser()
        except Exception:
            return ''

    def them_su_kien(self, loai, **kw):
        with self.khoa:
            self.seq += 1
            sk = {'seq': self.seq, 'loai': loai, 't': time.time()}
            sk.update(kw)
            self.hang_doi.append(sk)
        self.co_viec.set()

    def gui_mot_lan(self):
        with self.khoa:
            if not self.token:
                return
            goi_tin = {'token': self.token, 'gio_may': time.time(), 'hien_tai': dict(self.hien_tai),
                       'su_kien': list(self.hang_doi), 'qd_ver': self.qd_ver}
        try:
            kq = self.goi('/api/tin', goi_tin, thoi_gian=5)
        except LoiMang:
            with self.khoa:
                self.loi_lien_tiep += 1
                if self.loi_lien_tiep >= 2:
                    self.ket_noi_ok = False
            return
        with self.khoa:
            if not kq.get('ok'):
                if kq.get('ma_loi') == 'phien':
                    self.token = None
                    self.vp = None
                    self.hang_doi = []
                    self.het_phien = kq.get('loi', 'Phiên đã hết, em đăng nhập lại.')
                return
            self.loi_lien_tiep = 0
            self.ket_noi_ok = True
            self.lan_ok = time.time()
            da_nhan = kq.get('da_nhan', 0)
            self.hang_doi = [s for s in self.hang_doi if s['seq'] > da_nhan]
            self.so_vi_pham = kq.get('so_vi_pham', self.so_vi_pham)
            self.chu_ky = max(1, int(kq.get('chu_ky', self.chu_ky)))
            self.link = kq.get('link', self.link)
            if kq.get('quy_dinh'):
                self.quy_dinh = kq['quy_dinh']
                self.qd_ver = kq.get('qd_ver', '')
            buoi_cu, self.buoi = self.buoi, kq.get('buoi', self.buoi)
        if buoi_cu != self.buoi:
            self.kiem_tra_mot_lan()

    # ---- theo dõi cửa sổ ----
    def kiem_tra_mot_lan(self, cs=None):
        if cs is None:
            try:
                cs = cua_so_dang_dung()
            except Exception:
                cs = None
        with self.khoa:
            if not self.token:
                return
            hop_le, nhan = danh_gia(cs, self.quy_dinh, self.pid_minh)
            if hop_le is not None:
                self.hien_tai = {'nhan': nhan, 'tieu_de': (cs or {}).get('tieu_de', ''), 'hop_le': hop_le}
            dang_thi = self.buoi == 'dang_thi'
            if hop_le is None and dang_thi:
                return                       # thanh tác vụ, màn hình nền...: giữ nguyên trạng thái
            if dang_thi and hop_le is False:
                if self.vp and self.vp['nhan'] == nhan:
                    return
                if self.vp:
                    self._ket_thuc_vp()
                td = (cs or {}).get('tieu_de', '')
                self.vp = {'nhan': nhan, 'tieu_de': td, 't': time.time()}
                self.them_su_kien('vi_pham', ung_dung=nhan, tieu_de=td,
                                  tien_trinh=(cs or {}).get('tien_trinh', ''))
            elif self.vp:
                self._ket_thuc_vp()

    def _ket_thuc_vp(self):
        self.vp = None
        self.them_su_kien('het_vi_pham')

    def _vong_kiem_tra(self):
        while not self.dung.is_set():
            try:
                self.kiem_tra_mot_lan()
            except Exception:
                pass
            self.dung.wait(0.5)

    def _vong_gui(self):
        while not self.dung.is_set():
            try:
                self.gui_mot_lan()
            except Exception:
                pass
            self.co_viec.wait(self.chu_ky)
            self.co_viec.clear()
            self.dung.wait(0.2)

    def chay(self):
        if self.luong:
            return
        for f in (self._vong_kiem_tra, self._vong_gui):
            t = threading.Thread(target=f, daemon=True)
            t.start()
            self.luong.append(t)

    def bao_tat(self):
        """Báo cho thầy là em đóng chương trình, cố gửi trước khi thoát."""
        with self.khoa:
            if not self.token:
                return
            if self.vp:
                self._ket_thuc_vp()
        self.them_su_kien('tat')
        for _ in range(2):
            self.gui_mot_lan()
            with self.khoa:
                if not self.hang_doi:
                    break


# ----------------------------------------------------------------------------
# Giao diện (tkinter)
# ----------------------------------------------------------------------------
def chay_giao_dien():
    import tkinter as tk
    from tkinter import messagebox, ttk

    MAU = {'nen': '#f3f6fa', 'chinh': '#0b4f9c', 'xanh': '#1a8f45', 'do': '#c62828', 'vang': '#b7791f',
           'chu': '#1d2733', 'phu': '#5b6b7c'}

    goc = tk.Tk()
    goc.title('CodeGuard – Giám sát phòng thi')
    goc.configure(bg=MAU['nen'])
    try:
        K = max(1.0, goc.winfo_fpixels('1i') / 96.0)   # hệ số phóng to màn hình (125%, 150%...)
    except Exception:
        K = 1.0
    W = int(430 * K)                                   # độ rộng dòng chữ
    goc.minsize(int(440 * K), int(380 * K))

    style = ttk.Style()
    try:
        style.theme_use('vista' if LA_WINDOWS else 'clam')
    except tk.TclError:
        pass
    PHONG = ('Segoe UI', 11)
    style.configure('TLabel', background=MAU['nen'], font=PHONG, foreground=MAU['chu'])
    style.configure('Tieude.TLabel', font=('Segoe UI', 16, 'bold'), foreground=MAU['chinh'])
    style.configure('Phu.TLabel', foreground=MAU['phu'], font=('Segoe UI', 10))
    style.configure('TButton', font=('Segoe UI', 11))
    style.configure('Lon.TButton', font=('Segoe UI', 12, 'bold'), padding=8)
    style.configure('TFrame', background=MAU['nen'])

    gs = GiamSat()
    khung = {}

    def khung_moi(ten):
        f = ttk.Frame(goc, padding=20)
        khung[ten] = f
        return f

    def hien_khung(ten):
        for k, f in khung.items():
            f.pack_forget()
        khung[ten].pack(fill='both', expand=True)

    # ---------- 1. Kết nối ----------
    f1 = khung_moi('ket_noi')
    ttk.Label(f1, text='Kết nối máy thầy', style='Tieude.TLabel').pack(anchor='w')
    ttk.Label(f1, text='Phiên bản %s' % PHIEN_BAN, style='Phu.TLabel').pack(anchor='w', pady=(0, 14))
    ttk.Label(f1, text='Địa chỉ máy thầy (thầy ghi trên bảng):').pack(anchor='w')
    bien_dc = tk.StringVar()
    o_dc = ttk.Entry(f1, textvariable=bien_dc, font=('Segoe UI', 13))
    o_dc.pack(fill='x', pady=(4, 10))
    hang = ttk.Frame(f1)
    hang.pack(fill='x')
    nut_kn = ttk.Button(hang, text='Kết nối', style='Lon.TButton')
    nut_kn.pack(side='left', expand=True, fill='x', padx=(0, 6))
    nut_tim = ttk.Button(hang, text='Tự tìm máy thầy')
    nut_tim.pack(side='left', expand=True, fill='x')
    tb1 = ttk.Label(f1, text='', wraplength=W, foreground=MAU['do'])
    tb1.pack(anchor='w', pady=12)

    # ---------- 2. Đăng nhập ----------
    f2 = khung_moi('dang_nhap')
    ttk.Label(f2, text='Vào làm bài', style='Tieude.TLabel').pack(anchor='w')
    nhan_may = ttk.Label(f2, text='', style='Phu.TLabel')
    nhan_may.pack(anchor='w', pady=(0, 14))
    ttk.Label(f2, text='Chọn tên của em:').pack(anchor='w')
    bien_ten = tk.StringVar()
    o_ten = ttk.Combobox(f2, textvariable=bien_ten, state='readonly', font=('Segoe UI', 12))
    o_ten.pack(fill='x', pady=(4, 12))
    ttk.Label(f2, text='Mã vào bài (thầy phát):').pack(anchor='w')
    bien_ma = tk.StringVar()
    o_ma = ttk.Entry(f2, textvariable=bien_ma, show='•', font=('Segoe UI', 13))
    o_ma.pack(fill='x', pady=(4, 14))
    nut_vao = ttk.Button(f2, text='Vào làm bài', style='Lon.TButton')
    nut_vao.pack(fill='x')
    tb2 = ttk.Label(f2, text='', wraplength=W, foreground=MAU['do'])
    tb2.pack(anchor='w', pady=10)
    nut_doi = ttk.Button(f2, text='Đổi máy thầy')
    nut_doi.pack(anchor='w')

    # ---------- 3. Đang thi ----------
    f3 = khung_moi('dang_thi')
    nhan_ten = ttk.Label(f3, text='', style='Tieude.TLabel')
    nhan_ten.pack(anchor='w')
    nhan_buoi = tk.Label(f3, text='', font=('Segoe UI', 12, 'bold'), bg=MAU['nen'], anchor='w')
    nhan_buoi.pack(fill='x', pady=(6, 2))
    nhan_kn = tk.Label(f3, text='', font=('Segoe UI', 10), bg=MAU['nen'], anchor='w')
    nhan_kn.pack(fill='x')
    nhan_dang = tk.Label(f3, text='', font=('Segoe UI', 11), bg=MAU['nen'], anchor='w', justify='left',
                         wraplength=W)
    nhan_dang.pack(fill='x', pady=(10, 2))
    nhan_vp = tk.Label(f3, text='', font=('Segoe UI', 11), bg=MAU['nen'], anchor='w')
    nhan_vp.pack(fill='x')
    nhan_gio = tk.Label(f3, text='', font=('Segoe UI', 11), bg=MAU['nen'], anchor='w')
    nhan_gio.pack(fill='x', pady=(2, 10))
    nut_de = ttk.Button(f3, text='Mở trang đề VNOJ', style='Lon.TButton',
                        command=lambda: mo_chrome(gs.link))
    nut_de.pack(fill='x')
    nhac = tk.Label(f3, text='KHÔNG đóng cửa sổ này trong giờ thi.\n'
                             'Chỉ dùng: Code::Blocks, Python IDLE, Notepad, Chrome (trang VNOJ).',
                    font=('Segoe UI', 10), bg='#fff4e0', fg='#8a4b00', justify='left', anchor='w',
                    padx=10, pady=8)
    nhac.pack(fill='x', pady=(12, 0))

    # ---------- Cửa sổ cảnh báo (nổi trên cùng, không giành bàn phím) ----------
    canh_bao = tk.Toplevel(goc)
    canh_bao.overrideredirect(True)
    canh_bao.configure(bg=MAU['do'])
    try:
        canh_bao.attributes('-topmost', True)
    except tk.TclError:
        pass
    rong = min(goc.winfo_screenwidth() - 40, int(900 * K))
    canh_bao.geometry('%dx%d+%d+12' % (rong, int(120 * K), (goc.winfo_screenwidth() - rong) // 2))
    cb_chu = tk.Label(canh_bao, text='', font=('Segoe UI', 14, 'bold'), fg='white', bg=MAU['do'],
                      justify='center', wraplength=rong - 30)
    cb_chu.pack(expand=True, fill='both', padx=14, pady=10)
    canh_bao.update_idletasks()
    hwnd_cb = None
    if LA_WINDOWS:
        try:
            hwnd_cb = khong_chiem_tieu_diem(canh_bao)
            an_cua_so(hwnd_cb)
        except Exception:
            hwnd_cb = None
            canh_bao.withdraw()
    else:
        canh_bao.withdraw()
    cb_dang_hien = [False]

    def dat_canh_bao(noi_dung):
        if noi_dung:
            cb_chu.config(text=noi_dung)
            if not cb_dang_hien[0]:
                cb_dang_hien[0] = True
                if hwnd_cb:
                    hien_khong_chiem(hwnd_cb)
                else:
                    canh_bao.deiconify()
                    canh_bao.lift()
                if LA_WINDOWS:
                    try:
                        import winsound
                        winsound.MessageBeep(0x30)
                    except Exception:
                        pass
        elif cb_dang_hien[0]:
            cb_dang_hien[0] = False
            if hwnd_cb:
                an_cua_so(hwnd_cb)
            else:
                canh_bao.withdraw()

    # ---------- Hành động ----------
    def chay_nen(viec, xong):
        """Chạy việc mạng ở luồng phụ để giao diện không bị đứng."""
        def lam():
            try:
                kq = viec()
                loi_ = None
            except Exception as e:
                kq, loi_ = None, e
            goc.after(0, lambda: xong(kq, loi_))
        threading.Thread(target=lam, daemon=True).start()

    def ket_noi(dia_chi=None):
        dc = chuan_hoa_dia_chi(dia_chi if dia_chi is not None else bien_dc.get())
        if not dc:
            tb1.config(text='Em nhập địa chỉ máy thầy, hoặc bấm "Tự tìm máy thầy".', foreground=MAU['do'])
            return
        bien_dc.set(dc)
        gs.may_chu = dc
        tb1.config(text='Đang kết nối tới %s…' % dc, foreground=MAU['phu'])
        nut_kn.state(['disabled'])

        def xong(kq, loi_):
            nut_kn.state(['!disabled'])
            if loi_ or not kq or not kq.get('ok'):
                tb1.config(text='Không kết nối được máy thầy (%s).\nEm kiểm tra lại địa chỉ, mạng, hoặc báo thầy.'
                           % (loi_ or 'không rõ'), foreground=MAU['do'])
                return
            try:
                with open(FILE_NHO_MAY_CHU, 'w', encoding='utf-8') as f:
                    f.write(dc)
            except OSError:
                pass
            o_ten['values'] = kq.get('ten', [])
            nhan_may.config(text='Máy thầy: %s' % dc)
            tb2.config(text='')
            hien_khung('dang_nhap')
            if kq.get('buoi') == 'ket_thuc':
                tb2.config(text='Buổi thi đã kết thúc.')
        chay_nen(gs.tai_danh_sach, xong)

    def tu_tim():
        tb1.config(text='Đang tìm máy thầy trong mạng LAN…', foreground=MAU['phu'])
        nut_tim.state(['disabled'])

        def xong(dc, loi_):
            nut_tim.state(['!disabled'])
            if dc:
                ket_noi(dc)
            else:
                tb1.config(text='Không tự tìm được máy thầy. Em gõ địa chỉ thầy ghi trên bảng (ví dụ 192.168.1.5).',
                           foreground=MAU['do'])
        chay_nen(tim_may_thay, xong)

    def vao_bai(event=None):
        ten = bien_ten.get()
        ma = bien_ma.get().strip()
        if not ten:
            tb2.config(text='Em chưa chọn tên.')
            return
        if not ma:
            tb2.config(text='Em chưa nhập mã vào bài.')
            return
        tb2.config(text='Đang vào…', foreground=MAU['phu'])
        nut_vao.state(['disabled'])

        def xong(kq, loi_):
            nut_vao.state(['!disabled'])
            tb2.config(foreground=MAU['do'])
            if loi_:
                tb2.config(text='Lỗi kết nối: %s. Em bấm lại.' % loi_)
                return
            if not kq.get('ok'):
                tb2.config(text=kq.get('loi', 'Không vào được.'))
                return
            bien_ma.set('')
            nhan_ten.config(text=gs.ten)
            hien_khung('dang_thi')
            gs.chay()
            if gs.link and gs.buoi == 'dang_thi':
                mo_chrome(gs.link)
        chay_nen(lambda: gs.vao(ten, ma), xong)

    nut_kn.config(command=ket_noi)
    nut_tim.config(command=tu_tim)
    nut_vao.config(command=vao_bai)
    nut_doi.config(command=lambda: hien_khung('ket_noi'))
    o_ma.bind('<Return>', vao_bai)
    o_dc.bind('<Return>', lambda e: ket_noi())

    trang_truoc = ['']

    def cap_nhat():
        try:
            with gs.khoa:
                token, buoi, vp = gs.token, gs.buoi, dict(gs.vp) if gs.vp else None
                ht, ok, lan_ok = dict(gs.hien_tai), gs.ket_noi_ok, gs.lan_ok
                so_vp, het_phien, link = gs.so_vi_pham, gs.het_phien, gs.link
            if het_phien and not token:
                with gs.khoa:
                    gs.het_phien = ''
                dat_canh_bao('')
                tb2.config(text=het_phien, foreground=MAU['do'])
                hien_khung('dang_nhap')
                ket_noi(gs.may_chu)
            elif token:
                if buoi == 'cho':
                    nhan_buoi.config(text='⏳ Chờ thầy bắt đầu buổi thi', fg=MAU['vang'])
                elif buoi == 'dang_thi':
                    nhan_buoi.config(text='▶ Đang trong giờ thi – đang giám sát', fg=MAU['xanh'])
                else:
                    nhan_buoi.config(text='■ Thầy đã kết thúc buổi thi. Em có thể đóng chương trình.',
                                     fg=MAU['chinh'])
                if buoi != trang_truoc[0]:
                    if buoi == 'dang_thi' and trang_truoc[0] == 'cho' and link:
                        mo_chrome(link)
                    if buoi == 'ket_thuc':
                        try:
                            goc.deiconify()
                            goc.lift()
                        except tk.TclError:
                            pass
                    trang_truoc[0] = buoi
                if ok:
                    nhan_kn.config(text='● Đã kết nối máy thầy – lúc %s' % time.strftime('%H:%M:%S',
                                   time.localtime(lan_ok)), fg=MAU['xanh'])
                elif ok is False:
                    nhan_kn.config(text='● MẤT KẾT NỐI với máy thầy – em kiểm tra mạng và báo thầy',
                                   fg=MAU['do'])
                if ht.get('nhan'):
                    nhan_dang.config(text='%s Đang dùng: %s' % ('✔' if ht.get('hop_le') else '✖', ht['nhan']),
                                     fg=MAU['xanh'] if ht.get('hop_le') else MAU['do'])
                nhan_vp.config(text='Số lần vi phạm đã ghi: %d' % so_vp,
                               fg=MAU['do'] if so_vp else MAU['chu'])
                if link:
                    nut_de.state(['!disabled'])
                else:
                    nut_de.state(['disabled'])
                if vp and buoi == 'dang_thi':
                    giay = int(time.time() - vp['t'])
                    dat_canh_bao('⚠ CẢNH BÁO: Em đang dùng chương trình KHÔNG ĐƯỢC PHÉP: %s\n'
                                 'Lần vi phạm này đã được ghi lại và gửi cho thầy (%d giây).\n'
                                 'Hãy quay lại Code::Blocks, Python IDLE, Notepad hoặc trang VNOJ.'
                                 % (vp['nhan'], giay))
                else:
                    dat_canh_bao('')
                if buoi == 'dang_thi':
                    nhan_gio.config(text='Giờ máy: %s' % time.strftime('%H:%M:%S'))
                else:
                    nhan_gio.config(text='')
        except Exception:
            pass
        goc.after(400, cap_nhat)

    def khi_dong():
        with gs.khoa:
            dang_thi = gs.token and gs.buoi == 'dang_thi'
            co_token = bool(gs.token)
        if dang_thi:
            if not messagebox.askyesno(
                    'Thoát giám sát?',
                    'Đang trong giờ thi. Nếu em đóng chương trình giám sát, thầy sẽ thấy ngay và '
                    'việc này được ghi vào nhật ký.\n\nEm có chắc chắn muốn đóng không?',
                    icon='warning', default='no', parent=goc):
                return
        if co_token:
            try:
                gs.bao_tat()
            except Exception:
                pass
        gs.dung.set()
        goc.destroy()

    goc.protocol('WM_DELETE_WINDOW', khi_dong)

    # Địa chỉ máy thầy: ghi sẵn trong file > lần trước > tự tìm
    dc = MAY_CHU
    if not dc:
        try:
            with open(FILE_NHO_MAY_CHU, encoding='utf-8') as f:
                dc = f.read().strip()
        except OSError:
            dc = ''
    hien_khung('ket_noi')
    if dc:
        bien_dc.set(dc)
        goc.after(200, lambda: ket_noi(dc))
    else:
        goc.after(200, tu_tim)
    goc.after(400, cap_nhat)
    goc.mainloop()


if __name__ == '__main__':
    try:
        chay_giao_dien()
    except Exception as e:
        # Khi chạy bằng pythonw sẽ không có cửa sổ lệnh, nên hiện lỗi bằng hộp thoại
        try:
            import traceback
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror('CodeGuard – lỗi', 'Chương trình gặp lỗi, em báo thầy:\n\n%s' %
                                 traceback.format_exc()[-1500:])
        except Exception:
            raise e
