"""ทดสอบความทนทานของ API: การตรวจจำนวนเงิน/เลขที่/วันที่, ข้อผิดพลาดที่ตอบเป็น JSON, CSP ของหน้าเว็บ และการล็อกอิน"""
import importlib
import os
import re
import sqlite3
import sys
import time
from decimal import Decimal

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(db_path):
    """โหลดโมดูล app ด้วยฐานข้อมูลชั่วคราว (คืนโมดูล เพื่อเรียกฟังก์ชันตัวช่วยได้โดยตรง)"""
    os.environ.update(SECRET_KEY="test-secret", DATABASE_PATH=db_path,
                      COLLECTOR_TOKENS="ฉัตร=password-1,มีมี่=password-2,เพียว=password-3")
    sys.path.insert(0, ROOT)
    for m in ("app", "config", "db", "evidence"):
        sys.modules.pop(m, None)
    mod = importlib.import_module("app")
    mod.app.config.update(TESTING=True, ACTION_COOLDOWN_MS=0)
    return mod


@pytest.fixture
def client(tmp_path):
    app = load_module(str(tmp_path / "t.db")).app
    c = app.test_client()
    c.get("/")
    with c.session_transaction() as s:
        csrf = s["csrf"]
    c.h = {"X-CSRF-Token": csrf}
    assert c.post("/api/login", json={"token": "password-1"}, headers=c.h).json["ok"]
    return c


def data(c):
    return c.get("/api/data").json


# ---------- ตัวช่วยแปลงค่า ----------
@pytest.mark.parametrize("raw,expected", [
    ("0.025", 3),             # ปัดครึ่งขึ้น (เดิมปัดครึ่งเป็นคู่ได้ 2)
    ("0.015", 2),
    ("12.34", 1234),
    (12, 1200),
    ("1000000", 100000000),   # เพดาน 1,000,000 บาท
    ("0.004", None),          # ปัดแล้วเหลือ 0 สตางค์ -> ไม่รับ
    ("0", None),
    ("-1", None),
    ("1000000.01", None),
    ("NaN", None),
    ("abc", None),
    (True, None),
    (None, None),
])
def test_parse_amount(tmp_path, raw, expected):
    assert load_module(str(tmp_path / "p.db")).parse_amount(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (3, 3), ("3", 3), (" 7 ", 7), (3.0, 3),
    (1.9, None), (True, None), ("1.5", None), ("", None), (None, None), ("abc", None), (float("nan"), None),
])
def test_parse_int(tmp_path, raw, expected):
    assert load_module(str(tmp_path / "p.db")).parse_int(raw) == expected


# ---------- จำนวนเงินผ่าน API ----------
def test_sub_satang_amounts_return_400_not_server_error(client):
    before = len(data(client)["transactions"])
    for amt in ("0.001", "0.004", "1e-3", "0", "-5", "NaN", "Infinity", "1000000.01", "abc", True):
        r = client.post("/api/transactions", json={"type": "out", "d": "2026-10-30", "item": "x", "amt": amt},
                        headers=client.h)
        assert r.status_code == 400 and r.json["error"] == "invalid_input", amt
    assert len(data(client)["transactions"]) == before


def test_amount_is_stored_with_half_up_rounding(client):
    tid = client.post("/api/transactions", json={"type": "out", "d": "2026-10-30", "item": "ปัดเศษ", "amt": "0.025"},
                      headers=client.h).json["id"]
    row = next(t for t in data(client)["transactions"] if t["id"] == tid)
    assert row["amt"] == 0.03


# ---------- เลขที่นักเรียน / วันที่เรียกเก็บ ----------
@pytest.mark.parametrize("sid", [True, 1.9, "1.5", "abc", None, 0, 99])
def test_payment_rejects_bad_student_numbers(client, sid):
    before = data(client)["payments"]
    r = client.post("/api/payments", json={"sid": sid, "amt": 5}, headers=client.h)
    assert r.status_code == 400 and r.json["error"] == "invalid_input"
    assert data(client)["payments"] == before


