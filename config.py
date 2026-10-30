"""config.py — ค่าตั้งค่าของระบบการเงินห้อง 5/2 (อ่านจากตัวแปรสภาพแวดล้อม / ไฟล์ .env)"""
import os
import secrets
from datetime import timedelta

try:                      # อ่านไฟล์ .env (gunicorn ไม่อ่านให้เอง)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # กุญแจเซ็นต์ session: ควรตั้งใน .env (ถ้าไม่ตั้ง จะสุ่มใหม่ทุกครั้งที่เริ่มเซิร์ฟเวอร์ ทุกคนจะถูกให้ล็อกอินใหม่)
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SECRET_KEY_MISSING = not os.environ.get("SECRET_KEY")
    # รหัสผู้เก็บเงินตอนสร้างฐานข้อมูลครั้งแรก: "ฉัตร=รหัส1,มีมี่=รหัส2,เพียว=รหัส3" (รหัสยาว >= 8 ตัวอักษร)
    COLLECTOR_TOKENS = os.environ.get("COLLECTOR_TOKENS", "")
    TIMEZONE = os.environ.get("TIMEZONE", "Asia/Bangkok")
    # จำนวน reverse proxy ที่เชื่อถือ (Render/Fly/nginx = 1) เพื่ออ่าน IP จริงของผู้ใช้; 0 = ไม่มี proxy
    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "0") or 0)
    # ไฟล์ฐานข้อมูล SQLite (ค่าเริ่มต้นอยู่ในโฟลเดอร์ instance/)
    DATABASE = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "instance", "finance.db"))
    # โฟลเดอร์เก็บไฟล์หลักฐาน: ค่าเริ่มต้นอยู่ข้าง ๆ ไฟล์ฐานข้อมูล (บน Docker/Render จะเป็น /data/evidence ซึ่งอยู่บน disk ถาวร)
    EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR") or os.path.join(os.path.dirname(DATABASE), "evidence")
    # ขีดจำกัดหลักฐาน: ขนาดต่อไฟล์ (ไบต์), จำนวนไฟล์ต่อรายการ
    MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
    MAX_EVIDENCE_PER_TX = 5
    # เพดานขนาด request ทั้งหมด (ไฟล์ + ส่วนหัว multipart) ถ้าเกินจะถูกตอบ 413 ทันที
    MAX_CONTENT_LENGTH = MAX_EVIDENCE_BYTES + 256 * 1024

    # ความปลอดภัยของ cookie (ตั้ง SESSION_COOKIE_SECURE=1 เมื่อใช้ HTTPS)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)   # ล็อกอินค้างได้ 8 ชั่วโมง

    LOGIN_MAX_FAILS = 5        # ใส่รหัสผิดได้กี่ครั้งต่อ IP ...
    LOGIN_WINDOW_SEC = 60      # ... ภายในกี่วินาที ก่อนถูกล็อกชั่วคราว
    ACTION_COOLDOWN_MS = 1500  # การกระทำเดิมของคนเดิมต้องห่างกันอย่างน้อยกี่ มิลลิวินาที (กันกดรัว)
