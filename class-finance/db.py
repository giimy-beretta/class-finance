"""db.py — เชื่อมต่อ SQLite, สร้างตาราง, ใส่ข้อมูลเริ่มต้น และคำสั่ง CLI (init-db / set-token)"""
import os
import sqlite3
import time

import click
from flask import current_app, g
from flask.cli import with_appcontext
from werkzeug.security import check_password_hash, generate_password_hash

# ---------- ข้อมูลเริ่มต้น ----------
STUDENTS = [
    "ธนากร คงสวัสดิ์", "สุทธิลักษณ์ กวางไพร", "พีรพล บุญประกอบ", "อนันต์ธรรม มีเย็น", "อวิยรัช มาลี",
    "กษิเดช ปอสูงเนิน", "ภัทรพล นันทะกุล", "เกียรติศักดิ์ ทองช้าง", "เมธาวินทร์ ไตรทิพย์", "ธรรม โซตรง",
    "กลัส ตีวารี", "ณัฐธยาน์ เลิศปัญญา", "ยุวดี แก้วเทศ", "วรินดา เหล่านพกุล", "วรพร แซ่โง้ว",
    "พิชญาภา จันทร์โฮง", "กัญญาณัฐ แซ่กอ", "จุฑารัตน์ อาจศัตรู", "อริสดา พันธุชาติ", "เบร์รินทร์", "เอื้อการย์ ทองนวล",
]
# รหัสเริ่มต้นของผู้เก็บเงิน — ต้องเปลี่ยนด้วยคำสั่ง `flask --app app set-token <ชื่อ>` ก่อนใช้งานจริง
DEFAULT_COLLECTORS = {"ฉัตร": "token-1", "มีมี่": "token-2", "เพียว": "token-3"}
# รายรับที่สร้างอัตโนมัติเมื่อรับเงินนักเรียน (ใช้ชื่อเดียวกับรายการ "เก็บเงินห้อง" เดิม เพื่อให้รวมในหมวดเดียวกัน)
PAYMENT_ITEM = "1.1 เก็บเงินห้อง"
PAYMENT_CATEGORY = "รายได้รายอาทิตย์"
# รายรับ-รายจ่ายเดิม: (ประเภท, วันที่, รายการ, หมวดหมู่, บาท, หมายเหตุ)
BASE_TX = [
    ("in", "2026-05-22", "1.3 คงเหลือจาก ม.4", "รายได้อื่นๆ", 2874, "เงินคงเหลือรวมจาก ม.4"),
    ("in", "2026-05-25", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 220, "จ่ายมา 11 คน เหลืออีก 10"),
    ("in", "2026-05-25", "1.4 เงินใครตกไม่รู้", "รายได้อื่นๆ", 5, None),
    ("in", "2026-05-26", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 210, None),
    ("in", "2026-06-08", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 210, None),
    ("in", "2026-06-16", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 160, None),
    ("in", "2026-06-16", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 50, None),
    ("in", "2026-06-25", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 210, None),
    ("in", "2026-07-03", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 210, None),
    ("in", "2026-07-06", "1.1 เก็บเงินห้อง", "รายได้รายอาทิตย์", 210, None),
    ("in", "2026-08-07", "1.4 เงินใครตกไม่รู้", "รายได้อื่นๆ", 5, None),
    ("in", "2026-08-07", "1.6 เงินผิดระเบียบ", "รายได้ผิดระเบียบ", 20, None),
    ("out", "2026-05-22", "1.1 กิจกรรมวันงดสูบบุหรี่", "รายจ่ายใช้ในกิจกรรม", 65, "นำไปซื้อฟิวเจอร์บอร์ด"),
    ("out", "2026-05-29", "1.6 กิจกรรมพานไหว้ครู", "รายจ่ายใช้ในกิจกรรม", 150, None),
    ("out", "2026-06-16", "1.6 กิจกรรมพานไหว้ครู", "รายจ่ายใช้ในกิจกรรม", 30, None),
    ("out", "2026-06-16", "1.5 กิจกรรมกีฬาสี", "รายจ่ายใช้ในกิจกรรม", 193, "ค่าเดินทางไปคุยสัญญา ไป-กลับ"),
    ("out", "2026-06-19", "1.7 บอร์ดห้อง", "ไม่ระบุกลุ่ม", 110, None),
    ("out", "2026-06-25", "1.2 กิจกรรมจับสายรหัส", "รายจ่ายใช้ในกิจกรรม", 90, "มะนาว มะระ"),
    ("out", "2026-06-29", "1.5 กิจกรรมกีฬาสี", "รายจ่ายใช้ในกิจกรรม", 1666, "ค่ามัดจำ"),
]


