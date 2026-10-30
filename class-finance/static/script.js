/* ระบบการเงินห้อง 5/2 — script.js (เวอร์ชัน Flask)
 * - โหลดข้อมูลทั้งหมดจาก API ของเซิร์ฟเวอร์ (/api/data) แล้ววาดภาพรวม/ประวัติ/นักเรียน/รายงาน
 * - ผู้เก็บเงิน 3 คนล็อกอินด้วยรหัส (ตรวจที่เซิร์ฟเวอร์) เพื่อเพิ่ม/ลบรายรับ-รายจ่าย, เรียกเก็บรายสัปดาห์, รับเงินรายคน
 * - เซิร์ฟเวอร์เป็นผู้บันทึก Log ทุกการแก้ไข (ผู้ชมทั่วไปดูได้อย่างเดียว)
 * - ยอดค้างรายคน = เรียกเก็บรวมทุกครั้ง - ที่คนนั้นจ่าย ทบไปเรื่อย ๆ ไม่มีรีเซ็ต
 * - ป้องกันกดรัวฝั่งหน้าเว็บ (หน่วงต่อปุ่ม + ยืนยันสองจังหวะ) ส่วนฝั่งเซิร์ฟเวอร์มีการหน่วงซ้ำอีกชั้น */
const income = [];   // [Flask] ข้อมูลรายรับมาจาก API (ตาราง transactions) — mergeData() เติมให้
const expense = [];  // [Flask] ข้อมูลรายจ่ายมาจาก API (ตาราง transactions) — mergeData() เติมให้
const students = [
  "ธนากร คงสวัสดิ์","สุทธิลักษณ์ กวางไพร","พีรพล บุญประกอบ","อนันต์ธรรม มีเย็น","อวิยรัช มาลี",
  "กษิเดช ปอสูงเนิน","ภัทรพล นันทะกุล","เกียรติศักดิ์ ทองช้าง","เมธาวินทร์ ไตรทิพย์","ธรรม โซตรง",
  "กลัส ตีวารี","ณัฐธยาน์ เลิศปัญญา","ยุวดี แก้วเทศ","วรินดา เหล่านพกุล","วรพร แซ่โง้ว",
  "พิชญาภา จันทร์โฮง","กัญญาณัฐ แซ่กอ","จุฑารัตน์ อาจศัตรู","อริสดา พันธุชาติ","เบร์รินทร์","เอื้อการย์ ทองนวล"
];
// ยอดค้างของนักเรียนเลขที่ n = ยอดเรียกเก็บรวมทุกครั้ง - ยอดที่คนนั้นจ่ายรวม (ไม่เคยถูกรีเซ็ต)
function debtOf(n){
  const charged = chargeRows.reduce((s,r)=>s+r.amt,0);
  return charged - payRows.filter(r=>r.sid===n).reduce((s,r)=>s+r.amt,0);
}
function renderStudents(){
  const keep = {}; // จำค่าที่ผู้เก็บเงินกำลังพิมพ์ไว้ ไม่ให้หายตอนวาดใหม่
  document.querySelectorAll(".payIn").forEach(i=>keep[i.dataset.sid]=i.value);
  document.getElementById("studentRows").innerHTML = students.map((n,i)=>{
    const d = debtOf(i+1);
    const st = d>0 ? `<span style="color:var(--expense)">ค้าง ${fmt(d)}</span>`
      : d<0 ? `<span style="color:var(--income)">จ่ายล่วงหน้า ${fmt(-d)}</span>` : `<span style="color:var(--income)">ไม่ค้าง</span>`;
    const act = me ? `<td style="text-align:left"><input type="number" class="payIn" data-sid="${i+1}" min="0" step="0.01" placeholder="จ่ายมา (บาท)" value="${esc(keep[i+1]||"")}"> <button class="ghost" data-pay="${i+1}">รับเงิน</button></td>` : "";
    return `<tr><td>${i+1}</td><td>${esc(n)}</td><td>${st}</td>${act}</tr>`;
  }).join("");
  const owed = students.reduce((s,_,i)=>s+Math.max(0,debtOf(i+1)),0);
  document.getElementById("stuSummary").textContent = `เรียกเก็บแล้ว ${chargeRows.length} ครั้ง (รวม ${fmt(chargeRows.reduce((s,r)=>s+r.amt,0))} ต่อคน) · ยอดค้างรวมทุกคน ${fmt(owed)}`;
  // ประวัติเรียกเก็บ/รับเงิน (ล่าสุดอยู่บน, แสดง 100 รายการ)
  const hist = [...chargeRows.map(r=>({...r,k:"charge"})), ...payRows.map(r=>({...r,k:"pay"}))].sort((a,b)=>b.ts-a.ts).slice(0,100);
  document.getElementById("stuHist").innerHTML = hist.map(r=>`<tr><td>${thDate(r.d)}</td>
    <td>${r.k==="charge" ? "เรียกเก็บทุกคน" : "รับเงิน เลขที่ "+r.sid+" "+esc(students[r.sid-1]||"")}</td>
    <td>${fmt(r.amt)}</td><td>${esc(r.by)}</td>${me?`<td><button class="ghost" data-delst="${r.k}:${esc(r.id)}">🗑️</button></td>`:""}</tr>`).join("")
    || `<tr><td style="color:var(--muted)">ยังไม่มีรายการ</td></tr>`;
}

