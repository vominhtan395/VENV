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

# --- CẤU HÌNH FILE ÂM THANH ---
FILE_AM_THANH = "thanhcong.mp3"             # Nhạc khi trừ tiền thành công (OK)
FILE_AM_THANH_TRUNG = "canhbao.mp3"         # Nhạc báo xe đã giao dịch rồi (Trùng)
FILE_AM_THANH_KHONG_CO = "khongtimthay.mp3" # Nhạc khi biển số lạ
FILE_AM_THANH_KHONG_DU_TIEN = "khongdutien.mp3" # <--- MỚI: Nhạc khi không đủ số dư

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

# --- 2. CÁC HÀM PHÁT NHẠC ---
def phat_nhac_thanh_cong():
    if CO_AM_THANH:
        try:
            if os.path.exists(FILE_AM_THANH):
                if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
                pygame.mixer.music.load(FILE_AM_THANH)
                pygame.mixer.music.play()
            else:
                print(f"[!] Không tìm thấy file nhạc: {FILE_AM_THANH}")
        except Exception as e: print(f"[!] Lỗi phát nhạc: {e}")

def phat_nhac_canh_bao():
    if CO_AM_THANH:
        try:
            if os.path.exists(FILE_AM_THANH_TRUNG):
                if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
                pygame.mixer.music.load(FILE_AM_THANH_TRUNG)
                pygame.mixer.music.play()
            else:
                print(f"[!] Không tìm thấy file nhạc: {FILE_AM_THANH_TRUNG}")
        except Exception as e: print(f"[!] Lỗi phát nhạc cảnh báo: {e}")

def phat_nhac_khong_co():
    if CO_AM_THANH:
        try:
            if os.path.exists(FILE_AM_THANH_KHONG_CO):
                if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
                pygame.mixer.music.load(FILE_AM_THANH_KHONG_CO)
                pygame.mixer.music.play()
            else:
                print(f"[!] Không tìm thấy file nhạc: {FILE_AM_THANH_KHONG_CO}")
        except Exception as e: print(f"[!] Lỗi phát nhạc không có: {e}")

# --- HÀM PHÁT NHẠC KHÔNG ĐỦ TIỀN (MỚI) ---
def phat_nhac_khong_du_tien():
    if CO_AM_THANH:
        try:
            if os.path.exists(FILE_AM_THANH_KHONG_DU_TIEN):
                if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
                pygame.mixer.music.load(FILE_AM_THANH_KHONG_DU_TIEN)
                pygame.mixer.music.play()
            else:
                print(f"[!] Không tìm thấy file nhạc: {FILE_AM_THANH_KHONG_DU_TIEN}")
        except Exception as e: print(f"[!] Lỗi phát nhạc không đủ tiền: {e}")

def xu_ly_thanh_toan(con, plate_on):
    print(f"\n[XỬ LÝ] Tìm thấy xe: {plate_on}")
    user = tim_nguoi_theo_bien(con, plate_on)
    
    if user:
        # Kiểm tra số dư
        if user['so_du'] >= PHI_THU_PHI:
            ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, True, "OK")
            print(f"   --> [OK] Chủ xe: {user['chu_xe']} | Trừ: {PHI_THU_PHI}đ | Còn: {user['so_du'] - PHI_THU_PHI}đ")
            
            # --- GỌI HÀM PHÁT NHẠC KHI THÀNH CÔNG ---
            phat_nhac_thanh_cong() 
            
            return f"MO CONG: {plate_on}", (0, 255, 0)
        else:
            # Logic: Không đủ tiền -> FAIL
            ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, False, "KHONG_DU_SO_DU")
            print(f"   --> [FAIL] Không đủ tiền (Còn {user['so_du']}đ)")
            
            # --- GỌI HÀM PHÁT NHẠC KHÔNG ĐỦ TIỀN (MỚI) ---
            phat_nhac_khong_du_tien()
            
            return "KHONG DU TIEN", (0, 165, 255) # Màu cam
    else:
        # --- TRƯỜNG HỢP KHÔNG CÓ TRONG DATABASE ---
        print(f"   --> [?] Biển số lạ chưa đăng ký")
        
        # Gọi hàm phát nhạc báo lỗi không tìm thấy
        phat_nhac_khong_co()
        
        return "KHONG TON TAI", (0, 0, 255) # Màu đỏ

# --- HÀM NHẬN DIỆN (ĐÃ TỐI ƯU) ---
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
                except: pass
                
    return bien_so, khung_hien

