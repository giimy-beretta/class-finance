"""ทดสอบความสอดคล้องของหน้าเว็บ (ไม่ต้องเปิดเบราว์เซอร์):
- ทุก id ที่สคริปต์เรียกใช้ต้องมีอยู่จริงใน HTML (กันปุ่ม/ฟอร์มที่กดแล้วไม่มีอะไรเกิดขึ้น)
- ไม่มี inline style/handler/eval (สอดคล้องกับ Content-Security-Policy)
- ทุกตัวแปรสี var(--x) ที่ CSS ใช้ ต้องถูกนิยามไว้ที่ :root หรือธีม
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


HTML = read("templates", "index.html")
JS = read("static", "script.js")
CSS = read("static", "style.css")


def test_every_element_id_used_by_script_exists_in_html():
    # $("id") เท่านั้น (ไม่รวม $$("selector") และ id ที่สร้างตอนรัน เช่น `pay-${no}`)
    used = set(re.findall(r'(?<!\$)\$\("([^"]+)"\)', JS)) | set(re.findall(r'getElementById\("([^"]+)"\)', JS))
    ids = set(re.findall(r'\bid="([^"]+)"', HTML))
    missing = sorted(used - ids)
    assert not missing, f"สคริปต์อ้างถึง id ที่ไม่มีใน HTML: {missing}"


def test_every_data_action_has_a_handler():
    actions_in_markup = set(re.findall(r'data-act="([^"]+)"', HTML + JS))
    handled = set(re.findall(r'case "([^"]+)"', JS))
    assert actions_in_markup <= handled, f"data-act ที่ไม่มีตัวจัดการ: {sorted(actions_in_markup - handled)}"


def test_no_inline_handlers_styles_or_eval():
    assert not re.search(r"\son[a-z]+=", HTML), "ห้ามใช้ onclick= ฯลฯ ใน HTML"
    assert ' style="' not in HTML, "ห้ามใช้ style attribute ใน HTML"
    assert ' style="' not in JS and "style='" not in JS, "ห้ามสร้าง style attribute จากสคริปต์"
    assert "eval(" not in JS and "new Function" not in JS


def test_every_css_variable_used_is_defined():
    used = set(re.findall(r"var\((--[\w-]+)\)", CSS))
    defined = set(re.findall(r"(--[\w-]+)\s*:", CSS))
    assert used <= defined, f"ตัวแปร CSS ที่ไม่ได้นิยาม: {sorted(used - defined)}"


def test_assets_are_versioned_and_linked():
    assert "style.css" in HTML and "script.js" in HTML
    assert 'name="csrf"' in HTML
    assert 'lang="th"' in HTML
