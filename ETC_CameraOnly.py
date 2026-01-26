import cv2, sqlite3, time, sys, re, os
import datetime as dt
import numpy as np
from collections import deque, Counter

# Cấu hình hệ thống để hiển thị tiếng Việt trên Console Windows
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception: pass

# --- CẤU HÌNH HỆ THỐNG ---
# Địa chỉ RTSP từ ứng dụng IP Camera của bạn
URL_CAMERA = "rtsp://admin:gnyAU/@10.47.173.174:8556"
PHI_THU_PHI = 15000                                  
CHONG_LAP = 7.0         # Giây (Thời gian giãn cách giữa các lần trừ tiền)
TEN_TRAM = "TRAM_1"     # Tên trạm mặc định [cite: 279]
DUONG_DAN_DB = "du_lieu_etcv.db" # Đường dẫn file database [cite: 279]

try:
    import pytesseract
    CO_OCR = True
except Exception:
    CO_OCR = False
    print("[!] Cảnh báo: Không tìm thấy pytesseract. Vui lòng cài đặt để nhận diện chữ.")

M_AO_BIEN = re.compile(r"[A-Z0-9\-\.]{5,12}") # Định dạng biển số [cite: 279]

# --- HÀM XỬ LÝ DỮ LIỆU ---

def chuan_hoa_bien(s: str) -> str:
    """Viết hoa và sửa lỗi OCR thường gặp[cite: 279]."""
    if not s: return ""
    s = s.upper()
    s = s.translate(str.maketrans({
        'O':'0', 'Q':'0', 'I':'1', 'L':'1', 'T':'7', 'S':'5', 'B':'8', 'Z':'2'
    }))
    return re.sub(r'[^A-Z0-9]', '', s)

def ket_noi_db():
    """Kết nối database SQLite[cite: 279]."""
    ket_noi = sqlite3.connect(DUONG_DAN_DB, check_same_thread=False)
    ket_noi.row_factory = sqlite3.Row
    return ket_noi

def tim_nguoi_theo_bien(con, bien_so):
    """Truy vấn chủ xe dựa trên biển số đã chuẩn hóa[cite: 279]."""
    bien_norm = chuan_hoa_bien(bien_so)
    sql = """
      SELECT * FROM nguoi_dung 
       WHERE trang_thai='hoat_dong' 
         AND REPLACE(REPLACE(REPLACE(UPPER(bien_so),'.',''),'-',''),' ','') = ?
    """
    return con.execute(sql, (bien_norm,)).fetchone()

def ghi_giao_dich(con, uid, bien_so, so_tien, thanh_cong, ly_do):
    """Ghi lịch sử vào bảng giao_dich và cập nhật số dư[cite: 35, 37]."""
    con.execute("""INSERT INTO giao_dich(thoi_gian,uid,bien_so,so_tien,ket_qua,ly_do,tram)
                   VALUES(?,?,?,?,?,?,?)""",
                (dt.datetime.now().isoformat(timespec="seconds"),
                 uid, bien_so,
                 -so_tien if thanh_cong else 0,
                 "OK" if thanh_cong else "FAIL",
                 ly_do, TEN_TRAM))
    if thanh_cong:
        con.execute("UPDATE nguoi_dung SET so_du = so_du - ? WHERE uid=?", (so_tien, uid))
    con.commit()

# --- HÀM XỬ LÝ HÌNH ẢNH ---

