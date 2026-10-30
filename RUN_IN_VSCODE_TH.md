# วิธีรันระบบการเงินห้อง 5/2 บน VS Code (Windows)

## 1) เปิดโปรเจกต์
1. แตก ZIP ไปยังโฟลเดอร์ที่ต้องการ
2. เปิด VS Code → File → Open Folder… → เลือกโฟลเดอร์ `class-finance`
3. เปิด Terminal → New Terminal

## 2) สร้าง virtual environment และติดตั้งแพ็กเกจ
รันทีละบรรทัดใน Terminal ของ VS Code (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

ถ้า PowerShell แจ้งว่าไม่อนุญาตให้รัน Activate.ps1 ให้ใช้คำสั่งนี้เฉพาะหน้าต่าง Terminal ปัจจุบัน แล้วลอง Activate อีกครั้ง:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 3) ตั้งค่าก่อนเปิดเว็บ
สร้างไฟล์ `.env` ที่โฟลเดอร์เดียวกับ `app.py` (คัดลอกจาก `.env.example`) แล้วกำหนดค่า `SECRET_KEY` และรหัสผู้เก็บเงินที่ปลอดภัย เช่น:

```env
SECRET_KEY=ใส่ค่าที่ยาวและสุ่ม
COLLECTOR_TOKENS=ฉัตร=รหัสของฉัตรที่ยาว8ตัวขึ้นไป,มีมี่=รหัสของมีมี่ที่ยาว8ตัวขึ้นไป,เพียว=รหัสของเพียวที่ยาว8ตัวขึ้นไป
SESSION_COOKIE_SECURE=0
TRUSTED_PROXIES=0
```

อย่าใช้รหัสตัวอย่างนี้เป็นรหัสจริง และอย่าแชร์ไฟล์ `.env` ให้ผู้อื่น ฐานข้อมูลจะถูกสร้าง/อัปเกรดอัตโนมัติใน `instance/finance.db` ตอนเริ่มแอป

## 4) รันเซิร์ฟเวอร์
ตรวจว่ามี `(.venv)` นำหน้าบรรทัด Terminal แล้วรัน:

```powershell
python -m flask --app app run --debug
```

เปิดเบราว์เซอร์ไปที่ `http://127.0.0.1:5000` ห้ามเปิด `index.html` ด้วยการดับเบิลคลิก เพราะแอปต้องรันผ่าน Flask

หยุดเซิร์ฟเวอร์: กลับไปที่ Terminal แล้วกด `Ctrl+C`

## 5) ตรวจการแก้ระบบรับเงิน
- ล็อกอินด้วยรหัสผู้เก็บเงินที่ตั้งไว้ใน `.env`
- ไปที่แท็บนักเรียน กรอกจำนวนเงินที่ได้รับ แล้วกด **รับเงิน**
- ตรวจหน้า Overview/รายรับและรายงานรายเดือน: รายรับต้องเพิ่มตามยอดที่รับ
- ตรวจประวัติการเรียกเก็บ/รับเงินและ Log ว่ามีรายการใหม่
- หากมีฐานข้อมูลเก่าที่เคยบันทึกการรับเงินแต่ไม่ได้สร้างรายรับ ระบบจะสร้างรายรับย้อนหลังให้ครั้งเดียวตอนเริ่มแอป

หลังแก้โค้ดแล้วให้รีเฟรชหน้าเว็บด้วย `Ctrl+F5` หากข้อมูลไม่อัปเดต ให้ตรวจ Terminal ว่ามี error หรือไม่ และตรวจว่าเปิดโปรเจกต์/ฐานข้อมูลชุดที่ถูกต้อง

## 6) รันทดสอบ (ถ้าติดตั้ง requirements-dev แล้ว)
```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```
