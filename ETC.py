import cv2, sqlite3, time, sys, re, os
import datetime as dt
import numpy as np
import urllib.request 
from collections import deque, Counter

# Cấu hình hiển thị tiếng Việt trên Console
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception: pass

# --- CẤU HÌNH CAMERA (Dựa trên ảnh bạn gửi) ---
IP_PHONE = "192.168.1.137"
URL_SNAPSHOT = f"http://{IP_PHONE}:8080/shot.jpg"

# --- CẤU HÌNH HỆ THỐNG ---
PHI_THU_PHI = 15000                                  
CHONG_LAP = 7.0         
TEN_TRAM = "TRAM_1"     
DUONG_DAN_DB = "du_lieu_etcv.db" 

import pytesseract
# Kiểm tra lại đường dẫn cài đặt Tesseract trên máy bạn
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def chuan_hoa_bien(s):
    if not s: return ""
    s = s.upper()
    s = s.translate(str.maketrans({'O':'0', 'Q':'0', 'I':'1', 'L':'1', 'T':'7', 'S':'5', 'B':'8', 'Z':'2'}))
    return re.sub(r'[^A-Z0-9]', '', s)

def ket_noi_db():
    return sqlite3.connect(DUONG_DAN_DB, check_same_thread=False)

def tim_nguoi_theo_bien(con, bien_so):
    bn = chuan_hoa_bien(bien_so)
    # Tìm xe trong DB, loại bỏ dấu chấm và gạch ngang để so sánh chính xác
    sql = "SELECT * FROM nguoi_dung WHERE REPLACE(REPLACE(REPLACE(UPPER(bien_so),'.',''),'-',''),' ','') = ?"
    cursor = con.cursor()
    cursor.execute(sql, (bn,))
    res = cursor.fetchone()
    if res:
        columns = [column[0] for column in cursor.description]
        return dict(zip(columns, res))
    return None

def ghi_giao_dich(con, uid, bien_so, so_tien, thanh_cong, ly_do):
    # Ghi vào bảng giao_dich
    con.execute("INSERT INTO giao_dich(thoi_gian,uid,bien_so,so_tien,ket_qua,ly_do,tram) VALUES(?,?,?,?,?,?,?)",
                (dt.datetime.now().isoformat(timespec="seconds"), uid, bien_so, -so_tien if thanh_cong else 0, "OK" if thanh_cong else "FAIL", ly_do, TEN_TRAM))
    # Trừ tiền trong bảng nguoi_dung nếu thành công
    if thanh_cong:
        con.execute("UPDATE nguoi_dung SET so_du = so_du - ? WHERE uid=?", (so_tien, uid))
    con.commit()

def lay_hinh_anh():
    """Hàm tải ảnh tĩnh từ IP Webcam (Giống như F5 trình duyệt)"""
    try:
        img_resp = urllib.request.urlopen(URL_SNAPSHOT, timeout=2)
        img_arr = np.array(bytearray(img_resp.read()), dtype=np.uint8)
        img = cv2.imdecode(img_arr, -1)
        return True, img
    except Exception as e:
        return False, None

def xu_ly_thanh_toan(con, plate_on):
    """Hàm xử lý trừ tiền chung cho cả Camera và phím S"""
    print(f"\n[XỬ LÝ] Đang kiểm tra xe: {plate_on}")
    user = tim_nguoi_theo_bien(con, plate_on)
    
    if user:
        if user['so_du'] >= PHI_THU_PHI:
            ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, True, "OK")
            print(f"[OK] {plate_on} | Chủ xe: {user['chu_xe']} | Trừ: {PHI_THU_PHI}đ | Còn: {user['so_du'] - PHI_THU_PHI}đ")
            return f"MO CONG: {plate_on}", (0, 255, 0) # Màu xanh
        else:
            ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, False, "KHONG_DU_SO_DU")
            print(f"[FAIL] {plate_on} | Không đủ tiền (Còn {user['so_du']}đ)")
            return "KHONG DU TIEN", (0, 165, 255) # Màu cam
    else:
        print(f"[?] Biển số lạ: {plate_on}")
        return "KHONG TON TAI", (0, 0, 255) # Màu đỏ

def nhan_dien_bien(anh):
    if anh is None: return "", anh
    xam = cv2.cvtColor(anh, cv2.COLOR_BGR2GRAY)
    _, th1 = cv2.threshold(xam, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bien_so, khung_hien = "", anh.copy()
    
    cnts, _ = cv2.findContours(th1, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        if cv2.contourArea(c) > 3000:
            x, y, w, h = cv2.boundingRect(c)
            ratio = w / h
            if 2.0 < ratio < 6.0: 
                cv2.rectangle(khung_hien, (x, y), (x + w, y + h), (0, 255, 0), 2)
                roi = xam[y:y+h, x:x+w]
                try:
                    txt = pytesseract.image_to_string(roi, config="--psm 7").strip()
                    if len(txt) > 5: bien_so = txt
                except: pass
    return bien_so, khung_hien

def main():
    con = ket_noi_db()
    buf_bien = deque(maxlen=5)
    cooldown_to = 0
    msg, color = "", (0, 255, 0)
    
    print(f"--- ĐANG KẾT NỐI CAMERA: {URL_SNAPSHOT} ---")
    
    # Test kết nối ngay khi khởi động
    ok, _ = lay_hinh_anh()
    if not ok:
        print(f"[!] LỖI KẾT NỐI: Không tìm thấy IP {IP_PHONE}")
        print("    -> Hãy đảm bảo điện thoại và máy tính chung Wi-Fi.")
        return
    else:
        print("[OK] Đã kết nối thành công!")
        print(">>> Hãy bấm chuột vào cửa sổ Camera rồi nhấn phím 'S' để thử trừ tiền <<<")

    while True:
        ok, khung = lay_hinh_anh()
        if not ok: 
            print("Mất kết nối..."); time.sleep(1); continue
        
        bien, hinh_hien = nhan_dien_bien(khung)
        hien_tai = time.time()
        
        # 1. Xử lý nhận diện tự động
        if bien:
            bn = chuan_hoa_bien(bien)
            if len(bn) > 5 and any(c.isdigit() for c in bn): buf_bien.append(bn)
            
        if buf_bien:
            plate_on, count = Counter(buf_bien).most_common(1)[0]
            if count >= 2 and hien_tai > cooldown_to:
                msg, color = xu_ly_thanh_toan(con, plate_on)
                cooldown_to = hien_tai + CHONG_LAP
                buf_bien.clear()

        # Hiển thị thông báo trên màn hình
        if msg and (hien_tai - cooldown_to < 3 or cooldown_to == 0): # Hiện trong 3 giây
            cv2.putText(hinh_hien, msg, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)

        # Resize cửa sổ cho gọn
        hinh_nho = cv2.resize(hinh_hien, (800, 450))
        cv2.imshow("He thong ETC (Nhan S de test)", hinh_nho)
        
        # 2. Xử lý phím bấm
        key = cv2.waitKey(30) & 0xFF
        if key == ord('q'): # Thoát
            break
        elif key == ord('s'): # Giả lập phím S
            print("\n[TEST] Bạn vừa nhấn phím S!")
            msg, color = xu_ly_thanh_toan(con, "82A-081.23") # Giả lập xe 82A
            cooldown_to = hien_tai + CHONG_LAP

    cv2.destroyAllWindows(); con.close()

if __name__ == "__main__":
    main()