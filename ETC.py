import cv2, sqlite3, time, sys, re, os
import datetime as dt
import numpy as np
from collections import deque, Counter
import pytesseract

# --- 1. THÊM THƯ VIỆN PYGAME ĐỂ PHÁT NHẠC ---
try:
    import pygame
    CO_AM_THANH = True
except ImportError:
    CO_AM_THANH = False
    print("[!] Chưa cài pygame. Sẽ không có tiếng. (Chạy: pip install pygame)")

# --- CẤU HÌNH ---
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception: pass

# --- CẤU HÌNH IP CAMERA ---
IP_PHONE = "192.168.1.30"
URL_VIDEO = f"http://{IP_PHONE}:8080/video"

PHI_THU_PHI = 15000
DUONG_DAN_DB = "du_lieu_etcv.db" 
FILE_AM_THANH = "thanhcong.mp3" # <--- Tên file nhạc của bạn
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- HÀM XỬ LÝ DATABASE (GIỮ NGUYÊN) ---
def chuan_hoa_bien(s):
    if not s: return ""
    s = s.upper()
    s = s.translate(str.maketrans({'O':'0', 'Q':'0', 'I':'1', 'L':'1', 'T':'7', 'S':'5', 'B':'8', 'Z':'2'}))
    return re.sub(r'[^A-Z0-9]', '', s)

def ket_noi_db():
    return sqlite3.connect(DUONG_DAN_DB, check_same_thread=False)

def tim_nguoi_theo_bien(con, bien_so):
    bn = chuan_hoa_bien(bien_so)
    sql = "SELECT * FROM nguoi_dung WHERE REPLACE(REPLACE(REPLACE(UPPER(bien_so),'.',''),'-',''),' ','') = ?"
    cursor = con.cursor()
    cursor.execute(sql, (bn,))
    res = cursor.fetchone()
    if res:
        columns = [column[0] for column in cursor.description]
        return dict(zip(columns, res))
    return None

def ghi_giao_dich(con, uid, bien_so, so_tien, thanh_cong, ly_do):
    con.execute("INSERT INTO giao_dich(thoi_gian,uid,bien_so,so_tien,ket_qua,ly_do,tram) VALUES(?,?,?,?,?,?,?)",
                (dt.datetime.now().isoformat(timespec="seconds"), uid, bien_so, -so_tien if thanh_cong else 0, "OK" if thanh_cong else "FAIL", ly_do, "TRAM_VIDEO"))
    if thanh_cong:
        con.execute("UPDATE nguoi_dung SET so_du = so_du - ? WHERE uid=?", (so_tien, uid))
    con.commit()

# --- 2. HÀM PHÁT NHẠC MỚI ---
def phat_nhac_thanh_cong():
    if CO_AM_THANH:
        try:
            if os.path.exists(FILE_AM_THANH):
                # Dừng nhạc cũ nếu đang chạy
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                
                pygame.mixer.music.load(FILE_AM_THANH)
                pygame.mixer.music.play()
            else:
                print(f"[!] Không tìm thấy file nhạc: {FILE_AM_THANH}")
        except Exception as e:
            print(f"[!] Lỗi phát nhạc: {e}")

def xu_ly_thanh_toan(con, plate_on):
    print(f"\n[XỬ LÝ] Tìm thấy xe: {plate_on}")
    user = tim_nguoi_theo_bien(con, plate_on)
    
    if user:
        if user['so_du'] >= PHI_THU_PHI:
            ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, True, "OK")
            print(f"   --> [OK] Chủ xe: {user['chu_xe']} | Trừ: {PHI_THU_PHI}đ | Còn: {user['so_du'] - PHI_THU_PHI}đ")
            
            # --- GỌI HÀM PHÁT NHẠC KHI THÀNH CÔNG ---
            phat_nhac_thanh_cong() 
            
            return f"MO CONG: {plate_on}", (0, 255, 0)
        else:
            ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, False, "KHONG_DU_SO_DU")
            print(f"   --> [FAIL] Không đủ tiền (Còn {user['so_du']}đ)")
            return "KHONG DU TIEN", (0, 165, 255)
    else:
        print(f"   --> [?] Biển số lạ chưa đăng ký")
        return "KHONG TON TAI", (0, 0, 255)