// ===== [เพิ่มใหม่] ข้อมูลพื้นฐาน + ตัวช่วย =====
income.forEach((r,i)=>r.id="in-"+i);      // id คงที่ของรายการพื้นฐาน ใช้ตอนลบ (บันทึกเป็น tombstone ใน db)
expense.forEach((r,i)=>r.id="out-"+i);
const baseIncome = income.slice();        // สำเนารายการพื้นฐาน (income/expense จะถูกรวมใหม่ทุกครั้งที่ db เปลี่ยน)
const baseExpense = expense.slice();
const esc = s => String(s??"").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); // กัน XSS จากข้อความที่กรอก
let chargeRows = [], payRows = []; // [เพิ่มใหม่] รายการเรียกเก็บ / รายการรับเงินรายคน (จาก db)
let txRows = [], delIds = new Set(), auditRows = []; // ข้อมูลที่ได้จาก db: รายการที่เพิ่ม / id พื้นฐานที่ถูกลบ / log
let me = null, dbh = null, uid = null, userEmail = "";    // ผู้เก็บเงินที่ล็อกอิน, ตัว db, id ผู้ชม
function mergeData(){                     // รวมข้อมูลพื้นฐาน (ตัดที่ถูกลบ) + รายการจาก db เข้า income/expense
  income.length = 0; expense.length = 0;
  baseIncome.filter(r=>!delIds.has(r.id)).forEach(r=>income.push(r));
  baseExpense.filter(r=>!delIds.has(r.id)).forEach(r=>expense.push(r));
  txRows.forEach(r=>(r.type==="in"?income:expense).push(r));
}

const fmt = n => "฿" + n.toLocaleString("th-TH",{minimumFractionDigits:2,maximumFractionDigits:2});
const thDate = s => new Date(s).toLocaleDateString("th-TH",{year:"numeric",month:"short",day:"numeric"});
const thMonth = s => new Date(s+"-01").toLocaleDateString("th-TH",{year:"numeric",month:"long"});

