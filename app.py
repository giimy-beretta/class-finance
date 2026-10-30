"""app.py — แอป Flask ระบบการเงินห้อง 5/2

หน้าที่:
  - เสิร์ฟหน้าเว็บ (templates/index.html) และ API แบบ JSON
  - ผู้ชมทั่วไป "อ่านได้อย่างเดียว" (GET /api/data)
  - ผู้เก็บเงิน 3 คนล็อกอินด้วยรหัส แล้วเพิ่ม/ลบ รายรับ-รายจ่าย, เรียกเก็บเงินรายสัปดาห์, รับเงินรายคน
  - แนบไฟล์หลักฐาน (JPG/PNG/WEBP/GIF/PDF) ให้รายจ่าย — ทุกคนดูได้, เฉพาะผู้เก็บเงินแนบ/ลบ
  - ทุกการแก้ไขถูกบันทึกใน audit_log ที่ฝั่งเซิร์ฟเวอร์ (ใครทำ ทำอะไร เมื่อไร + อีเมลที่กรอกตอนล็อกอิน)
  - ป้องกัน: ตรวจรหัสฝั่งเซิร์ฟเวอร์, จำกัดการเดารหัสต่อ IP, หน่วงการกระทำซ้ำ (กันกดรัว), CSRF token
"""
import hashlib
import os
import re
import secrets
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

import db
import evidence
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
if app.config["SECRET_KEY_MISSING"] and not (app.debug or app.config["TESTING"]):
    # ไม่มี SECRET_KEY คงที่ => แต่ละ worker สุ่มคนละค่า ทำให้ล็อกอิน/CSRF พังแบบสุ่ม จึงไม่ยอมเริ่มระบบ
    raise RuntimeError("ต้องตั้งค่า SECRET_KEY (python -c \"import secrets; print(secrets.token_hex(32))\") "
                       "ในไฟล์ .env หรือ environment variable ก่อนเริ่มระบบ (โหมดพัฒนาใช้ flask --app app run --debug)")
db.init_app(app)
if app.config["TRUSTED_PROXIES"]:   # อยู่หลัง nginx / แพลตฟอร์ม cloud: ใช้ IP จริงของผู้ใช้ (จำกัดการเดารหัสต่อ IP)
    from werkzeug.middleware.proxy_fix import ProxyFix
    n = app.config["TRUSTED_PROXIES"]
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)
with app.app_context():            # สร้าง/อัปเกรดฐานข้อมูลให้อัตโนมัติตอนเริ่มระบบ (รันซ้ำได้ ข้อมูลไม่หาย)
    db.bootstrap(app)

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")


# ---------------------------------------------------------------- ตัวช่วย
def fail(error, status=400):
    """ตอบข้อผิดพลาดแบบ JSON"""
    return jsonify(ok=False, error=error), status


def today_th():
    """วันนี้ตามเวลาประเทศไทย (ไม่ใช้เวลา UTC ของเซิร์ฟเวอร์ เพราะจะเลื่อนวันผิดช่วงเช้า)"""
    return datetime.now(ZoneInfo(app.config["TIMEZONE"])).date().isoformat()


def baht(satang):
    """แปลงสตางค์เป็นข้อความ ฿1,234.50"""
    return f"฿{satang / 100:,.2f}"


def parse_amount(value):
    """แปลงจำนวนเงินจากผู้ใช้เป็นสตางค์ (ไม่น้อยกว่า 0.01 และไม่เกิน 1,000,000 บาท; ปัดครึ่งขึ้นถึงสตางค์)
    ผิดรูปแบบ หรือปัดแล้วเหลือ 0 สตางค์ คืน None"""
    if isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or d > Decimal("1000000"):
        return None
    satang = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return satang if satang > 0 else None


def parse_int(value):
    """แปลงเลขจำนวนเต็ม (รับ 3, "3" หรือ 3.0) — ไม่รับ true/false หรือทศนิยมเช่น 1.9 คืน None ถ้าผิดรูปแบบ"""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    return None


def parse_date(value):
    """แปลงข้อความ YYYY-MM-DD เป็นวันที่ (ปี 2000-2100) ผิดรูปแบบคืน None"""
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return None
    return d.isoformat() if 2000 <= d.year <= 2100 else None


def clean_email(value):
    """รับอีเมลถ้ารูปแบบถูกต้อง ไม่เช่นนั้นคืนข้อความว่าง (ระบบไม่ได้ยืนยันว่าอีเมลเป็นของจริง)"""
    value = str(value or "").strip()
    return value if EMAIL_RE.match(value) else ""


