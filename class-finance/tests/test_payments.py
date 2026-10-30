"""ทดสอบบัครับเงิน: รับเงินแล้วต้องเข้ารายรับ + เขียนประวัติ/Log และลบแล้วย้อนกลับ"""
import importlib
import os
import sqlite3
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_app(db_path):
    os.environ.update(SECRET_KEY="test-secret", DATABASE_PATH=db_path,
                      COLLECTOR_TOKENS="ฉัตร=password-1,มีมี่=password-2,เพียว=password-3")
    sys.path.insert(0, ROOT)
    for m in ("app", "config", "db"):
        sys.modules.pop(m, None)
    app = importlib.import_module("app").app
    app.config.update(TESTING=True, ACTION_COOLDOWN_MS=0)
    return app


@pytest.fixture
def client(tmp_path):
    app = load_app(str(tmp_path / "t.db"))
    c = app.test_client()
    c.get("/")
    with c.session_transaction() as s:
        csrf = s["csrf"]
    c.h = {"X-CSRF-Token": csrf}
    assert c.post("/api/login", json={"token": "password-1"}, headers=c.h).json["ok"]
    return c


def data(c):
    return c.get("/api/data").json


def total_in(d):
    return sum(t["amt"] for t in d["transactions"] if t["type"] == "in")


def test_payment_updates_income_debt_and_log(client):
    before = data(client)
    client.post("/api/charges", json={"amt": 20}, headers=client.h)
    r = client.post("/api/payments", json={"sid": 3, "amt": 15.5}, headers=client.h)
    assert r.json["ok"]
    d = data(client)
    assert round(total_in(d) - total_in(before), 2) == 15.5               # รายรับเพิ่ม
    new = [t for t in d["transactions"] if t["pid"] == r.json["id"]]
    assert len(new) == 1 and new[0]["type"] == "in" and "พีรพล" in new[0]["note"]   # มีในประวัติ
    assert d["payments"][-1]["amt"] == 15.5                                # ยอดค้างลดลง (ฝั่ง payments)
    assert d["audit"][0]["action"] == "record_payment"                     # เขียน Log


def test_delete_payment_reverts_income(client):
    before = total_in(data(client))
    pid = client.post("/api/payments", json={"sid": 1, "amt": 10}, headers=client.h).json["id"]
    assert client.delete(f"/api/payments/{pid}", headers=client.h).json["ok"]
    d = data(client)
    assert total_in(d) == before and not d["payments"]


def test_cannot_delete_linked_income_directly(client):
    r = client.post("/api/payments", json={"sid": 1, "amt": 10}, headers=client.h).json
    tid = r["transaction_id"]
    resp = client.delete(f"/api/transactions/{tid}", headers=client.h)
    assert resp.status_code == 409 and resp.json["error"] == "linked_to_payment"


def test_invalid_payment_rejected_and_nothing_written(client):
    before = data(client)
    for body in ({"sid": 99, "amt": 5}, {"sid": 1, "amt": 0}, {"sid": 1, "amt": -3}, {"sid": "x", "amt": 5}):
        assert client.post("/api/payments", json=body, headers=client.h).status_code == 400
    assert total_in(data(client)) == total_in(before)


def test_requires_login_and_csrf(client):
    anon = client.application.test_client()
    anon.get("/")
    assert anon.post("/api/payments", json={"sid": 1, "amt": 5}).status_code == 403   # ไม่มี CSRF
    with anon.session_transaction() as s:
        h = {"X-CSRF-Token": s["csrf"]}
    assert anon.post("/api/payments", json={"sid": 1, "amt": 5}, headers=h).status_code == 401


def test_migrates_old_db_and_backfills_missing_income(tmp_path):
    """ฐานข้อมูลเวอร์ชันบัค: มี payments แต่ไม่มีรายรับ -> อัปเกรดแล้วต้องได้รายรับย้อนหลังครั้งเดียว"""
    path = str(tmp_path / "old.db")
    app = load_app(path)
    with app.app_context():
        import db
        conn = db.get_db()
        conn.executescript("""
            DROP TABLE payments;
            CREATE TABLE payments (id INTEGER PRIMARY KEY AUTOINCREMENT, student_no INTEGER NOT NULL,
              amount_satang INTEGER NOT NULL, pay_date TEXT NOT NULL, created_by INTEGER NOT NULL,
              created_at_ms INTEGER NOT NULL, deleted_at_ms INTEGER, deleted_by INTEGER);
            INSERT INTO payments(student_no, amount_satang, pay_date, created_by, created_at_ms) VALUES (1, 1000, '2026-10-29', 1, 1);
        """)
        conn.commit()
    app = load_app(path)       # เริ่มระบบใหม่ = bootstrap รัน migration
    app2 = load_app(path)      # รันซ้ำต้องไม่สร้างซ้ำ
    rows = sqlite3.connect(path).execute(
        "SELECT t.amount_satang FROM payments p JOIN transactions t ON t.id = p.transaction_id").fetchall()
    assert rows == [(1000,)]
    n = sqlite3.connect(path).execute("SELECT COUNT(*) FROM transactions WHERE note LIKE 'เลขที่ 1 %'").fetchone()[0]
    assert n == 1