def now_ms():
    """เวลาปัจจุบันเป็นมิลลิวินาที"""
    return int(time.time() * 1000)


def get_db():
    """คืนการเชื่อมต่อฐานข้อมูลของ request นี้ (สร้างครั้งเดียวต่อ request)"""
    if "db" not in g:
        path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        g.db = sqlite3.connect(path, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")   # บังคับ foreign key
        g.db.execute("PRAGMA busy_timeout = 15000")   # หลาย worker เขียนพร้อมกัน: รอคิวแทนที่จะ error
    return g.db


def close_db(_exc=None):
    """ปิดการเชื่อมต่อเมื่อจบ request"""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    """สร้างตารางตาม schema.sql + อัปเกรดฐานข้อมูลเก่า (รันซ้ำได้ ข้อมูลเดิมไม่หาย)"""
    conn = get_db()
    conn.execute("PRAGMA journal_mode = WAL")   # อ่านพร้อมเขียนได้ เหมาะกับหลาย worker
    with current_app.open_resource("schema.sql") as f:
        conn.executescript(f.read().decode("utf8"))
    migrate(conn)


def migrate(conn):
    """อัปเกรดฐานข้อมูลเวอร์ชันเก่า: เพิ่ม payments.transaction_id แล้วสร้างรายรับย้อนหลังให้การรับเงินที่เคยตกหล่น"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(payments)")}
    if "transaction_id" not in cols:
        conn.execute("ALTER TABLE payments ADD COLUMN transaction_id INTEGER REFERENCES transactions(id)")
    orphans = conn.execute(
        "SELECT p.*, s.full_name FROM payments p JOIN students s ON s.student_no = p.student_no "
        "WHERE p.transaction_id IS NULL AND p.deleted_at_ms IS NULL").fetchall()
    for p in orphans:   # การรับเงินที่เคยบันทึกแต่ไม่เข้ารายรับ (บัคเดิม) -> สร้างรายรับให้ครั้งเดียว
        tx = conn.execute(
            "INSERT INTO transactions(kind, tx_date, item, category, amount_satang, note, created_by, created_at_ms) "
            "VALUES ('in', ?, ?, ?, ?, ?, ?, ?)",
            (p["pay_date"], PAYMENT_ITEM, PAYMENT_CATEGORY, p["amount_satang"],
             f"เลขที่ {p['student_no']} {p['full_name']}", p["created_by"], p["created_at_ms"]))
        conn.execute("UPDATE payments SET transaction_id = ? WHERE id = ?", (tx.lastrowid, p["id"]))
        conn.execute(
            "INSERT INTO audit_log(at_ms, collector_id, collector_name, action, table_name, record_id, detail) "
            "VALUES (?, NULL, 'ระบบ', 'fix_payment_income', 'payments', ?, ?)",
            (now_ms(), str(p["id"]),
             f"แก้ข้อมูลย้อนหลัง: บันทึกรายรับให้การรับเงิน เลขที่ {p['student_no']} {p['amount_satang'] / 100:,.2f} บาท"))
    conn.commit()


def bootstrap(app):
    """เรียกตอนเริ่มระบบ: สร้าง/อัปเกรดฐานข้อมูล และใส่ข้อมูลเริ่มต้นเมื่อยังว่าง
    ผู้เก็บเงินคนแรกตั้งรหัสผ่านตัวแปร COLLECTOR_TOKENS="ฉัตร=รหัส1,มีมี่=รหัส2,เพียว=รหัส3" (อย่างน้อย 8 ตัวอักษร)
    ใช้งานจริงห้ามเหลือรหัสเริ่มต้น token-1..3 — ระบบจะไม่ยอมเริ่มทำงาน"""
    init_db()
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM collectors").fetchone()[0] == 0:
        tokens = parse_tokens(app.config["COLLECTOR_TOKENS"]) or (DEFAULT_COLLECTORS if app.debug else {})
        seed_data(tokens)
    if not app.debug and not app.config["TESTING"]:
        weak = [r["name"] for r in conn.execute("SELECT * FROM collectors WHERE active = 1")
                if any(check_password_hash(r["token_hash"], t) for t in DEFAULT_COLLECTORS.values())]
        if weak:
            raise RuntimeError(
                f"ผู้เก็บเงิน {', '.join(weak)} ยังใช้รหัสเริ่มต้น — ตั้งรหัสใหม่ด้วย `flask --app app set-token <ชื่อ>` "
                "(หรือใส่ COLLECTOR_TOKENS ตอนสร้างฐานข้อมูลใหม่) ก่อนเปิดใช้งานจริง")
        if not conn.execute("SELECT 1 FROM collectors WHERE active = 1").fetchone():
            raise RuntimeError("ยังไม่มีผู้เก็บเงิน — ตั้งตัวแปร COLLECTOR_TOKENS แล้วเริ่มระบบใหม่")


def parse_tokens(text):
    """แปลง "ชื่อ=รหัส,ชื่อ=รหัส" เป็น dict (ข้ามรหัสที่สั้นกว่า 8 ตัวอักษร)"""
    out = {}
    for part in (text or "").split(","):
        name, _, token = part.partition("=")
        name, token = name.strip(), token.strip()
        if name and len(token) >= 8:
            out[name] = token
    return out


def seed_data(collectors=None):
    """ใส่นักเรียน ผู้เก็บเงิน และรายรับ-รายจ่ายเดิม (ไม่ซ้ำถ้ามีอยู่แล้ว)"""
    collectors = DEFAULT_COLLECTORS if collectors is None else collectors
    conn = get_db()
    conn.executemany("INSERT OR IGNORE INTO students(student_no, full_name) VALUES (?, ?)",
                     list(enumerate(STUDENTS, start=1)))
    for name, token in collectors.items():
        conn.execute("INSERT OR IGNORE INTO collectors(name, token_hash) VALUES (?, ?)",
                     (name, generate_password_hash(token)))
    if conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO transactions(kind, tx_date, item, category, amount_satang, note, created_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(k, d, i, c, a * 100, n, now_ms()) for k, d, i, c, a, n in BASE_TX])
    conn.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """สร้างฐานข้อมูล + ข้อมูลเริ่มต้น"""
    init_db()
    seed_data(parse_tokens(current_app.config["COLLECTOR_TOKENS"]) or DEFAULT_COLLECTORS)
    click.echo("สร้างฐานข้อมูลเรียบร้อย — ถ้าไม่ได้ตั้ง COLLECTOR_TOKENS รหัสคือ token-1..3 ให้เปลี่ยนด้วย: flask --app app set-token <ชื่อ>")


@click.command("set-token")
@click.argument("name")
@with_appcontext
def set_token_command(name):
    """เปลี่ยนรหัสของผู้เก็บเงิน (ต้องยาวอย่างน้อย 8 ตัวอักษร)"""
    token = click.prompt("รหัสใหม่", hide_input=True, confirmation_prompt=True)
    if len(token) < 8:
        raise click.ClickException("รหัสต้องยาวอย่างน้อย 8 ตัวอักษร")
    conn = get_db()
    cur = conn.execute("UPDATE collectors SET token_hash = ? WHERE name = ?", (generate_password_hash(token), name))
    conn.commit()
    if cur.rowcount == 0:
        raise click.ClickException(f"ไม่พบผู้เก็บเงินชื่อ {name}")
    click.echo(f"เปลี่ยนรหัสของ {name} แล้ว")


def init_app(app):
    """ผูกฟังก์ชันของไฟล์นี้เข้ากับแอป Flask"""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(set_token_command)
