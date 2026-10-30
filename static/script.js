/* ระบบการเงินห้อง 5/2 — สคริปต์หน้าเว็บ (ไม่ใช้ไลบรารีภายนอก ไม่มี inline script/style)
 * - ข้อมูลทั้งหมดมาจาก /api/data การเพิ่ม/แก้/ลบทุกอย่างส่งไปที่เซิร์ฟเวอร์ ซึ่งตรวจสิทธิ์ คำนวณซ้ำ และบันทึก Log
 * - ภายในหน้าเว็บคำนวณเงินเป็น "สตางค์" (จำนวนเต็ม) เพื่อไม่ให้ทศนิยมคลาดเคลื่อน
 * - ยอดค้างรายคน = เรียกเก็บรวมทุกครั้ง - ที่คนนั้นจ่ายรวม (ไม่มีการรีเซ็ต) */
(() => {
  "use strict";

  /* ---------- ตัวช่วยพื้นฐาน ---------- */
  const $ = (id) => document.getElementById(id);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const icon = (name) => `<svg class="ic" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const toSatang = (baht) => Math.round(Number(baht) * 100);
  const fmtSatang = (s) => `${s < 0 ? "-" : ""}฿${(Math.abs(s) / 100).toLocaleString("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const pad = (n) => String(n).padStart(2, "0");
  const todayYmd = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const ymdDate = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const thDate = (s) => ymdDate(s).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
  const thMonth = (ym) => { const [y, m] = ym.split("-").map(Number); return new Date(y, m - 1, 1).toLocaleDateString("th-TH", { year: "numeric", month: "long" }); };
  const BAHT_RE = /^\d{1,7}(\.\d{1,2})?$/;
  // แปลงจำนวนเงินที่พิมพ์ (บาท ไม่เกิน 2 ตำแหน่ง) เป็นสตางค์ ผิดรูปแบบหรือไม่อยู่ในช่วง 0.01–1,000,000 คืน null
  function parseBahtInput(text) {
    const s = String(text ?? "").trim();
    if (!BAHT_RE.test(s)) return null;
    const sat = toSatang(s);
    return sat > 0 && sat <= 100000000 ? sat : null;
  }

  const ERR = {
    invalid_token: "รหัสไม่ถูกต้อง",
    too_many_attempts: "ใส่รหัสผิดหลายครั้ง กรุณารอสักครู่แล้วลองใหม่",
    too_fast: "ทำรายการเร็วเกินไป กรุณารอสักครู่",
    invalid_input: "ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง",
    not_found: "ไม่พบรายการ (อาจถูกลบไปแล้ว)",
    unauthorized: "หมดเวลาเข้าสู่ระบบ กรุณาเข้าสู่ระบบใหม่",
    linked_to_payment: "รายรับนี้มาจากการรับเงินนักเรียน ให้กดปุ่ม \"จากการรับเงิน\" ในแถวนี้เพื่อลบ",
    bad_csrf: "หน้าเว็บหมดอายุ กรุณารีเฟรชหน้า",
    too_big: "ไฟล์ใหญ่เกินกำหนด",
    bad_type: "รองรับเฉพาะไฟล์ JPG, PNG, WEBP, GIF หรือ PDF",
    too_many_evidence: "รายการนี้แนบครบจำนวนแล้ว (ลบไฟล์เดิมก่อนจึงแนบเพิ่มได้)",
    no_file: "ยังไม่ได้เลือกไฟล์",
    not_expense: "แนบหลักฐานได้เฉพาะรายจ่าย",
    file_missing: "ไม่พบไฟล์หลักฐานบนเซิร์ฟเวอร์",
    network: "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ ตรวจสอบอินเทอร์เน็ตแล้วลองใหม่",
    server_error: "เกิดข้อผิดพลาดที่เซิร์ฟเวอร์ กรุณาลองใหม่อีกครั้ง",
  };
  const errText = (code) => ERR[code] || `ไม่สำเร็จ (${code})`;

  /* ---------- ข้อความแจ้งผล (toast) ---------- */
  let toastTimer = 0;
  function toast(text, kind = "ok") {
    const el = $("toast");
    clearTimeout(toastTimer);
    if (!text) { el.hidden = true; return; }
    el.dataset.kind = kind;
    el.textContent = text;
    el.hidden = false;
    toastTimer = setTimeout(() => { el.hidden = true; }, kind === "error" ? 6000 : 3500);
  }

  /* ---------- สถานะ ---------- */
  const state = { loaded: false, me: null, students: [], tx: [], charges: [], payments: [], audit: [], evLimit: 5, evMaxMb: 5 };
  const view = { type: "all", sort: { key: "d", dir: -1 } };   // ตัวกรองประเภท และการเรียงตาราง (dir: -1 = มาก/ใหม่ก่อน)
  let evTargetId = null;     // รายจ่ายที่กำลังจะแนบหลักฐาน
  let evBusy = false;
  let lastFocusSelector = "";   // ปุ่มรับเงินที่เปิดกล่องอยู่ (เพื่อคืนโฟกัสเมื่อปิดกล่อง)
  const armTimers = new WeakMap();
  const originalLabels = new WeakMap();

  const sumType = (type) => state.tx.reduce((s, t) => (t.type === type ? s + t.sat : s), 0);
  const countType = (type) => state.tx.filter((t) => t.type === type).length;
  const nameOf = (no) => state.students.find((s) => s.no === no)?.name ?? "";
  const chargedSat = () => state.charges.reduce((s, c) => s + c.sat, 0);
  const paidSat = (no) => state.payments.reduce((s, p) => (p.sid === no ? s + p.sat : s), 0);
  const debtSat = (no) => chargedSat() - paidSat(no);
  const byDateDesc = (a, b) => (a.d < b.d ? 1 : a.d > b.d ? -1 : b.id - a.id);

  /* ---------- เครือข่าย ---------- */
  const csrfToken = () => document.querySelector('meta[name="csrf"]').content;
  // เรียก API เสมอคืน {ok, ...} (ไม่ throw) และแนบ CSRF token ทุกครั้ง
  async function api(path, { method = "GET", body, form } = {}) {
    const init = { method, credentials: "same-origin", headers: { "X-CSRF-Token": csrfToken() } };
    if (form) {
      init.body = form;                                  // FormData: เบราว์เซอร์ตั้ง multipart boundary เอง
    } else if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    try {
      const res = await fetch(path, init);
      const json = await res.json().catch(() => null);
      if (json && typeof json.ok === "boolean") return json;
      return { ok: false, error: res.status === 429 ? "too_fast" : `http_${res.status}` };
    } catch {
      return { ok: false, error: "network" };
    }
  }

  // โหลดข้อมูลทั้งหมดจากเซิร์ฟเวอร์แล้ววาดใหม่
  async function load() {
    const j = await api("/api/data");
    if (!j.ok) {
      $("loadErrorText").textContent = `โหลดข้อมูลไม่สำเร็จ — ${errText(j.error)}`;
      $("loadError").hidden = false;
      if (!state.loaded) showLoadingPlaceholders("โหลดข้อมูลไม่สำเร็จ กดลองใหม่ด้านบน");   // ไม่ให้ค้างข้อความ "กำลังโหลด"
      return false;
    }
    state.loaded = true;
    state.me = j.me;
    state.students = j.students;
    state.tx = j.transactions.map((t) => ({ ...t, sat: toSatang(t.amt) }));
    state.charges = j.charges.map((c) => ({ ...c, sat: toSatang(c.amt) }));
    state.payments = j.payments.map((p) => ({ ...p, sat: toSatang(p.amt) }));
    state.audit = j.audit;
    state.evLimit = j.ev_limit ?? state.evLimit;
    state.evMaxMb = j.ev_max_mb ?? state.evMaxMb;
    $("loadError").hidden = true;
    renderAll();
    return true;
  }

  // ทำให้ผู้ใช้เห็นว่าข้อมูลกำลังโหลด (ก่อนได้ข้อมูลชุดแรก)
  function showLoadingPlaceholders(text = "กำลังโหลดข้อมูล…") {
    const row = (cols) => `<tr><td class="empty-cell" colspan="${cols}">${esc(text)}</td></tr>`;
    $("rows").innerHTML = row(6);
    $("studentRows").innerHTML = row(4);
    $("monthRows").innerHTML = row(5);
    $("latestList").innerHTML = `<li class="empty">${esc(text)}</li>`;
  }

  /* ---------- วาดหน้าจอ ---------- */
  function renderAll() {
    renderSummary();
    renderCategoryOptions();
    renderHistory();
    renderStudents();
    renderMonths();
    renderAudit();
    applyAuth();
  }

  // แสดง/ซ่อนส่วนของผู้เก็บเงินตามสถานะล็อกอิน
  function applyAuth() {
    const me = state.me;
    $("loginForm").hidden = Boolean(me);
    $("whoBox").hidden = !me;
    $("whoName").textContent = me || "";
    $("addCard").hidden = !me;
    $("chargeCard").hidden = !me;
    $$(".admin-only").forEach((el) => { el.hidden = !me; });
  }

  function renderSummary() {
    const inS = sumType("in"), outS = sumType("out"), balS = inS - outS;
    const owed = state.students.reduce((s, st) => s + Math.max(0, debtSat(st.no)), 0);
    const owing = state.students.filter((st) => debtSat(st.no) > 0).length;
    $("totalIn").textContent = fmtSatang(inS);
    $("totalOut").textContent = fmtSatang(outS);
    $("balance").textContent = fmtSatang(balS);
    $("balance").classList.toggle("neg", balS < 0);
    $("countIn").textContent = `${countType("in")} รายการ`;
    $("countOut").textContent = `${countType("out")} รายการ`;
    $("totalDebt").textContent = fmtSatang(owed);
    $("debtMeta").textContent = `${owing} จาก ${state.students.length} คน ยังค้างอยู่`;
    renderBars($("catIn"), "in", inS);
    renderBars($("catOut"), "out", outS);
    renderLatest();
  }

  function renderBars(el, type, total) {
    const byCat = new Map();
    state.tx.forEach((t) => { if (t.type === type) byCat.set(t.cat, (byCat.get(t.cat) || 0) + t.sat); });
    const rows = [...byCat].sort((a, b) => b[1] - a[1]);
    el.innerHTML = rows.length
      ? rows.map(([cat, sat]) => {
          const pct = total ? (sat / total) * 100 : 0;
          return `<div class="bar-row">
            <div class="bar-meta"><span>${esc(cat)}</span><span>${fmtSatang(sat)} · ${pct.toFixed(0)}%</span></div>
            <div class="bar" aria-hidden="true"><span data-w="${pct.toFixed(1)}"></span></div>
          </div>`;
        }).join("")
      : `<p class="empty">ยังไม่มีข้อมูล</p>`;
    $$("[data-w]", el).forEach((b) => { b.style.width = `${b.dataset.w}%`; });   // ตั้งความกว้างผ่าน CSSOM (ไม่ใช้ style attribute)
  }

  function renderLatest() {
    const latest = [...state.tx].sort(byDateDesc).slice(0, 5);
    $("latestList").innerHTML = latest.length
      ? latest.map((t) => {
          const isIn = t.type === "in";
          return `<li class="feed-item">
            <span class="tag ${t.type}">${isIn ? "รายรับ" : "รายจ่าย"}</span>
            <div class="feed-main"><strong>${esc(t.item)}</strong><small>${thDate(t.d)} · ${esc(t.cat)}</small></div>
            <span class="amt ${isIn ? "pos" : "neg"}">${isIn ? "+" : "−"}${fmtSatang(t.sat)}</span>
          </li>`;
        }).join("")
      : `<li class="empty">ยังไม่มีรายการ</li>`;
  }

  function renderCategoryOptions() {
    const sel = $("catFilter"), keep = sel.value;
    const cats = [...new Set(state.tx.map((t) => t.cat))].sort((a, b) => a.localeCompare(b, "th"));
    sel.innerHTML = `<option value="">ทุกหมวดหมู่</option>${cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}`;
    sel.value = cats.includes(keep) ? keep : "";
    $("catList").innerHTML = cats.map((c) => `<option value="${esc(c)}"></option>`).join("");
  }

  // รายการที่ตรงกับตัวกรองและการเรียงปัจจุบัน
  function filteredRows() {
    const q = $("search").value.trim().toLowerCase();
    const cat = $("catFilter").value, from = $("dateFrom").value, to = $("dateTo").value;
    const { key, dir } = view.sort;
    return state.tx
      .filter((t) => (view.type === "all" || t.type === view.type)
        && (!cat || t.cat === cat)
        && (!from || t.d >= from)
        && (!to || t.d <= to)
        && (!q || `${t.item} ${t.cat}`.toLowerCase().includes(q)))
      .sort((a, b) => {
        const va = key === "amt" ? a.sat : a.d, vb = key === "amt" ? b.sat : b.d;
        const c = va < vb ? -1 : va > vb ? 1 : 0;
        return (c || a.id - b.id) * dir;
      });
  }

  function evidenceCell(t) {
    if (t.type !== "out") return `<span class="muted">—</span>`;
    const files = t.ev || [], me = state.me;
    const list = files.map((f) => `<div class="ev-row">
        <a href="/api/evidence/${f.id}" target="_blank" rel="noopener" title="${esc(f.name)}">${icon("file")}<span>${esc(f.name)}</span></a>
        ${me ? `<button class="btn small icon" type="button" data-act="del-ev" data-id="${f.id}" aria-label="ลบหลักฐาน ${esc(f.name)}">${icon("trash")}</button>` : ""}
      </div>`).join("");
    const attach = me && files.length < state.evLimit
      ? `<button class="btn small" type="button" data-act="attach" data-id="${t.id}">${icon("clip")}<span>แนบหลักฐาน</span></button>`
      : "";
    if (!files.length) return `<span class="tag">ยังไม่มีหลักฐาน</span>${attach ? ` ${attach}` : ""}`;
    return `${list}${attach ? `<div class="ev-row">${attach}</div>` : ""}`;
  }

  function renderHistory() {
    const rows = filteredRows(), me = state.me;
    $("rows").innerHTML = rows.map((t) => {
      const isIn = t.type === "in";
      const actions = !me ? "" : t.pid
        ? `<button class="btn small danger" type="button" data-act="del-pay" data-id="${t.pid}" title="ลบการรับเงินนี้ รายรับที่เกี่ยวข้องจะถูกยกเลิกด้วย">${icon("trash")}<span>จากการรับเงิน</span></button>`
        : `<button class="btn small icon" type="button" data-act="del-tx" data-id="${t.id}" aria-label="ลบรายการ ${esc(t.item)}">${icon("trash")}</button>`;
      return `<tr>
        <td class="nowrap" data-label="วันที่">${thDate(t.d)}</td>
        <td class="cell-main" data-label="รายการ">
          <span class="tag ${t.type}">${isIn ? "รายรับ" : "รายจ่าย"}</span> <span class="item">${esc(t.item)}</span>
          ${t.note ? `<div class="note-line">${esc(t.note)}</div>` : ""}
        </td>
        <td data-label="หมวดหมู่">${esc(t.cat)}</td>
        <td class="num ${isIn ? "pos" : "neg"}" data-label="จำนวนเงิน">${isIn ? "+" : "−"}${fmtSatang(t.sat)}</td>
        <td data-label="หลักฐาน">${evidenceCell(t)}</td>
        ${me ? `<td class="cell-actions" data-label="จัดการ">${actions}</td>` : ""}
      </tr>`;
    }).join("") || `<tr><td class="empty-cell" colspan="${me ? 6 : 5}">ไม่พบรายการที่ตรงกับตัวกรอง</td></tr>`;
    $("resultCount").textContent = `แสดง ${rows.length} จาก ${state.tx.length} รายการ`;
    $$("#histTable [data-sort]").forEach((btn) => {
      const active = btn.dataset.sort === view.sort.key;
      btn.closest("th").setAttribute("aria-sort", active ? (view.sort.dir === 1 ? "ascending" : "descending") : "none");
    });
  }

  function renderStudents() {
    const me = state.me;
    const typed = {};   // จำค่าที่กำลังพิมพ์ไว้ ไม่ให้หายตอนข้อมูลรีเฟรช
    $$(".pay-input").forEach((i) => { if (i.value) typed[i.dataset.no] = i.value; });
    $("studentRows").innerHTML = state.students.map((st) => {
      const d = debtSat(st.no);
      const status = d > 0 ? `<span class="tag out">ค้าง ${fmtSatang(d)}</span>`
        : d < 0 ? `<span class="tag in">จ่ายล่วงหน้า ${fmtSatang(-d)}</span>`
        : `<span class="tag in">ไม่ค้าง</span>`;
      const payCell = me ? `<td class="cell-actions" data-label="รับเงิน">
          <label class="sr-only" for="pay-${st.no}">จำนวนเงินที่รับจาก ${esc(st.name)}</label>
          <input id="pay-${st.no}" class="pay-input" type="number" inputmode="decimal" min="0.01" max="1000000" step="0.01" placeholder="บาท" data-no="${st.no}" value="${esc(typed[st.no] ?? "")}">
          <button class="btn small primary" type="button" data-act="pay" data-no="${st.no}">รับเงิน</button>
        </td>` : "";
      return `<tr>
        <td class="num-cell" data-label="เลขที่">${st.no}</td>
        <td class="cell-main" data-label="ชื่อ-สกุล">${esc(st.name)}</td>
        <td data-label="สถานะ">${status}</td>
        ${payCell}
      </tr>`;
    }).join("") || `<tr><td class="empty-cell" colspan="${me ? 4 : 3}">ยังไม่มีรายชื่อนักเรียน</td></tr>`;

    const owed = state.students.reduce((s, st) => s + Math.max(0, debtSat(st.no)), 0);
    $("stuSummary").textContent = `เรียกเก็บแล้ว ${state.charges.length} ครั้ง (รวม ${fmtSatang(chargedSat())} ต่อคน) · ยอดค้างรวมทุกคน ${fmtSatang(owed)}`;

    const hist = [
      ...state.charges.map((c) => ({ kind: "charge", id: c.id, ts: c.ts, d: c.d, sat: c.sat, by: c.by, label: "เรียกเก็บทุกคน" })),
      ...state.payments.map((p) => ({ kind: "pay", id: p.id, ts: p.ts, d: p.d, sat: p.sat, by: p.by, label: `รับเงิน เลขที่ ${p.sid} ${nameOf(p.sid)}` })),
    ].sort((a, b) => b.ts - a.ts).slice(0, 100);
    $("stuHist").innerHTML = hist.map((h) => `<tr>
        <td class="nowrap" data-label="วันที่">${thDate(h.d)}</td>
        <td class="cell-main" data-label="รายการ">${esc(h.label)}</td>
        <td class="num" data-label="จำนวน">${fmtSatang(h.sat)}</td>
        <td data-label="บันทึกโดย">${esc(h.by || "-")}</td>
        ${me ? `<td class="cell-actions" data-label="จัดการ"><button class="btn small icon" type="button" data-act="del-hist" data-kind="${h.kind}" data-id="${h.id}" aria-label="ลบรายการนี้">${icon("trash")}</button></td>` : ""}
      </tr>`).join("") || `<tr><td class="empty-cell" colspan="${me ? 5 : 4}">ยังไม่มีรายการ</td></tr>`;
  }

  function renderMonths() {
    const months = new Map();
    state.tx.forEach((t) => {
      const key = t.d.slice(0, 7);
      const m = months.get(key) || { inS: 0, outS: 0 };
      if (t.type === "in") m.inS += t.sat; else m.outS += t.sat;
      months.set(key, m);
    });
    let running = 0;
    $("monthRows").innerHTML = [...months].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([ym, m]) => {
      running += m.inS - m.outS;
      return `<tr>
        <td class="cell-main" data-label="เดือน">${thMonth(ym)}</td>
        <td class="num pos" data-label="รายรับ">+${fmtSatang(m.inS)}</td>
        <td class="num neg" data-label="รายจ่าย">−${fmtSatang(m.outS)}</td>
        <td class="num" data-label="สุทธิ">${fmtSatang(m.inS - m.outS)}</td>
        <td class="num" data-label="คงเหลือสะสม">${fmtSatang(running)}</td>
      </tr>`;
    }).join("") || `<tr><td class="empty-cell" colspan="5">ยังไม่มีข้อมูล</td></tr>`;
  }

  const AUDIT_LABEL = {
    login: "เข้าสู่ระบบ", logout: "ออกจากระบบ", add_transaction: "เพิ่มรายการ", delete_transaction: "ลบรายการ",
    create_charge: "เรียกเก็บเงิน", record_payment: "รับเงินนักเรียน", delete_charge: "ลบรายการเรียกเก็บ",
    delete_payment: "ลบรายการรับเงิน", upload_evidence: "แนบหลักฐาน", delete_evidence: "ลบหลักฐาน",
    fix_payment_income: "แก้ไขข้อมูลย้อนหลัง",
  };
  function renderAudit() {
    const me = state.me;
    $("auditRows").innerHTML = state.audit.map((r) => `<tr>
        <td class="nowrap" data-label="เวลา">${new Date(r.ts).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })}</td>
        <td data-label="ผู้แก้ไข">${esc(r.by || "ระบบ")}</td>
        <td data-label="การกระทำ">${esc(AUDIT_LABEL[r.action] || r.action)}</td>
        <td class="cell-main" data-label="รายละเอียด">${esc(r.detail || "-")}</td>
        ${me ? `<td data-label="อีเมลที่กรอก">${esc(r.email || "-")}</td>` : ""}
      </tr>`).join("") || `<tr><td class="empty-cell" colspan="${me ? 5 : 4}">ยังไม่มีบันทึก</td></tr>`;
  }

  /* ---------- กันกดซ้ำ และการยืนยันสองขั้น ---------- */
  // ปุ่มถูกปิดระหว่างรอเซิร์ฟเวอร์ตอบ
  async function withBusy(btn, job) {
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    try { await job(); } finally { btn.disabled = false; }
  }
  // กดครั้งแรก = เปลี่ยนป้ายเป็นข้อความยืนยัน (หมดเวลาใน 4 วินาที); กดซ้ำ = ทำงานจริง
  function armOrRun(btn, label, run) {
    if (btn.dataset.armed !== "1") {
      if (!originalLabels.has(btn)) originalLabels.set(btn, btn.innerHTML);
      btn.dataset.armed = "1";
      btn.classList.add("danger");
      btn.textContent = label;
      clearTimeout(armTimers.get(btn));
      armTimers.set(btn, setTimeout(() => disarm(btn), 4000));
      return;
    }
    disarm(btn);
    run();
  }
  function disarm(btn) {
    clearTimeout(armTimers.get(btn));
    btn.dataset.armed = "";
    btn.classList.remove("danger");
    if (originalLabels.has(btn)) btn.innerHTML = originalLabels.get(btn);
  }
  // ส่งคำสั่งลบ/แก้ไขแล้วแจ้งผล และโหลดข้อมูลใหม่
  async function mutate(path, method, okMsg) {
    const j = await api(path, { method });
    if (!j.ok) {
      toast(errText(j.error), "error");
      if (j.error === "unauthorized") await load();
      return false;
    }
    toast(okMsg);
    await load();
    return true;
  }

  /* ---------- การกระทำจากปุ่มในตาราง (ใช้ event delegation) ---------- */
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const { act, id, no, kind } = btn.dataset;
    const admin = Boolean(state.me);
    switch (act) {
      case "retry":
        load();
        break;
      case "attach":
        if (!admin) return;
        evTargetId = id;
        $("evFile").click();
        break;
      case "del-tx":
        if (admin) armOrRun(btn, "ยืนยันลบ?", () => mutate(`/api/transactions/${id}`, "DELETE", "ลบรายการแล้ว"));
        break;
      case "del-pay":
        if (admin) armOrRun(btn, "ยืนยันลบ?", () => mutate(`/api/payments/${id}`, "DELETE", "ลบการรับเงินและรายรับที่เกี่ยวข้องแล้ว"));
        break;
      case "del-ev":
        if (admin) armOrRun(btn, "ยืนยัน?", () => mutate(`/api/evidence/${id}`, "DELETE", "ลบหลักฐานแล้ว"));
        break;
      case "del-hist":
        if (admin) armOrRun(btn, "ยืนยัน?", () => mutate(`/api/${kind === "charge" ? "charges" : "payments"}/${id}`, "DELETE", "ลบรายการแล้ว"));
        break;
      case "pay":
        if (admin) payStudent(Number(no), btn);
        break;
      default:
        break;
    }
  });

  /* ---------- ล็อกอิน / ออกจากระบบ ---------- */
  $("loginForm").addEventListener("submit", (e) => {
    e.preventDefault();
    withBusy($("loginBtn"), async () => {
      const j = await api("/api/login", {
        method: "POST",
        body: { token: $("tokenIn").value.trim(), email: $("emailIn").value.trim() },
      });
      if (!j.ok) {
        toast(errText(j.error), "error");
        $("tokenIn").select();
        return;
      }
      $("tokenIn").value = "";
      toast(`เข้าสู่ระบบเป็น ${j.name} แล้ว`);
      await load();
    });
  });
  $("logoutBtn").addEventListener("click", (e) => withBusy(e.currentTarget, async () => {
    await api("/api/logout", { method: "POST" });
    toast("ออกจากระบบแล้ว");
    await load();
  }));

  /* ---------- เพิ่มรายการรายรับ / รายจ่าย ---------- */
  $("txForm").addEventListener("submit", (e) => {
    e.preventDefault();
    if (!state.me) return;
    const body = {
      type: $("fType").value,
      d: $("fDate").value,
      item: $("fItem").value.trim(),
      cat: $("fCat").value.trim(),
      amt: $("fAmt").value,
      note: $("fNote").value.trim(),
    };
    withBusy($("addBtn"), async () => {
      const j = await api("/api/transactions", { method: "POST", body });
      if (!j.ok) { toast(errText(j.error), "error"); return; }
      ["fItem", "fCat", "fAmt", "fNote"].forEach((id) => { $(id).value = ""; });   // เก็บประเภทและวันที่ไว้ใช้กรอกต่อ
      toast("บันทึกรายการแล้ว");
      await load();
    });
  });

  /* ---------- เรียกเก็บรายสัปดาห์ (ยืนยันสองขั้น) ---------- */
  $("chargeForm").addEventListener("submit", (e) => {
    e.preventDefault();
    if (!state.me) return;
    const btn = $("chargeBtn");
    const sat = parseBahtInput($("cAmt").value);
    if (sat === null) { toast(ERR.invalid_input + " (จำนวนเงินต้องมากกว่า 0 ไม่เกิน 2 ตำแหน่งทศนิยม)", "error"); return; }
    armOrRun(btn, `ยืนยันเรียกเก็บ ${fmtSatang(sat)} ต่อคน?`, () => withBusy(btn, async () => {
      const j = await api("/api/charges", { method: "POST", body: { amt: $("cAmt").value, d: $("cDate").value } });
      if (!j.ok) { toast(errText(j.error), "error"); return; }
      toast("เรียกเก็บเงินทุกคนแล้ว");
      await load();
    }));
  });

  /* ---------- รับเงินรายคน ---------- */
  async function payStudent(no, btn) {
    const input = $(`pay-${no}`);
    const sat = parseBahtInput(input ? input.value : "");
    if (sat === null) {
      toast("ใส่จำนวนเงินที่จ่ายมา (มากกว่า 0 ไม่เกิน 2 ตำแหน่งทศนิยม)", "error");
      input?.focus();
      return;
    }
    await withBusy(btn, async () => {
      const j = await api("/api/payments", { method: "POST", body: { sid: no, amt: input.value } });
      if (!j.ok) { toast(errText(j.error), "error"); return; }
      input.value = "";            // ล้างก่อนโหลดใหม่ เพื่อไม่ให้ค่าเดิมกลับมา
      await load();
      showPayDialog(no, sat, debtSat(no));
    });
  }

  function showPayDialog(no, paidSat, remainSat) {
    // ตารางถูกวาดใหม่หลังบันทึกแล้ว ปุ่มเดิมจึงไม่อยู่ในหน้า: จำตัวเลือกของปุ่มไว้แทน
    lastFocusSelector = `[data-act="pay"][data-no="${no}"]`;
    const left = remainSat > 0 ? `<span class="neg">ค้างอยู่ ${fmtSatang(remainSat)}</span>`
      : remainSat < 0 ? `<span class="pos">จ่ายล่วงหน้า ${fmtSatang(-remainSat)}</span>`
      : `<span class="pos">ชำระครบแล้ว</span>`;
    $("payDlgBody").innerHTML = `
      <div><dt>เลขที่</dt><dd>${no}</dd></div>
      <div><dt>ชื่อ-สกุล</dt><dd>${esc(nameOf(no))}</dd></div>
      <div><dt>จำนวนที่รับ</dt><dd>${fmtSatang(paidSat)}</dd></div>
      <div><dt>ยอดค้างคงเหลือ</dt><dd>${left}</dd></div>`;
    $("payDialog").hidden = false;
    $("payDlgClose").focus();
  }
  function hidePayDialog() {
    $("payDialog").hidden = true;
    document.querySelector(lastFocusSelector)?.focus();   // คืนโฟกัสให้ผู้ใช้คีย์บอร์ดทำงานต่อได้
    lastFocusSelector = "";
  }
  $("payDlgClose").addEventListener("click", hidePayDialog);
  $("payDialog").addEventListener("click", (e) => { if (e.target.id === "payDialog") hidePayDialog(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("payDialog").hidden) hidePayDialog();
  });

  /* ---------- หลักฐานการจ่ายเงิน ---------- */
  $("evFile").addEventListener("change", async () => {
    const input = $("evFile"), file = input.files[0], tid = evTargetId;
    input.value = "";                                   // เคลียร์ค่า เพื่อให้เลือกไฟล์เดิมซ้ำได้
    if (!file || !tid || !state.me || evBusy) return;
    if (file.size > state.evMaxMb * 1024 * 1024) {
      toast(`${ERR.too_big} (สูงสุด ${state.evMaxMb} MB)`, "error");
      return;
    }
    evBusy = true;
    toast("กำลังแนบไฟล์…", "info");
    try {
      const form = new FormData();
      form.append("file", file);
      const j = await api(`/api/transactions/${encodeURIComponent(tid)}/evidence`, { method: "POST", form });
      if (!j.ok) { toast(errText(j.error), "error"); return; }
      toast(`แนบหลักฐานแล้ว: ${file.name}`);
      await load();
    } finally {
      evBusy = false;
    }
  });

  /* ---------- ตัวกรอง การเรียง และการส่งออก ---------- */
  ["search", "catFilter", "dateFrom", "dateTo"].forEach((id) => {
    $(id).addEventListener("input", renderHistory);
    $(id).addEventListener("change", renderHistory);
  });
  $("typeToggle").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-type]");
    if (!b) return;
    view.type = b.dataset.type;
    $$("#typeToggle button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderHistory();
  });
  $("clearFilters").addEventListener("click", () => {
    ["search", "catFilter", "dateFrom", "dateTo"].forEach((id) => { $(id).value = ""; });
    view.type = "all";
    $$("#typeToggle button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.type === "all")));
    renderHistory();
  });
  document.querySelector("#histTable thead").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-sort]");
    if (!b) return;
    const key = b.dataset.sort;
    view.sort = view.sort.key === key ? { key, dir: -view.sort.dir } : { key, dir: -1 };
    renderHistory();
  });

  // ส่งออก CSV ตามตัวกรองปัจจุบัน (มี BOM ให้ Excel อ่านภาษาไทยถูกต้อง)
  $("exportBtn").addEventListener("click", () => {
    const rows = filteredRows();
    const header = ["วันที่", "ประเภท", "รายการ", "หมวดหมู่", "จำนวนเงิน (บาท)", "หมายเหตุ"];
    const lines = rows.map((t) => [t.d, t.type === "in" ? "รายรับ" : "รายจ่าย", t.item, t.cat, (t.sat / 100).toFixed(2), t.note || ""]);
    const csv = [header, ...lines]
      .map((cols) => cols.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
      .join("\r\n");
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "room502_transactions.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`ส่งออก ${rows.length} รายการแล้ว`);
  });
  $("printBtn").addEventListener("click", () => window.print());

  /* ---------- แท็บ (รองรับคีย์บอร์ด ลูกศรซ้าย/ขวา Home End) ---------- */
  const tabs = $$('[role="tab"]');
  function selectTab(name, { focus = false, remember = false } = {}) {
    tabs.forEach((t) => {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    $$('[role="tabpanel"]').forEach((p) => { p.hidden = p.dataset.panel !== name; });
    if (remember) history.replaceState(null, "", `#${name}`);
  }
  tabs.forEach((t) => {
    t.addEventListener("click", () => selectTab(t.dataset.tab, { remember: true }));
    t.addEventListener("keydown", (e) => {
      const i = tabs.indexOf(t);
      const next = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault();
      selectTab(tabs[next].dataset.tab, { focus: true, remember: true });
    });
  });
  const startTab = location.hash.slice(1);
  selectTab(tabs.some((t) => t.dataset.tab === startTab) ? startTab : "overview");

  /* ---------- เริ่มต้น ---------- */
  $("cDate").value = todayYmd();   // ค่าเริ่มต้นวันที่ = วันนี้ (ตามเครื่องผู้ใช้)
  $("fDate").value = todayYmd();
  showLoadingPlaceholders();
  load();
  setInterval(() => { if (!document.hidden) load(); }, 30000);   // รีเฟรชทุก 30 วินาที เพื่อเห็นการแก้ไขของคนอื่น
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
})();