def log(action, table, record_id, detail):
    """เขียน audit log ด้วยข้อมูลผู้ล็อกอินปัจจุบัน (ยังไม่ commit — ให้ route เป็นคน commit พร้อมงานหลัก)"""
    db.get_db().execute(
        "INSERT INTO audit_log(at_ms, collector_id, collector_name, action, table_name, record_id, detail, email) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (db.now_ms(), session.get("cid"), session.get("name"), action, table,
         None if record_id is None else str(record_id), detail, session.get("email") or None))


def too_fast(action):
    """True ถ้าผู้ล็อกอินคนนี้ทำ action เดิมไปเมื่อเร็ว ๆ นี้ (กันกดรัว)"""
    since = db.now_ms() - app.config["ACTION_COOLDOWN_MS"]
    row = db.get_db().execute(
        "SELECT 1 FROM audit_log WHERE collector_id = ? AND action = ? AND at_ms > ? LIMIT 1",
        (session["cid"], action, since)).fetchone()
    return row is not None


def collector_required(fn):
    """บังคับให้ต้องล็อกอินเป็นผู้เก็บเงินที่ยังใช้งานอยู่"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        cid = session.get("cid")
        row = cid and db.get_db().execute("SELECT 1 FROM collectors WHERE id = ? AND active = 1", (cid,)).fetchone()
        if not row:
            session.pop("cid", None)
            return fail("unauthorized", 401)
        return fn(*args, **kwargs)
    return wrapper


@app.before_request
def check_csrf():
    """ทุก request ที่แก้ข้อมูลต้องแนบ X-CSRF-Token ที่ตรงกับ session"""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        sent = request.headers.get("X-CSRF-Token", "")
        if not session.get("csrf") or not secrets.compare_digest(session["csrf"], sent):
            return fail("bad_csrf", 403)


@app.after_request
def security_headers(resp):
    """ใส่ header ความปลอดภัยพื้นฐาน และไม่ให้ cache ข้อมูล API"""
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if resp.mimetype == "text/html":   # หน้าเว็บหลัก: โหลดได้เฉพาะไฟล์ของระบบเอง ไม่มีสคริปต์ inline
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- หน้าเว็บ
@app.get("/")
def index():
    """หน้าหลัก: แจก CSRF token ให้ session นี้"""
    session.setdefault("csrf", secrets.token_hex(16))
    return render_template("index.html", csrf_token=session["csrf"])


# ---------------------------------------------------------------- อ่านข้อมูล (สาธารณะ)
@app.get("/api/data")
def get_data():
    """ส่งข้อมูลทั้งหมดให้หน้าเว็บ (ไม่รวมรายการที่ถูกลบ) — อีเมลใน log เห็นเฉพาะผู้เก็บเงินที่ล็อกอิน"""
    conn = db.get_db()
    logged_in = bool(session.get("cid"))
    students = [dict(no=r["student_no"], name=r["full_name"])
                for r in conn.execute("SELECT student_no, full_name FROM students ORDER BY student_no")]
    ev_by_tx = {}   # หลักฐานที่ยังใช้งานได้ จัดกลุ่มตามรายการ (ซ่อนถ้ารายการถูกลบ)
    for e in conn.execute(
            "SELECT e.id, e.transaction_id, e.display_name, e.size_bytes, e.mime_type FROM evidence e "
            "JOIN transactions t ON t.id = e.transaction_id "
            "WHERE e.deleted_at_ms IS NULL AND t.deleted_at_ms IS NULL ORDER BY e.id"):
        ev_by_tx.setdefault(e["transaction_id"], []).append(
            dict(id=e["id"], name=e["display_name"], size=e["size_bytes"], mime=e["mime_type"]))
    tx = [dict(id=r["id"], type=r["kind"], d=r["tx_date"], item=r["item"], cat=r["category"],
               amt=r["amount_satang"] / 100, note=r["note"], by=r["by_name"], ts=r["created_at_ms"],
               pid=r["payment_id"], ev=ev_by_tx.get(r["id"], []))
          for r in conn.execute(
              "SELECT t.*, c.name AS by_name, "
              "  (SELECT p.id FROM payments p WHERE p.transaction_id = t.id AND p.deleted_at_ms IS NULL) AS payment_id "
              "FROM transactions t LEFT JOIN collectors c ON c.id = t.created_by "
              "WHERE t.deleted_at_ms IS NULL ORDER BY t.tx_date, t.id")]
    charges = [dict(id=r["id"], d=r["charge_date"], amt=r["amount_satang"] / 100, by=r["by_name"], ts=r["created_at_ms"])
               for r in conn.execute(
                   "SELECT ch.*, c.name AS by_name FROM charges ch JOIN collectors c ON c.id = ch.created_by "
                   "WHERE ch.deleted_at_ms IS NULL ORDER BY ch.id")]
    payments = [dict(id=r["id"], sid=r["student_no"], d=r["pay_date"], amt=r["amount_satang"] / 100,
                     by=r["by_name"], ts=r["created_at_ms"])
                for r in conn.execute(
                    "SELECT p.*, c.name AS by_name FROM payments p JOIN collectors c ON c.id = p.created_by "
                    "WHERE p.deleted_at_ms IS NULL ORDER BY p.id")]
    audit = []
    for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200"):
        row = dict(ts=r["at_ms"], by=r["collector_name"], action=r["action"], detail=r["detail"])
        if logged_in:
            row["email"] = r["email"]
        audit.append(row)
    return jsonify(ok=True, me=session.get("name") if logged_in else None, students=students,
                   transactions=tx, charges=charges, payments=payments, audit=audit,
                   ev_limit=app.config["MAX_EVIDENCE_PER_TX"],
                   ev_max_mb=app.config["MAX_EVIDENCE_BYTES"] // (1024 * 1024))


# ---------------------------------------------------------------- ล็อกอิน / ออก
@app.post("/api/login")
def login():
    """ล็อกอินด้วยรหัสผู้เก็บเงิน (+ อีเมลสำหรับบันทึก log) — ผิดเกินกำหนดต่อ IP จะถูกล็อกชั่วคราว"""
    conn = db.get_db()
    data = request.get_json(silent=True) or {}
    ip = request.remote_addr or "-"
    since = db.now_ms() - app.config["LOGIN_WINDOW_SEC"] * 1000
    conn.execute("DELETE FROM auth_failures WHERE at_ms <= ?", (since,))   # ลบประวัติที่พ้นช่วงเวลาแล้ว ไม่ให้ตารางโตไม่หยุด
    fails = conn.execute("SELECT COUNT(*) FROM auth_failures WHERE ip = ? AND at_ms > ?", (ip, since)).fetchone()[0]
    if fails >= app.config["LOGIN_MAX_FAILS"]:
        return fail("too_many_attempts", 429)
    token = str(data.get("token") or "")
    me = next((r for r in conn.execute("SELECT * FROM collectors WHERE active = 1")
               if check_password_hash(r["token_hash"], token)), None)
    if me is None:
        conn.execute("INSERT INTO auth_failures(ip, at_ms) VALUES (?, ?)", (ip, db.now_ms()))
        conn.commit()
        return fail("invalid_token", 401)
    session.permanent = True
    session.update(cid=me["id"], name=me["name"], email=clean_email(data.get("email")))
    log("login", None, None, "เข้าสู่ระบบ")
    conn.commit()
    return jsonify(ok=True, name=me["name"])


@app.post("/api/logout")
@collector_required
def logout():
    """ออกจากระบบ (บันทึก log ก่อนล้าง session)"""
    log("logout", None, None, "ออกจากระบบ")
    db.get_db().commit()
    for key in ("cid", "name", "email"):
        session.pop(key, None)
    return jsonify(ok=True)


# ---------------------------------------------------------------- รายรับ-รายจ่าย
@app.post("/api/transactions")
@collector_required
def add_transaction():
    """เพิ่มรายรับ/รายจ่าย"""
    if too_fast("add_transaction"):
        return fail("too_fast", 429)
    d = request.get_json(silent=True) or {}
    kind, item = d.get("type"), str(d.get("item") or "").strip()[:200]
    cat = (str(d.get("cat") or "").strip() or "ไม่ระบุกลุ่ม")[:100]
    note = str(d.get("note") or "").strip()[:300] or None
    amt, tx_date = parse_amount(d.get("amt")), parse_date(d.get("d"))
    if kind not in ("in", "out") or not item or amt is None or tx_date is None:
        return fail("invalid_input")
    conn = db.get_db()
    cur = conn.execute(
        "INSERT INTO transactions(kind, tx_date, item, category, amount_satang, note, created_by, created_at_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (kind, tx_date, item, cat, amt, note, session["cid"], db.now_ms()))
    log("add_transaction", "transactions", cur.lastrowid,
        f"{'รายรับ' if kind == 'in' else 'รายจ่าย'} {item} {baht(amt)} ({tx_date})")
    conn.commit()
    return jsonify(ok=True, id=cur.lastrowid)


@app.delete("/api/transactions/<int:tid>")
@collector_required
def delete_transaction(tid):
    """ลบรายรับ/รายจ่าย (soft delete)"""
    if too_fast("delete_transaction"):
        return fail("too_fast", 429)
    conn = db.get_db()
    r = conn.execute("SELECT * FROM transactions WHERE id = ? AND deleted_at_ms IS NULL", (tid,)).fetchone()
    if r is None:
        return fail("not_found", 404)
    if conn.execute("SELECT 1 FROM payments WHERE transaction_id = ? AND deleted_at_ms IS NULL", (tid,)).fetchone():
        return fail("linked_to_payment", 409)   # รายรับจากการรับเงินนักเรียน ต้องลบที่ "ประวัติการเรียกเก็บ/รับเงิน" เพื่อให้ยอดตรงกัน
    conn.execute("UPDATE transactions SET deleted_at_ms = ?, deleted_by = ? WHERE id = ?",
                 (db.now_ms(), session["cid"], tid))
    log("delete_transaction", "transactions", tid,
        f"ลบ {'รายรับ' if r['kind'] == 'in' else 'รายจ่าย'} {r['item']} {baht(r['amount_satang'])} ({r['tx_date']})")
    conn.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- เรียกเก็บรายสัปดาห์
@app.post("/api/charges")
@collector_required
def create_charge():
    """เรียกเก็บเงินทุกคนคนละเท่ากัน (เรียกซ้ำได้ ยอดค้างทบต่อ ไม่มีการรีเซ็ต)"""
    if too_fast("create_charge"):
        return fail("too_fast", 429)
    d = request.get_json(silent=True) or {}
    amt = parse_amount(d.get("amt"))
    raw_date = d.get("d")
    charge_date = parse_date(raw_date) if raw_date else today_th()   # ไม่ส่งวันที่มา = ใช้วันนี้; ส่งมาแล้วผิดรูปแบบ = ปฏิเสธ
    if amt is None or charge_date is None:
        return fail("invalid_input")
    conn = db.get_db()
    cur = conn.execute("INSERT INTO charges(charge_date, amount_satang, created_by, created_at_ms) VALUES (?, ?, ?, ?)",
                       (charge_date, amt, session["cid"], db.now_ms()))
    log("create_charge", "charges", cur.lastrowid, f"เรียกเก็บทุกคน {baht(amt)} (สัปดาห์ {charge_date})")
    conn.commit()
    return jsonify(ok=True, id=cur.lastrowid)


@app.delete("/api/charges/<int:cid>")
@collector_required
def delete_charge(cid):
    """ลบรายการเรียกเก็บที่กรอกผิด (ทีละรายการ, soft delete)"""
    if too_fast("delete_charge"):
        return fail("too_fast", 429)
    conn = db.get_db()
    r = conn.execute("SELECT * FROM charges WHERE id = ? AND deleted_at_ms IS NULL", (cid,)).fetchone()
    if r is None:
        return fail("not_found", 404)
    conn.execute("UPDATE charges SET deleted_at_ms = ?, deleted_by = ? WHERE id = ?", (db.now_ms(), session["cid"], cid))
    log("delete_charge", "charges", cid, f"ลบการเรียกเก็บ {baht(r['amount_satang'])} ({r['charge_date']})")
    conn.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- รับเงินรายคน
@app.post("/api/payments")
@collector_required
def record_payment():
    """รับเงินจากนักเรียนรายคน (ยอดค้างลดลงตามที่จ่าย)"""
    if too_fast("record_payment"):
        return fail("too_fast", 429)
    d = request.get_json(silent=True) or {}
    amt = parse_amount(d.get("amt"))
    sid = parse_int(d.get("sid"))
    conn = db.get_db()
    stu = None
    if sid is not None:
        stu = conn.execute("SELECT full_name FROM students WHERE student_no = ?", (sid,)).fetchone()
    if amt is None or stu is None:
        return fail("invalid_input")
    now, pay_date = db.now_ms(), today_th()
    # ทำใน transaction เดียวกัน: ถ้าขั้นใดล้มเหลวจะไม่บันทึกอะไรเลย (ยอดค้าง/รายรับ/ประวัติต้องตรงกันเสมอ)
    tx = conn.execute(
        "INSERT INTO transactions(kind, tx_date, item, category, amount_satang, note, created_by, created_at_ms) "
        "VALUES ('in', ?, ?, ?, ?, ?, ?, ?)",
        (pay_date, f"รับเงินจาก {stu['full_name']}", db.PAYMENT_CATEGORY, amt, f"เลขที่ {sid} {stu['full_name']}", session["cid"], now))
    cur = conn.execute(
        "INSERT INTO payments(student_no, amount_satang, pay_date, created_by, created_at_ms, transaction_id) "
        "VALUES (?, ?, ?, ?, ?, ?)", (sid, amt, pay_date, session["cid"], now, tx.lastrowid))
    log("record_payment", "payments", cur.lastrowid,
        f"เลขที่ {sid} {stu['full_name']} จ่าย {baht(amt)} (บันทึกเป็นรายรับแล้ว)")
    conn.commit()
    return jsonify(ok=True, id=cur.lastrowid, transaction_id=tx.lastrowid)


@app.delete("/api/payments/<int:pid>")
@collector_required
def delete_payment(pid):
    """ลบรายการรับเงินที่กรอกผิด (ทีละรายการ, soft delete)"""
    if too_fast("delete_payment"):
        return fail("too_fast", 429)
    conn = db.get_db()
    r = conn.execute(
        "SELECT p.*, s.full_name FROM payments p JOIN students s ON s.student_no = p.student_no "
        "WHERE p.id = ? AND p.deleted_at_ms IS NULL", (pid,)).fetchone()
    if r is None:
        return fail("not_found", 404)
    now = db.now_ms()
    conn.execute("UPDATE payments SET deleted_at_ms = ?, deleted_by = ? WHERE id = ?", (now, session["cid"], pid))
    if r["transaction_id"]:   # ยกเลิกรายรับที่ผูกกันด้วย เพื่อให้เงินคงเหลือกลับมาถูกต้อง
        conn.execute("UPDATE transactions SET deleted_at_ms = ?, deleted_by = ? WHERE id = ? AND deleted_at_ms IS NULL",
                     (now, session["cid"], r["transaction_id"]))
    log("delete_payment", "payments", pid,
        f"ลบรับเงินของ {r['full_name']} เลขที่ {r['student_no']} จำนวน {baht(r['amount_satang'])} "
        f"({r['pay_date']}) และยกเลิกรายรับที่ผูกกัน")
    conn.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- หลักฐานการจ่ายเงิน
def evidence_dir():
    """โฟลเดอร์เก็บไฟล์หลักฐาน (ตั้งจาก config)"""
    return app.config["EVIDENCE_DIR"]


_API_ERROR_CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 413: "too_big", 415: "bad_type"}


@app.errorhandler(HTTPException)
def http_error(err):
    """ข้อผิดพลาด HTTP ของ /api/ ตอบเป็น JSON เสมอ (เช่น ไฟล์ใหญ่เกินเพดาน) ให้หน้าเว็บแสดงข้อความภาษาไทยได้"""
    if not request.path.startswith("/api/"):
        return err.get_response()
    return fail(_API_ERROR_CODES.get(err.code, "http_error"), err.code)


@app.errorhandler(Exception)
def unexpected_error(err):
    """ข้อผิดพลาดที่ไม่คาดคิด: บันทึกรายละเอียดไว้ที่เซิร์ฟเวอร์ แต่ไม่ส่งข้อมูลภายในไปให้ผู้ใช้"""
    if isinstance(err, HTTPException):
        return http_error(err)
    app.logger.exception("unexpected error")
    if request.path.startswith("/api/"):
        return fail("server_error", 500)
    return "เกิดข้อผิดพลาดที่เซิร์ฟเวอร์", 500


@app.post("/api/transactions/<int:tid>/evidence")
@collector_required
def upload_evidence(tid):
    """แนบหลักฐานให้รายจ่าย (ทีละไฟล์) — ตรวจชนิดจากเนื้อไฟล์จริง จำกัดขนาดและจำนวน"""
    if too_fast("upload_evidence"):
        return fail("too_fast", 429)
    conn = db.get_db()
    tx = conn.execute("SELECT * FROM transactions WHERE id = ? AND deleted_at_ms IS NULL", (tid,)).fetchone()
    if tx is None:
        return fail("not_found", 404)
    if tx["kind"] != "out":                       # แนบหลักฐานได้เฉพาะรายจ่าย
        return fail("not_expense", 409)
    active = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE transaction_id = ? AND deleted_at_ms IS NULL", (tid,)).fetchone()[0]
    if active >= app.config["MAX_EVIDENCE_PER_TX"]:
        return fail("too_many_evidence", 409)
    up = request.files.get("file")
    if up is None:
        return fail("no_file")
    data = up.read(app.config["MAX_EVIDENCE_BYTES"] + 1)   # อ่านแค่เพดาน+1 ไบต์ เพื่อรู้ว่าเกินหรือไม่
    if not data:
        return fail("no_file")
    if len(data) > app.config["MAX_EVIDENCE_BYTES"]:
        return fail("too_big", 413)
    kind = evidence.detect_type(data)
    if kind is None:                              # ไม่ใช่ JPG/PNG/WEBP/GIF/PDF จริง (ไม่เชื่อแค่นามสกุล)
        return fail("bad_type", 415)
    ext, mime = kind
    stored = evidence.new_stored_name(ext)
    display = evidence.clean_display_name(up.filename, ext)
    folder = evidence_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, stored)
    with open(path, "xb") as f:                   # "xb" = สร้างไฟล์ใหม่เท่านั้น ไม่เขียนทับของเดิม
        f.write(data)
    try:
        cur = conn.execute(
            "INSERT INTO evidence(transaction_id, stored_name, display_name, mime_type, size_bytes, sha256, "
            "created_by, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, stored, display, mime, len(data), hashlib.sha256(data).hexdigest(), session["cid"], db.now_ms()))
        log("upload_evidence", "evidence", cur.lastrowid,
            f"แนบหลักฐานให้รายจ่าย {tx['item']} ({display}, {len(data) / 1024:,.0f} KB)")
        conn.commit()
    except Exception:
        conn.rollback()
        os.remove(path)                           # บันทึกฐานข้อมูลไม่สำเร็จ ลบไฟล์ที่เขียนไว้ไม่ให้ค้างเป็นขยะ
        raise
    return jsonify(ok=True, id=cur.lastrowid)


@app.get("/api/evidence/<int:eid>")
def get_evidence(eid):
    """เปิดดูไฟล์หลักฐาน (ทุกคนดูได้ เหมือนข้อมูลอื่นในหน้าเว็บ) — ซ่อนถ้าหลักฐานหรือรายการถูกลบ"""
    row = db.get_db().execute(
        "SELECT e.* FROM evidence e JOIN transactions t ON t.id = e.transaction_id "
        "WHERE e.id = ? AND e.deleted_at_ms IS NULL AND t.deleted_at_ms IS NULL", (eid,)).fetchone()
    if row is None or not evidence.is_valid_stored_name(row["stored_name"]):
        return fail("not_found", 404)
    path = os.path.join(evidence_dir(), row["stored_name"])
    if not os.path.isfile(path):
        return fail("file_missing", 404)
    resp = send_file(path, mimetype=row["mime_type"], as_attachment=False, download_name=row["display_name"])
    if row["mime_type"].startswith("image/"):     # รูปภาพไม่ต้องโหลดอะไรเพิ่ม
        resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'"
    return resp


@app.delete("/api/evidence/<int:eid>")
@collector_required
def delete_evidence(eid):
    """ลบหลักฐาน (soft delete: ซ่อนจากหน้าเว็บ ไฟล์ยังอยู่ และบันทึกลง Log)"""
    if too_fast("delete_evidence"):
        return fail("too_fast", 429)
    conn = db.get_db()
    r = conn.execute(
        "SELECT e.*, t.item FROM evidence e JOIN transactions t ON t.id = e.transaction_id "
        "WHERE e.id = ? AND e.deleted_at_ms IS NULL", (eid,)).fetchone()
    if r is None:
        return fail("not_found", 404)
    conn.execute("UPDATE evidence SET deleted_at_ms = ?, deleted_by = ? WHERE id = ?",
                 (db.now_ms(), session["cid"], eid))
    log("delete_evidence", "evidence", eid, f"ลบหลักฐานของรายจ่าย {r['item']} ({r['display_name']})")
    conn.commit()
    return jsonify(ok=True)


@app.get("/healthz")
def healthz():
    """ตรวจสุขภาพระบบสำหรับ platform (เช็กว่าฐานข้อมูลเปิดได้)"""
    db.get_db().execute("SELECT 1").fetchone()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True)   # โหมดพัฒนาเท่านั้น — ใช้งานจริงให้รันด้วย gunicorn (ดู README.md)