def warp_bang_bien(gray, box, out_size=(320, 120)):
    """Cắt và nắn thẳng vùng chứa biển số[cite: 279]."""
    pts = box.reshape(4,2).astype("float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl, br = pts[np.argmin(s)], pts[np.argmax(s)]
    tr, bl = pts[np.argmin(diff)], pts[np.argmax(diff)]
    dst = np.array([[0, 0], [out_size[0]-1, 0], [out_size[0]-1, out_size[1]-1], [0, out_size[1]-1]], dtype="float32")
    M = cv2.getPerspectiveTransform(np.array([tl,tr,br,bl], dtype="float32"), dst)
    return cv2.warpPerspective(gray, M, out_size)

def ocr_text(img_bin, psm=6):
    """Nhận diện ký tự từ ảnh nhị phân[cite: 279]."""
    if not CO_OCR: return ""
    cfg = f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-."
    raw = pytesseract.image_to_string(img_bin, config=cfg).upper().replace(" ","").strip()
    m = M_AO_BIEN.findall(raw)
    return "-".join(m) if m else ""

def nhan_dien_bien(anh):
    """Tìm và đọc biển số trong khung hình[cite: 279]."""
    xam = cv2.cvtColor(anh, cv2.COLOR_BGR2GRAY)
    xam = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(xam)
    mag = cv2.convertScaleAbs(cv2.magnitude(cv2.Scharr(xam, cv2.CV_32F, 1, 0), cv2.Scharr(xam, cv2.CV_32F, 0, 1)))
    _, th1 = cv2.threshold(mag, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    bien_so, khung_hien = "", anh.copy()
    H, W = xam.shape[:2]
    cnts, _ = cv2.findContours(cv2.morphologyEx(th1, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5,3)), iterations=2), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_box, best_is_sq = None, False
    max_score = -1
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 0.0025 * W * H: continue
        rect = cv2.minAreaRect(c)
        (rw, rh) = rect[1]
        if rw == 0 or rh == 0: continue
        ratio = max(rw, rh) / min(rw, rh)
        is_r, is_s = (2.0 <= ratio <= 6.5), (0.85 <= ratio <= 1.35)
        if (is_r or is_s) and area * (2.0 if is_s else 1.0) > max_score:
            max_score, best_box, best_is_sq = area * (2.0 if is_s else 1.0), cv2.boxPoints(rect), is_s

    if best_box is not None:
        warped = warp_bang_bien(xam, best_box, (240, 240) if best_is_sq else (360, 120))
        _, binv = cv2.threshold(warped, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bien_so = ocr_text(binv, psm=6 if best_is_sq else 7)
        if bien_so:
            cv2.polylines(khung_hien, [best_box.astype(int)], True, (0,255,0), 2)
            cv2.putText(khung_hien, bien_so, (int(best_box[0][0]), int(best_box[0][1])-10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
    return bien_so, khung_hien

# --- HÀM CHÍNH ---

def main():
    con = ket_noi_db()
    camera = cv2.VideoCapture(URL_CAMERA)
    
    # Hàng đợi để kiểm tra độ ổn định của biển số
    buf_bien = deque(maxlen=6)
    cooldown_to = 0
    
    print(f"--- ĐANG KẾT NỐI RTSP: {URL_CAMERA} ---")
    if not camera.isOpened():
        print("[!] Không thể kết nối camera. Vui lòng kiểm tra lại địa chỉ hoặc Wi-Fi.")
        return

    while True:
        ret, khung = camera.read()
        if not ret: 
            print("[!] Mất kết nối luồng video."); break
        
        bien, hinh_hien = nhan_dien_bien(khung)
        hien_tai = time.time()
        
        # Nhấn S để giả lập biển số demo [cite: 279]
        if cv2.waitKey(1) & 0xFF == ord('s'): 
            bien = "82A-081.23"

        if bien:
            bn = chuan_hoa_bien(bien)
            if bn: buf_bien.append(bn)

        # Xử lý khi có biển số xuất hiện ổn định (>= 3 lần trong buffer)
        if buf_bien:
            plate_on, count = Counter(buf_bien).most_common(1)[0]
            if count >= 3 and hien_tai > cooldown_to:
                user = tim_nguoi_theo_bien(con, plate_on)
                
                print(f"\n[PHÁT HIỆN] Biển số: {plate_on}")
                if user:
                    if user['so_du'] >= PHI_THU_PHI:
                        # Thực hiện trừ tiền và mở cổng (giả lập)
                        ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, True, "OK") [cite: 35, 37]
                        print(f"[✓] Thành công: {user['chu_xe']} | Số dư còn: {user['so_du'] - PHI_THU_PHI}đ")
                        msg, color = f"OK - MO CONG: {plate_on}", (0, 255, 0)
                    else:
                        ghi_giao_dich(con, user['uid'], plate_on, PHI_THU_PHI, False, "KHONG_DU_SO_DU") [cite: 35, 161]
                        print(f"[×] Không đủ tiền: {user['so_du']}đ")
                        msg, color = "KHONG DU SO DU", (0, 165, 255)
                else:
                    print(f"[?] Biển số không có trong hệ thống: {plate_on}")
                    msg, color = "BIEN KHONG TON TAI", (0, 0, 255)
                
                # Hiển thị thông báo lên màn hình Video
                cv2.putText(hinh_hien, msg, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
                cooldown_to = hien_tai + CHONG_LAP
                buf_bien.clear()

        cv2.imshow("He thong ETC - Camera Only Mode", hinh_hien)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    camera.release()
    cv2.destroyAllWindows()
    con.close()

if __name__ == "__main__":
    main()