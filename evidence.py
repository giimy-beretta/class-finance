"""evidence.py — ตัวช่วยจัดการไฟล์หลักฐานการจ่ายเงิน (รูปหรือ PDF ที่แนบกับรายจ่าย)

- detect_type(): ดูชนิดไฟล์จาก "เนื้อไฟล์จริง" (signature / magic bytes) ไม่เชื่อนามสกุลหรือ Content-Type ที่ผู้ใช้ส่งมา
- new_stored_name(): ตั้งชื่อไฟล์บนดิสก์เป็นตัวสุ่ม ไม่ใช้ชื่อจากผู้ใช้ (กันการเขียน/อ่านไฟล์นอกโฟลเดอร์)
- clean_display_name(): ทำความสะอาดชื่อที่จะแสดง และให้นามสกุลตรงกับชนิดไฟล์จริง
- is_valid_stored_name(): ตรวจรูปแบบชื่อไฟล์บนดิสก์ก่อนเปิดอ่าน

โมดูลนี้ไม่พึ่ง Flask/ฐานข้อมูล เพื่อให้ทดสอบแยกได้ง่าย
"""
import re
import secrets
from pathlib import PurePosixPath, PureWindowsPath

# ตัวอักษรที่ห้ามอยู่ในชื่อที่แสดง (ควบคุม, อักขระพิเศษของระบบไฟล์ และ HTML)
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
# รูปแบบชื่อไฟล์บนดิสก์ที่เราสร้างเอง: เลขฐานสิบหก 32 ตัว + นามสกุลที่อนุญาต
_STORED_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|gif|webp|pdf)$")


def detect_type(data):
    """คืน (นามสกุล, MIME) ถ้าเนื้อไฟล์เป็น JPG / PNG / GIF / WEBP / PDF จริง ไม่เช่นนั้นคืน None"""
    head = data[:16]
    if head[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp", "image/webp"
    if head[:5] == b"%PDF-":
        return "pdf", "application/pdf"
    return None


def new_stored_name(ext):
    """ชื่อไฟล์ที่เก็บบนดิสก์: สุ่ม 128 บิต + นามสกุลที่ระบบกำหนดเอง"""
    return secrets.token_hex(16) + "." + ext


def is_valid_stored_name(name):
    """True ถ้าชื่อไฟล์ตรงรูปแบบที่ระบบสร้าง (ป้องกันการส่งชื่อแปลก ๆ มาอ่านไฟล์)"""
    return bool(_STORED_RE.match(name or ""))


def clean_display_name(name, ext):
    """ทำชื่อที่แสดงให้สะอาด: ตัดโฟลเดอร์ออก (รองรับทั้ง / และ \\) ลบอักขระอันตราย และให้นามสกุลตรงกับชนิดจริง"""
    base = PurePosixPath(PureWindowsPath(str(name or "")).name).name
    base = _BAD_CHARS.sub("", base).strip().strip(".")
    stem = base.rsplit(".", 1)[0] if "." in base else base
    stem = stem.strip()[:80] or "หลักฐาน"
    return f"{stem}.{ext}"
