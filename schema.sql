-- schema.sql — โครงสร้างฐานข้อมูล SQLite ของระบบการเงินห้อง 5/2
-- เงินเก็บเป็นจำนวนเต็ม "สตางค์" (amount_satang) เพื่อไม่ให้เกิดความคลาดเคลื่อนของทศนิยม
-- การลบทุกอย่างเป็น soft delete (deleted_at_ms) เพื่อเก็บประวัติไว้เสมอ

-- ผู้เก็บเงิน (เก็บเฉพาะ hash ของรหัส)
CREATE TABLE IF NOT EXISTS collectors (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT UNIQUE NOT NULL,
  token_hash  TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1
);

-- นักเรียน เลขที่ 1-21
CREATE TABLE IF NOT EXISTS students (
  student_no  INTEGER PRIMARY KEY,
  full_name   TEXT NOT NULL
);

-- รายรับ-รายจ่าย (kind: in = รายรับ, out = รายจ่าย)
CREATE TABLE IF NOT EXISTS transactions (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  kind           TEXT NOT NULL CHECK (kind IN ('in','out')),
  tx_date        TEXT NOT NULL,                       -- รูปแบบ YYYY-MM-DD
  item           TEXT NOT NULL,
  category       TEXT NOT NULL DEFAULT 'ไม่ระบุกลุ่ม',
  amount_satang  INTEGER NOT NULL CHECK (amount_satang > 0),
  note           TEXT,
  created_by     INTEGER REFERENCES collectors(id),   -- NULL = ข้อมูลนำเข้าตอนเริ่มระบบ
  created_at_ms  INTEGER NOT NULL,
  deleted_at_ms  INTEGER,
  deleted_by     INTEGER REFERENCES collectors(id)
);

-- การเรียกเก็บเงินรายสัปดาห์ (ทุกคนเท่ากัน) — เรียกซ้ำได้ ยอดค้างจะทบเพิ่ม
CREATE TABLE IF NOT EXISTS charges (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  charge_date    TEXT NOT NULL,
  amount_satang  INTEGER NOT NULL CHECK (amount_satang > 0),
  created_by     INTEGER NOT NULL REFERENCES collectors(id),
  created_at_ms  INTEGER NOT NULL,
  deleted_at_ms  INTEGER,
  deleted_by     INTEGER REFERENCES collectors(id)
);

-- การรับเงินรายคน
CREATE TABLE IF NOT EXISTS payments (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  student_no     INTEGER NOT NULL REFERENCES students(student_no),
  amount_satang  INTEGER NOT NULL CHECK (amount_satang > 0),
  pay_date       TEXT NOT NULL,
  created_by     INTEGER NOT NULL REFERENCES collectors(id),
  created_at_ms  INTEGER NOT NULL,
  deleted_at_ms  INTEGER,
  deleted_by     INTEGER REFERENCES collectors(id),
  transaction_id INTEGER REFERENCES transactions(id)  -- รายรับที่สร้างอัตโนมัติจากการรับเงินนี้
);

-- หลักฐานการจ่ายเงิน (รูป/PDF ที่แนบกับรายจ่าย) — ตัวไฟล์เก็บบนดิสก์ใน EVIDENCE_DIR ไม่ได้เก็บในฐานข้อมูล
-- การลบเป็น soft delete: ซ่อนจากหน้าเว็บ แต่ไฟล์และประวัติยังอยู่
CREATE TABLE IF NOT EXISTS evidence (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  transaction_id  INTEGER NOT NULL REFERENCES transactions(id),
  stored_name     TEXT NOT NULL UNIQUE,      -- ชื่อไฟล์บนดิสก์ (สุ่ม) ไม่ใช่ชื่อที่ผู้ใช้ตั้ง
  display_name    TEXT NOT NULL,             -- ชื่อที่แสดงให้ผู้ใช้เห็น (ทำความสะอาดแล้ว)
  mime_type       TEXT NOT NULL,
  size_bytes      INTEGER NOT NULL,
  sha256          TEXT NOT NULL,             -- ลายนิ้วมือไฟล์ ใช้ตรวจว่าไฟล์ไม่ถูกแก้ไขภายหลัง
  created_by      INTEGER NOT NULL REFERENCES collectors(id),
  created_at_ms   INTEGER NOT NULL,
  deleted_at_ms   INTEGER,
  deleted_by      INTEGER REFERENCES collectors(id)
);

-- บันทึกการแก้ไข: ใครทำอะไรเมื่อไร (email ผู้ใช้กรอกเองตอนล็อกอิน ระบบไม่ได้ยืนยัน)
CREATE TABLE IF NOT EXISTS audit_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  at_ms           INTEGER NOT NULL,
  collector_id    INTEGER REFERENCES collectors(id),
  collector_name  TEXT,
  action          TEXT NOT NULL,
  table_name      TEXT,
  record_id       TEXT,
  detail          TEXT,
  email           TEXT
);

-- บันทึกการใส่รหัสผิด (ใช้จำกัดความถี่ต่อ IP)
CREATE TABLE IF NOT EXISTS auth_failures (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ip     TEXT NOT NULL,
  at_ms  INTEGER NOT NULL
);

-- audit_log เพิ่มได้อย่างเดียว: ห้ามแก้ไข/ลบ
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE INDEX IF NOT EXISTS idx_tx_date     ON transactions(tx_date);
CREATE INDEX IF NOT EXISTS idx_pay_student ON payments(student_no);
CREATE INDEX IF NOT EXISTS idx_audit_act   ON audit_log(collector_id, action, at_ms);
CREATE INDEX IF NOT EXISTS idx_fail_ip     ON auth_failures(ip, at_ms);
CREATE INDEX IF NOT EXISTS idx_evidence_tx ON evidence(transaction_id);