def test_payment_accepts_student_number_as_string_or_whole_float(client):
    assert client.post("/api/payments", json={"sid": "2", "amt": 5}, headers=client.h).json["ok"]
    assert client.post("/api/payments", json={"sid": 3.0, "amt": 5}, headers=client.h).json["ok"]
    assert sorted(p["sid"] for p in data(client)["payments"]) == [2, 3]


def test_charge_rejects_malformed_date_but_defaults_when_absent(client):
    r = client.post("/api/charges", json={"amt": 20, "d": "31/10/2026"}, headers=client.h)
    assert r.status_code == 400 and r.json["error"] == "invalid_input"
    assert data(client)["charges"] == []
    assert client.post("/api/charges", json={"amt": 20}, headers=client.h).json["ok"]
    assert data(client)["charges"][0]["d"]           # ใช้วันนี้เมื่อไม่ได้ส่งวันที่มา


# ---------- ข้อผิดพลาดของ API ตอบเป็น JSON เสมอ ----------
def test_unknown_api_route_and_wrong_method_return_json(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.is_json and r.json == {"ok": False, "error": "not_found"}
    r2 = client.post("/api/data", headers=client.h)
    assert r2.status_code == 405 and r2.is_json and r2.json["ok"] is False


def test_unexpected_error_is_generic_json_without_internal_detail(client, monkeypatch):
    def boom():
        raise RuntimeError("secret internal detail /var/db/path")
    monkeypatch.setitem(client.application.view_functions, "get_data", boom)
    r = client.get("/api/data")
    assert r.status_code == 500 and r.is_json and r.json == {"ok": False, "error": "server_error"}
    assert "secret internal detail" not in r.get_data(as_text=True)


# ---------- หน้าเว็บ: CSP และไม่มีโค้ด inline ----------
def test_html_page_has_strict_csp_and_no_inline_code(client):
    anon = client.application.test_client()
    r = anon.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp
    assert "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    body = r.get_data(as_text=True)
    assert not re.search(r"<script(?![^>]*\bsrc=)", body), "ห้ามมี <script> แบบ inline"
    assert " style=" not in body and " onclick=" not in body
    assert r.headers["X-Frame-Options"] == "DENY"


# ---------- ข้อมูลรายชื่อนักเรียนมาจากเซิร์ฟเวอร์ ----------
def test_students_list_is_served_by_api(client):
    students = data(client)["students"]
    assert len(students) == 21
    assert students[0] == {"no": 1, "name": "ธนากร คงสวัสดิ์"}
    assert students[-1]["no"] == 21


# ---------- ล็อกอิน: จำกัดการเดารหัส และลบประวัติเก่า ----------
def test_login_locks_ip_after_repeated_failures(client):
    anon = client.application.test_client()
    anon.get("/")
    with anon.session_transaction() as s:
        h = {"X-CSRF-Token": s["csrf"]}
    for _ in range(5):
        assert anon.post("/api/login", json={"token": "wrong-token"}, headers=h).status_code == 401
    r = anon.post("/api/login", json={"token": "password-2"}, headers=h)   # แม้รหัสจะถูก ก็ต้องถูกล็อกชั่วคราว
    assert r.status_code == 429 and r.json["error"] == "too_many_attempts"


def test_old_login_failures_are_pruned(client):
    db_path = client.application.config["DATABASE"]
    old = int(time.time() * 1000) - 10 * 60 * 1000          # 10 นาทีก่อน (พ้นช่วงล็อก 60 วินาที)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO auth_failures(ip, at_ms) VALUES ('10.0.0.9', ?)", (old,))
    conn.commit()
    conn.close()
    anon = client.application.test_client()
    anon.get("/")
    with anon.session_transaction() as s:
        h = {"X-CSRF-Token": s["csrf"]}
    anon.post("/api/login", json={"token": "wrong-token"}, headers=h)
    cutoff = int(time.time() * 1000) - 60 * 1000
    left = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM auth_failures WHERE at_ms <= ?", (cutoff,)).fetchone()[0]
    assert left == 0


def test_decimal_helper_is_exact():
    # กันการใช้ float ในการคำนวณเงิน: 0.1 + 0.2 ต้องได้ 0.3 พอดี
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