let totalIn = 0, totalOut = 0;
const all = [];
function renderOverview(){ // คำนวณและวาดภาพรวม/หมวดหมู่/รายงานรายเดือนใหม่ทั้งหมด
mergeData();
totalIn = income.reduce((s,r)=>s+r.amt,0);
totalOut = expense.reduce((s,r)=>s+r.amt,0);
document.getElementById("totalIn").textContent = fmt(totalIn);
document.getElementById("totalOut").textContent = fmt(totalOut);
document.getElementById("balance").textContent = fmt(totalIn-totalOut);
document.getElementById("countIn").textContent = income.length + " รายการ";
document.getElementById("countOut").textContent = expense.length + " รายการ";

function catSummary(list){
  const m = {};
  list.forEach(r=>{ m[r.cat]=(m[r.cat]||0)+r.amt; });
  return Object.entries(m).sort((a,b)=>b[1]-a[1]);
}
function renderCat(el, data, total){
  el.innerHTML = data.map(([cat,amt])=>`
    <div class="catrow">
      <div class="meta"><span>${esc(cat)}</span><span>${fmt(amt)}</span></div>
      <div class="bar"><span style="width:${(amt/total*100).toFixed(1)}%"></span></div>
    </div>`).join("");
}
renderCat(document.getElementById("catIn"), catSummary(income), totalIn);
renderCat(document.getElementById("catOut"), catSummary(expense), totalOut);

all.length = 0;
all.push(...[
  ...income.map(r=>({...r, type:"in"})),
  ...expense.map(r=>({...r, type:"out"})),
].sort((a,b)=> a.d.localeCompare(b.d)));

document.getElementById("latestRows").innerHTML = [...all].sort((a,b)=>b.d.localeCompare(a.d)).slice(0,5).map(r=>`
  <tr>
    <td>${thDate(r.d)}</td>
    <td><span class="tag ${r.type}">${r.type==="in"?"รายรับ":"รายจ่าย"}</span> ${esc(r.item)}</td>
    <td style="text-align:right;color:${r.type==="in"?"var(--income)":"var(--expense)"}">${r.type==="in"?"+":"-"}${fmt(r.amt)}</td>
  </tr>`).join("");

const months = {};
all.forEach(r=>{
  const m = r.d.slice(0,7);
  months[m] = months[m] || {in:0,out:0};
  months[m][r.type] += r.amt;
});
let running = 0;
document.getElementById("monthRows").innerHTML = Object.keys(months).sort().map(m=>{
  const {in:mi=0,out:mo=0} = months[m];
  running += mi-mo;
  return `<tr><td>${thMonth(m)}</td><td style="color:var(--income)">+${fmt(mi)}</td>
    <td style="color:var(--expense)">-${fmt(mo)}</td><td>${fmt(mi-mo)}</td><td>${fmt(running)}</td></tr>`;
}).join("");
}

const catSel = document.getElementById("catFilter");
function renderCatOptions(){ // เติมตัวเลือกหมวดหมู่ใหม่ (คงค่าที่เลือกไว้)
const keep = catSel.value;
while(catSel.options.length>1) catSel.remove(1);
[...new Set(all.map(r=>r.cat))].sort().forEach(c=>{
  const o = document.createElement("option"); o.value=c; o.textContent=c; catSel.appendChild(o);
});
catSel.value = keep;
}

let currentType = "all", sortKey="d", sortDir=1;
function getRows(){
  const q = document.getElementById("search").value.trim().toLowerCase();
  const cat = catSel.value;
  const from = document.getElementById("dateFrom").value;
  const to = document.getElementById("dateTo").value;
  let rows = all.filter(r=>{
    if(currentType!=="all" && r.type!==currentType) return false;
    if(cat && r.cat!==cat) return false;
    if(from && r.d<from) return false;
    if(to && r.d>to) return false;
    if(q && !(r.item+r.cat).toLowerCase().includes(q)) return false;
    return true;
  });
  rows.sort((a,b)=> (a[sortKey]>b[sortKey]?1:-1)*sortDir);
  return rows;
}
function render(){
  const rows = getRows();
  document.getElementById("rows").innerHTML = rows.map(r=>`
    <tr>
      <td>${thDate(r.d)}</td>
      <td><span class="tag ${r.type}">${r.type==="in"?"รายรับ":"รายจ่าย"}</span> ${esc(r.item)}${r.note?`<div style="color:var(--muted);font-size:12px">${esc(r.note)}</div>`:""}</td>
      <td>${esc(r.cat)}</td>
      <td style="color:${r.type==="in"?"var(--income)":"var(--expense)"}">${r.type==="in"?"+":"-"}${fmt(r.amt)}</td>
      <td>${r.type==="out" ? '<span class="tag out">ยังไม่มีหลักฐาน</span>' : '<span style="color:var(--muted)">-</span>'}</td>${me?`<td>${r.pid?'<span style="color:var(--muted);font-size:12px" title="ลบที่แท็บนักเรียน">จากการรับเงิน</span>':`<button class="ghost" data-del="${esc(r.id)}">🗑️</button>`}</td>`:""}
    </tr>`).join("") || `<tr><td colspan="${me?6:5}" style="text-align:center;color:var(--muted)">ไม่พบรายการ</td></tr>`;
}
["search","catFilter","dateFrom","dateTo"].forEach(id=>{
  document.getElementById(id).addEventListener("input", render);
  document.getElementById(id).addEventListener("change", render);
});
document.querySelectorAll("#typeToggle button").forEach(b=>{
  b.addEventListener("click", ()=>{
    document.querySelectorAll("#typeToggle button").forEach(x=>x.classList.remove("active"));
    b.classList.add("active"); currentType = b.dataset.type; render();
  });
});
document.querySelectorAll("th.sortable").forEach(th=>{
  th.addEventListener("click", ()=>{
    const k = th.dataset.k;
    sortDir = (sortKey===k) ? -sortDir : 1;
    sortKey = k; render();
  });
});
function refreshAll(){ renderOverview(); renderCatOptions(); render(); renderStudents(); } // วาดทุกส่วนใหม่เมื่อข้อมูลเปลี่ยน
refreshAll();