# --- MAIN ---
def main():
    # --- KHỞI TẠO ÂM THANH ---
    if CO_AM_THANH:
        pygame.mixer.init()
        print("[LOA] Đã khởi tạo hệ thống âm thanh.")

    con = ket_noi_db()
    
    print(f"--- ĐANG KẾT NỐI: {URL_VIDEO} ---")
    cap = cv2.VideoCapture(URL_VIDEO)
    
    # [FIX DELAY] Thiết lập bộ đệm camera xuống 1 để lấy hình mới nhất
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 
    
    if not cap.isOpened():
        print("[LỖI] Không thể mở luồng video! Kiểm tra lại IP.")
        return

    xe_da_qua_tram = set() 
    msg, color = "CHO QUET...", (255, 255, 255)
    
    thoi_gian_hien_thong_bao = 0 
    bien_hien_tai = "" 
    
    # Biến đếm khung hình để tối ưu hiển thị
    frame_count = 0
    last_hinh_hien = None
    last_bien = ""

    print(">>> HỆ THỐNG SẴN SÀNG - BẤM PHÍM 'CÁCH' (SPACE) ĐỂ QUÉT <<<")

    while True:
        ok, khung = cap.read()
        if not ok: 
            print("Mất tín hiệu..."); break
        
        khung = cv2.resize(khung, (800, 450))
        hien_tai = time.time()
        frame_count += 1
        
        # [TỐI ƯU] Chỉ chạy nhận diện để vẽ khung xanh mỗi 5 frame
        if frame_count % 5 == 0:
            bien_so_nhan_dien, hinh_hien = nhan_dien_bien(khung)
            last_hinh_hien = hinh_hien
            last_bien = bien_so_nhan_dien
        else:
            hinh_hien = khung if last_hinh_hien is None else last_hinh_hien
            bien_so_nhan_dien = last_bien
        
        if bien_so_nhan_dien:
            bien_hien_tai = chuan_hoa_bien(bien_so_nhan_dien)
        else:
            bien_hien_tai = ""

        # XỬ LÝ PHÍM BẤM
        key = cv2.waitKey(1) & 0xFF
        
        if key == 32: # SPACE (Phím Cách)
            # Khi bấm phím, ta nhận diện lại TRỰC TIẾP trên khung hình hiện tại để chính xác nhất
            bien_chuan_xac, _ = nhan_dien_bien(khung)
            bien_check = chuan_hoa_bien(bien_chuan_xac)

            if bien_check:
                # 1. Kiểm tra trùng lặp (Đã qua trạm thành công chưa)
                if bien_check in xe_da_qua_tram:
                    msg = f"DA GIAO DICH: {bien_check}"
                    color = (0, 0, 255) # Màu đỏ
                    print(f"[CẢNH BÁO] Biển số {bien_check} đã giao dịch trước đó!")
                    
                    # --- GỌI HÀM PHÁT NHẠC CẢNH BÁO ---
                    phat_nhac_canh_bao()
                    
                else:
                    # 2. Chưa trùng -> Xử lý thanh toán
                    msg_kq, color_kq = xu_ly_thanh_toan(con, bien_check)
                    msg = msg_kq
                    color = color_kq
                    
                    # 3. CHỈ KHI "MO CONG" (Thành công) mới thêm vào danh sách
                    if "MO CONG" in msg or "OK" in msg:
                        xe_da_qua_tram.add(bien_check)
            else:
                msg = "KHONG THAY BIEN SO"
                color = (0, 255, 255)
            
            thoi_gian_hien_thong_bao = hien_tai + 3.0

        elif key == ord('q'): 
            break
        elif key == ord('r'): # Reset danh sách
            xe_da_qua_tram.clear()
            print("[RESET] Đã xóa danh sách xe đã qua trạm.")
            msg = "DA RESET LIST"
            thoi_gian_hien_thong_bao = hien_tai + 2.0

        # Hiển thị thông báo
        if hien_tai < thoi_gian_hien_thong_bao:
            cv2.putText(hinh_hien, msg, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
        else:
            cv2.putText(hinh_hien, "Bam SPACE de quet...", (30, 420), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            if bien_hien_tai:
                 cv2.putText(hinh_hien, f"Phat hien: {bien_hien_tai}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        cv2.imshow("ETC System (Manual - Fix Delay)", hinh_hien)

    cap.release()
    cv2.destroyAllWindows()
    con.close()

if __name__ == "__main__":
    main()