# --- HÀM NHẬN DIỆN (ĐÃ TỐI ƯU & BỎ CỬA SỔ DEBUG) ---
def nhan_dien_bien(anh):
    if anh is None: return "", anh
    xam = cv2.cvtColor(anh, cv2.COLOR_BGR2GRAY)
    th1 = cv2.adaptiveThreshold(xam, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    
    bien_so = ""
    khung_hien = anh.copy()
    
    cnts, _ = cv2.findContours(th1, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    for c in cnts:
        area = cv2.contourArea(c)
        if area > 1000: 
            x, y, w, h = cv2.boundingRect(c)
            ratio = w / h
            if 2.0 < ratio < 7.0: 
                cv2.rectangle(khung_hien, (x, y), (x + w, y + h), (0, 0, 255), 1)
                roi = xam[y:y+h, x:x+w]
                try:
                    txt = pytesseract.image_to_string(roi, config="--psm 7").strip()
                    txt_clean = re.sub(r'[^A-Z0-9-]', '', txt.upper())
                    
                    if len(txt_clean) > 5: 
                        bien_so = txt_clean
                        cv2.rectangle(khung_hien, (x, y), (x + w, y + h), (0, 255, 0), 2)
                        # print(f"[OCR]: {txt_clean}") 
                except: pass
                
    return bien_so, khung_hien

# --- MAIN ---
def main():
    # --- 3. KHỞI TẠO ÂM THANH ---
    if CO_AM_THANH:
        pygame.mixer.init()
        print("[LOA] Đã khởi tạo hệ thống âm thanh.")

    con = ket_noi_db()
    
    print(f"--- ĐANG KẾT NỐI: {URL_VIDEO} ---")
    cap = cv2.VideoCapture(URL_VIDEO)
    
    if not cap.isOpened():
        print("[LỖI] Không thể mở luồng video! Kiểm tra lại IP.")
        return

    buf_bien = deque(maxlen=8)
    cooldown_to = 0
    msg, color = "SAN SANG...", (255, 255, 255)
    
    frame_count = 0
    last_hinh_hien = None 
    last_bien = ""

    print(">>> HỆ THỐNG ĐÃ SẴN SÀNG (CÓ ÂM THANH) <<<")

    while True:
        ok, khung = cap.read()
        if not ok: 
            print("Mất tín hiệu..."); break
        
        khung = cv2.resize(khung, (800, 450))
        frame_count += 1
        
        # KỸ THUẬT GIẢM LAG: Quét mỗi 4 khung hình
        if frame_count % 4 == 0:
            bien, hinh_hien = nhan_dien_bien(khung)
            last_hinh_hien = hinh_hien 
            last_bien = bien
        else:
            hinh_hien = khung 
            bien = last_bien

        hien_tai = time.time()
        
        if bien:
            bn = chuan_hoa_bien(bien)
            if len(bn) > 5 and any(c.isdigit() for c in bn) and any(c.isalpha() for c in bn):
                buf_bien.append(bn)
            
        if buf_bien:
            plate_on, count = Counter(buf_bien).most_common(1)[0]
            if count >= 2 and hien_tai > cooldown_to:
                msg, color = xu_ly_thanh_toan(con, plate_on)
                cooldown_to = hien_tai + 5.0
                buf_bien.clear()

        if hien_tai < cooldown_to:
            cv2.putText(hinh_hien, msg, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
        else:
            cv2.putText(hinh_hien, "Dua bien so vao khung...", (30, 420), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

        cv2.imshow("ETC System (Audio Enabled)", hinh_hien)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'): break
        elif key == ord('s'): 
            print("[TEST] Giả lập xe vào!")
            msg, color = xu_ly_thanh_toan(con, "82A-081.23") 
            cooldown_to = hien_tai + 5.0

    cap.release()
    cv2.destroyAllWindows()
    con.close()

if __name__ == "__main__":
    main()