document.querySelectorAll("nav.tabs button").forEach(btn=>{
  btn.addEventListener("click", ()=>{
    document.querySelectorAll("nav.tabs button").forEach(b=>b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p=>p.classList.remove("active"));
    btn.classList.add("active");
    document.querySelector(`.panel[data-panel="${btn.dataset.tab}"]`).classList.add("active");
  });
});

// ส่งออก CSV: ดาวน์โหลดไฟล์ผ่านเบราว์เซอร์ตามปกติ (BOM ให้ Excel อ่านภาษาไทยถูก)
document.getElementById("exportBtn").addEventListener("click", ()=>{
  const rows = getRows();
  const header = "วันที่,ประเภท,รายการ,หมวดหมู่,จำนวนเงิน\n";
  const body = rows.map(r=>[r.d, r.type==="in"?"รายรับ":"รายจ่าย", r.item, r.cat, r.amt]
    .map(v=>`"${String(v).replace(/"/g,'""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["\uFEFF"+header+body], {type:"text/csv;charset=utf-8"}));
  a.download = "room502_transactions.csv"; a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 1000);
});

// ===== [Flask] เชื่อมต่อ API ฝั่งเซิร์ฟเวอร์ =====
const $ = id => document.getElementById(id);
const today = () => { const d=new Date(); return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0"); }; // วันที่ตามเครื่องผู้ใช้ (ไม่ใช้ UTC)
const ERR = {invalid_token:"รหัสไม่ถูกต้อง", too_many_attempts:"ใส่รหัสผิดหลายครั้ง กรุณารอสักครู่", too_fast:"ทำรายการเร็วเกินไป กรุณารอสักครู่",
  invalid_input:"ข้อมูลไม่ถูกต้อง", not_found:"ไม่พบรายการ", unauthorized:"กรุณาเข้าสู่ระบบใหม่", linked_to_payment:"รายรับนี้มาจากการรับเงินนักเรียน — ลบได้ที่แท็บนักเรียน > ประวัติการเรียกเก็บ/รับเงิน", bad_csrf:"หน้าเว็บหมดอายุ กรุณารีเฟรช"};
function say(t, err){ const m=$("msg"); m.textContent=t; m.style.color = err ? "var(--expense)" : "var(--income)"; } // ข้อความสถานะส่วนกลาง
// เรียก API พร้อมแนบ CSRF token; คืนค่า {ok, ...} เสมอ (ไม่ throw)
async function api(path, method="GET", body){
  try{
    const r = await fetch(path, {method, credentials:"same-origin",
      headers:{"Content-Type":"application/json", "X-CSRF-Token":document.querySelector('meta[name="csrf"]').content},
      body: body ? JSON.stringify(body) : undefined});
    const j = await r.json().catch(()=>({}));
    return (j.ok===undefined) ? {ok:false, error:"http_"+r.status} : j;
  }catch(e){ return {ok:false, error:"network"}; }
}
// โหลดข้อมูลทั้งหมดจากเซิร์ฟเวอร์ แล้ววาดทุกส่วนใหม่
async function load(){
  const j = await api("/api/data");
  if(!j.ok){ say("โหลดข้อมูลไม่สำเร็จ ("+j.error+")", true); return; }
  txRows = j.transactions; chargeRows = j.charges; payRows = j.payments; auditRows = j.audit; me = j.me;
  refreshAll(); applyAuth();
}
// วาดตาราง Log (ล่าสุดอยู่บน) — คอลัมน์อีเมลเห็นเฉพาะผู้เก็บเงินที่ล็อกอิน
function renderAudit(){
  const L = {login:"เข้าสู่ระบบ", logout:"ออกจากระบบ", add_transaction:"เพิ่มรายการ", delete_transaction:"ลบรายการ",
    create_charge:"เรียกเก็บเงิน", record_payment:"รับเงินนักเรียน", delete_charge:"ลบรายการเรียกเก็บ", delete_payment:"ลบรายการรับเงิน"};
  $("auditRows").innerHTML = auditRows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString("th-TH")}</td><td>${esc(r.by)}</td><td>${L[r.action]||esc(r.action)}</td>
    <td>${esc(r.detail||"-")}</td>${me?`<td>${esc(r.email||"-")}</td>`:""}</tr>`).join("")
    || `<tr><td colspan="4" style="color:var(--muted)">ยังไม่มีบันทึก</td></tr>`;
}
// แสดง/ซ่อนส่วนของผู้เก็บเงินตามสถานะล็อกอิน
function applyAuth(){
  $("loginBox").hidden = !!me; $("whoBox").hidden = !me; $("adminForm").hidden = !me; $("actTh").hidden = !me;
  $("whoName").textContent = me || "";
  $("histBar").hidden = !me; $("chargeBar").hidden = !me; $("stuActTh").hidden = !me; $("audEmailTh").hidden = !me;
  render(); renderStudents(); renderAudit();
}
// ล็อกอิน / ออกจากระบบ (ตรวจรหัสและบันทึก log ที่เซิร์ฟเวอร์)
$("loginBtn").addEventListener("click", async ()=>{
  const j = await api("/api/login", "POST", {token:$("tokenIn").value.trim(), email:$("emailIn").value.trim()});
  if(!j.ok){ say(ERR[j.error]||"เข้าสู่ระบบไม่สำเร็จ", true); return; }
  $("tokenIn").value = ""; say("เข้าสู่ระบบเป็น "+j.name); load();
});
$("logoutBtn").addEventListener("click", async ()=>{ await api("/api/logout", "POST"); say(""); load(); });

const lastClick = {};             // เวลาคลิกล่าสุดของแต่ละปุ่ม
document.addEventListener("click", e=>{ // ดักก่อนตัวจัดการอื่น: ปุ่มเดิมต้องคลิกห่างกัน >= 1.5 วินาที
  const b = e.target.closest("#loginBtn,#logoutBtn,#addBtn,#chargeBtn,[data-del],[data-pay],[data-delst]"); if(!b) return;
  const k = b.id || (b.dataset.del || b.dataset.pay || b.dataset.delst), now = Date.now();
  if(now-(lastClick[k]||0) < 1500){ e.stopImmediatePropagation(); e.preventDefault(); return; }
  lastClick[k] = now;
}, true);
// ช่วยส่งคำขอแล้วแสดงผล: สำเร็จ -> โหลดข้อมูลใหม่, ล้มเหลว -> แสดงข้อผิดพลาด
async function act(promise, okMsg){
  const j = await promise;
  if(!j.ok){ say(ERR[j.error]||("ไม่สำเร็จ ("+j.error+")"), true); return false; }
  say(okMsg); await load(); return true;
}
// เพิ่มรายการรายรับ/รายจ่าย
$("addBtn").addEventListener("click", async ()=>{
  if(!me) return;
  const row = {type:$("fType").value, d:$("fDate").value, item:$("fItem").value.trim(), cat:$("fCat").value.trim(), amt:Number($("fAmt").value), note:$("fNote").value.trim()};
  if(!row.d || !row.item || !(row.amt>0)){ say("กรอกวันที่ รายการ และจำนวนเงิน (มากกว่า 0) ให้ครบ", true); return; }
  if(await act(api("/api/transactions","POST",row), "บันทึกรายการแล้ว")) ["fItem","fCat","fAmt","fNote"].forEach(id=>$(id).value="");
});
// ลบรายการรายรับ/รายจ่าย (กดครั้งแรก = ขอยืนยัน, กดซ้ำหลัง 1.5 วิ แต่ไม่เกิน 4 วิ = ลบจริง)
$("rows").addEventListener("click", async e=>{
  const b = e.target.closest("button[data-del]"); if(!b || !me) return;
  if(!b.dataset.armed){ b.dataset.armed = "1"; b.textContent = "ยืนยันลบ?"; setTimeout(()=>{ b.dataset.armed=""; b.textContent="🗑️"; }, 4000); return; }
  act(api("/api/transactions/"+encodeURIComponent(b.dataset.del), "DELETE"), "ลบรายการแล้ว");
});
// เรียกเก็บทุกคน: กดครั้งแรกขอยืนยัน กดซ้ำจึงบันทึก (เรียกซ้ำได้ ยอดค้างจะทบเพิ่ม)
$("cDate").value = today();       // ค่าเริ่มต้นวันที่เรียกเก็บ = วันนี้
$("chargeBtn").addEventListener("click", async ()=>{
  const b = $("chargeBtn"), amt = Number($("cAmt").value), d = $("cDate").value || today();
  if(!me) return;
  if(!(amt>0)){ say("ใส่จำนวนเงินที่เรียกเก็บ (มากกว่า 0)", true); return; }
  if(!b.dataset.armed){ b.dataset.armed="1"; b.textContent = "ยืนยันเรียกเก็บ "+fmt(amt)+"?"; setTimeout(()=>{ b.dataset.armed=""; b.textContent="เรียกเก็บทุกคน"; }, 4000); return; }
  b.dataset.armed = ""; b.textContent = "เรียกเก็บทุกคน";
  act(api("/api/charges","POST",{amt, d}), "เรียกเก็บเงินทุกคนแล้ว");
});
// รับเงินจากนักเรียนรายคน (ยอดค้างลดลงตามที่จ่าย)
$("studentRows").addEventListener("click", async e=>{
  const b = e.target.closest("button[data-pay]"); if(!b || !me) return;
  const sid = Number(b.dataset.pay), inp = document.querySelector('.payIn[data-sid="'+sid+'"]'), amt = Number(inp.value);
  if(!(amt>0)){ say("ใส่จำนวนเงินที่จ่ายมา (มากกว่า 0)", true); return; }
  if(await act(api("/api/payments","POST",{sid, amt}), "บันทึกการรับเงินแล้ว")) inp.value = "";
});
// ลบรายการเรียกเก็บ/รับเงินที่กรอกผิดทีละรายการ (ไม่มีการรีเซ็ตทั้งหมด) — กดซ้ำเพื่อยืนยัน
$("stuHist").addEventListener("click", async e=>{
  const b = e.target.closest("button[data-delst]"); if(!b || !me) return;
  if(!b.dataset.armed){ b.dataset.armed="1"; b.textContent="ยืนยันลบ?"; setTimeout(()=>{ b.dataset.armed=""; b.textContent="🗑️"; }, 4000); return; }
  const [k, id] = b.dataset.delst.split(":");
  act(api("/api/"+(k==="charge"?"charges":"payments")+"/"+encodeURIComponent(id), "DELETE"), "ลบรายการแล้ว");
});
// เริ่มต้น: โหลดข้อมูล และรีเฟรชทุก 30 วินาทีเพื่อให้เห็นการแก้ไขของคนอื่น (เว้นตอนแท็บถูกซ่อน)
load();
setInterval(()=>{ if(!document.hidden) load(); }, 30000);
