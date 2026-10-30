"""app.py — แอป Flask ระบบการเงินห้อง 5/2

หน้าที่:
  - เสิร์ฟหน้าเว็บ (templates/index.html) และ API แบบ JSON
  - ผู้ชมทั่วไป "อ่านได้อย่างเดียว" (GET /api/data)
  - ผู้เก็บเงิน 3 คนล็อกอินด้วยรหัส แล้วเพิ่ม/ลบ รายรับ-รายจ่าย, เรียกเก็บเงินรายสัปดาห์, รับเงินรายคน
  - ทุกการแก้ไขถูกบันทึกใน audit_log ที่ฝั่งเซิร์ฟเวอร์ (ใครทำ ทำอะไร เมื่อไร + อีเมลที่กรอกตอนล็อกอิน)
  - ป้องกัน: ตรวจรหัสฝั่งเซิร์ฟเวอร์, จำกัดการเดารหัสต่อ IP, หน่วงการกระทำซ้ำ (กันกดรัว), CSRF token
"""
import re
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash

import db
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
    """แปลงจำนวนเงินจากผู้ใช้เป็นสตางค์ (ต้องมากกว่า 0 และไม่เกิน 1,000,000 บาท) ผิดรูปแบบคืน None"""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or d <= 0 or d > Decimal("1000000"):
        return None
    return int((d * 100).to_integral_value())


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
    tx = [dict(id=r["id"], type=r["kind"], d=r["tx_date"], item=r["item"], cat=r["category"],
               amt=r["amount_satang"] / 100, note=r["note"], by=r["by_name"], ts=r["created_at_ms"],
               pid=r["payment_id"])
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
    return jsonify(ok=True, me=session.get("name") if logged_in else None,
                   transactions=tx, charges=charges, payments=payments, audit=audit)


# ---------------------------------------------------------------- ล็อกอิน / ออก
@app.post("/api/login")
def login():
    """ล็อกอินด้วยรหัสผู้เก็บเงิน (+ อีเมลสำหรับบันทึก log) — ผิดเกินกำหนดต่อ IP จะถูกล็อกชั่วคราว"""
    conn = db.get_db()
    data = request.get_json(silent=True) or {}
    ip = request.remote_addr or "-"
    since = db.now_ms() - app.config["LOGIN_WINDOW_SEC"] * 1000
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
    charge_date = parse_date(d.get("d")) or today_th()
    if amt is None:
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
    try:
        sid = int(d.get("sid"))
    except (TypeError, ValueError):
        return fail("invalid_input")
    conn = db.get_db()
    stu = conn.execute("SELECT full_name FROM students WHERE student_no = ?", (sid,)).fetchone()
    if amt is None or stu is None:
        return fail("invalid_input")
    now, pay_date = db.now_ms(), today_th()
    # ทำใน transaction เดียวกัน: ถ้าขั้นใดล้มเหลวจะไม่บันทึกอะไรเลย (ยอดค้าง/รายรับ/ประวัติต้องตรงกันเสมอ)
    tx = conn.execute(
        "INSERT INTO transactions(kind, tx_date, item, category, amount_satang, note, created_by, created_at_ms) "
        "VALUES ('in', ?, ?, ?, ?, ?, ?, ?)",
        (pay_date, db.PAYMENT_ITEM, db.PAYMENT_CATEGORY, amt, f"เลขที่ {sid} {stu['full_name']}", session["cid"], now))
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
    r = conn.execute("SELECT * FROM payments WHERE id = ? AND deleted_at_ms IS NULL", (pid,)).fetchone()
    if r is None:
        return fail("not_found", 404)
    now = db.now_ms()
    conn.execute("UPDATE payments SET deleted_at_ms = ?, deleted_by = ? WHERE id = ?", (now, session["cid"], pid))
    if r["transaction_id"]:   # ยกเลิกรายรับที่ผูกกันด้วย เพื่อให้เงินคงเหลือกลับมาถูกต้อง
        conn.execute("UPDATE transactions SET deleted_at_ms = ?, deleted_by = ? WHERE id = ? AND deleted_at_ms IS NULL",
                     (now, session["cid"], r["transaction_id"]))
    log("delete_payment", "payments", pid,
        f"ลบรับเงิน เลขที่ {r['student_no']} {baht(r['amount_satang'])} ({r['pay_date']}) และรายรับที่ผูกกัน")
    conn.commit()
    return jsonify(ok=True)


@app.get("/healthz")
def healthz():
    """ตรวจสุขภาพระบบสำหรับ platform (เช็กว่าฐานข้อมูลเปิดได้)"""
    db.get_db().execute("SELECT 1").fetchone()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True)   # โหมดพัฒนาเท่านั้น — ใช้งานจริงให้รันด้วย gunicorn (ดู README.md)
