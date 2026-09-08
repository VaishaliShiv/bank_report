let DATA = [];
const $ = id => document.getElementById(id);
const aed = n => (n ?? 0).toLocaleString("en-AE",{minimumFractionDigits:2,maximumFractionDigits:2});
const abbr = n => Math.abs(n) >= 1e6 ? (n/1e6).toFixed(2)+"M"
                : Math.abs(n) >= 1e3 ? (n/1e3).toFixed(2)+"K" : (n??0).toFixed(2);
const int = n => (n ?? 0).toLocaleString("en-AE");
const fmtD = s => new Date(s+"T00:00:00").toLocaleDateString("en-GB",
  {day:"2-digit",month:"long",year:"numeric"});

// anomaly types, each with its own colour so the composition bar reads without a key
const ANOM = [
  ["missingInSap",      "Missing in SAP",      "var(--red)"],
  ["missingInPartner",  "Missing in partner",  "#cf7f57"],
  ["sapAmountHigh",     "SAP amount high",     "var(--amber)"],
  ["partnerAmountHigh", "Partner amount high", "#c9a53f"],
  ["duplicates",        "Duplicate",           "var(--cyan)"],
  ["dateDifferences",   "Date difference",     "var(--teal)"],
];

let DATES = [];
let state = {date:null, filter:"all", q:""};

/* ---------- small chart primitives ---------- */
const GAUGE_HUE = {match:"var(--green)", source:"var(--amber)", value:"var(--cyan)"};
function gauge(pct, label, sub, tone, hue){
  const R=54, CX=68, CY=62, LEN=Math.PI*R;
  const on = LEN * Math.min(Math.max(pct,0),100)/100;
  // severity wins when something is actually wrong; otherwise the reference hue
  const col = tone==="crit" ? "var(--red)" : tone==="warn" ? "var(--amber)" : hue;
  const gid = "g"+Math.random().toString(36).slice(2,9);
  return `<div class="gauge">
    <svg viewBox="0 0 136 76" role="img" aria-label="${label}: ${pct.toFixed(1)} percent">
      <defs><linearGradient id="${gid}" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="${col}"/><stop offset="100%" stop-color="${col}" stop-opacity=".55"/>
      </linearGradient></defs>
      <path d="M ${CX-R} ${CY} A ${R} ${R} 0 0 1 ${CX+R} ${CY}" fill="none"
        stroke="var(--surface-3)" stroke-width="13" stroke-linecap="round"/>
      <path d="M ${CX-R} ${CY} A ${R} ${R} 0 0 1 ${CX+R} ${CY}" fill="none"
        stroke="url(#${gid})" stroke-width="13" stroke-linecap="round"
        stroke-dasharray="${on} ${LEN}"/>
    </svg>
    <span class="gv" style="color:${col}">${pct.toFixed(1)}%</span>
    <span class="gl">${label}</span><span class="gs">${sub}</span></div>`;
}

function donut(ok, bad){
  const total = ok+bad, R=54, C=2*Math.PI*R, pct = total ? ok/total*100 : 0;
  return `<div class="donut" style="width:146px;height:146px">
    <svg width="146" height="146" viewBox="0 0 146 146" role="img"
      aria-label="${ok} of ${total} sources reconciled">
      <circle cx="73" cy="73" r="${R}" fill="none" stroke="var(--red)" stroke-width="17"/>
      <circle cx="73" cy="73" r="${R}" fill="none" stroke="var(--green)" stroke-width="17"
        stroke-dasharray="${C*(total?ok/total:0)} ${C}" transform="rotate(-90 73 73)"/>
    </svg>
    <div class="mid"><span class="n">${pct.toFixed(1)}%</span><span class="t">Reconciled</span></div>
  </div>`;
}

/* per-exception graphics: a match meter and an anomaly composition bar */
function excCharts(r){
  const rate = r.matchRatePct ?? 0;
  const present = ANOM.filter(([k])=>r[k]>0);
  const totalAnom = present.reduce((s,[k])=>s+r[k],0) || 1;
  const comp = present.map(([k,l,c])=>
    `<span style="width:${r[k]/totalAnom*100}%;background:${c}" title="${l}: ${r[k]}"></span>`).join("");
  const chips = present.map(([k,l,c])=>
    `<span class="chip"><i style="background:${c}"></i>${l} <b>${r[k]}</b></span>`).join("");
  const atRisk = r.amountPartner ? Math.abs(r.balanceDifference)/r.amountPartner*100 : 0;
  return `<div style="display:flex;flex-direction:column;gap:12px">
    <div class="meter">
      <div class="mh"><span>Records matched</span>
        <span class="num" style="font-weight:700;color:var(--ink)">${rate.toFixed(2)}%</span></div>
      <div class="mtrack">
        <span style="width:${rate}%;background:linear-gradient(90deg,var(--teal-dk),var(--teal-lt))"></span>
        <span style="width:${100-rate}%;background:var(--critical)"></span>
      </div>
      <div class="mh"><span>${int(r.matched)} of ${int(r.recordsPartner)} records</span>
        <span>${int(r.recordsPartner-r.matched)} unmatched</span></div>
    </div>
    <div class="meter">
      <div class="mh"><span>Anomaly composition</span>
        <span class="num" style="font-weight:700;color:var(--ink)">${int(r.anomalies)} total</span></div>
      <div class="mtrack">${comp || '<span style="width:100%;background:var(--surface-3)"></span>'}</div>
      <div class="chips">${chips || '<span class="chip">No anomaly codes recorded</span>'}</div>
    </div>
    <div class="meter">
      <div class="mh"><span>Value unconfirmed</span>
        <span class="num" style="font-weight:700;color:var(--red-dk)">${atRisk.toFixed(2)}%</span></div>
      <div class="mtrack">
        <span style="width:${Math.min(atRisk,100)}%;background:var(--critical)"></span>
        <span style="width:${Math.max(100-atRisk,0)}%;background:var(--surface-3)"></span>
      </div>
      <div class="mh"><span>AED ${aed(Math.abs(r.balanceDifference))} of ${aed(r.amountPartner)}</span></div>
    </div>
  </div>`;
}

function barsHTML(vals, fmt){
  // One colour for every bar: the chart's job is ranking, and a second hue
  // competes with that. Status is flagged with a dot and the value colour,
  // which stays legible even when most sources have not reconciled.
  const max = Math.max(...vals.map(v=>v[1]), 1);
  return vals.sort((a,b)=>b[1]-a[1]).map(([n,v,unrec])=>
    `<div class="bar"><span class="bn" title="${n}${unrec?" - not reconciled":""}">
        ${unrec?'<i class="sdot" aria-label="not reconciled"></i>':""}${n}</span>
      <span class="blane"><span class="track"><span class="fill"
        style="width:${Math.max(v/max*100,1.2)}%"></span></span>
      <span class="bv${unrec?" unrec":""}">${fmt(v)}</span></span></div>`).join("");
}

/* ---------- page ---------- */
function render(){
  $("dpick").value = state.date;
  const i = DATES.indexOf(state.date);
  $("prev").disabled = i <= 0;
  $("next").disabled = i < 0 || i >= DATES.length-1;

  const all = DATA.filter(r=>r.date===state.date);
  if (!all.length){
    $("page").innerHTML = `<section class="panel"><div class="empty">
      <b>No reconciliation ran on ${fmtD(state.date)}</b>
      Available dates: ${DATES.map(d=>fmtD(d)).join(" &middot; ")}</div></section>`;
    return;
  }

  const q = state.q.trim().toLowerCase();
  const shown = all.filter(r=>{
    if (state.filter==="ok"  && r.status!=="Reconciled") return false;
    if (state.filter==="bad" && r.status==="Reconciled") return false;
    return !q || (r.source+" "+r.vendorId+" "+(r.summary||"")).toLowerCase().includes(q);
  });

  const bad     = all.filter(r=>r.status!=="Reconciled");
  const recs    = all.reduce((s,r)=>s+r.recordsPartner,0);
  const matched = all.reduce((s,r)=>s+r.matched,0);
  const anom    = all.reduce((s,r)=>s+r.anomalies,0);
  const val     = all.reduce((s,r)=>s+r.amountPartner,0);
  const valOk   = all.filter(r=>r.status==="Reconciled").reduce((s,r)=>s+r.amountPartner,0);
  const diff    = all.reduce((s,r)=>s+r.balanceDifference,0);
  const reruns  = all.reduce((s,r)=>s+r.runCount-1,0);
  const varied  = all.filter(r=>r.figuresVariedAcrossRuns);

  $("cAll").textContent = all.length;
  $("cOk").textContent  = all.length - bad.length;
  $("cBad").textContent = bad.length;
  document.querySelectorAll(".seg button").forEach(b=>{
    const n = b.dataset.f==="all" ? all.length
            : b.dataset.f==="ok"  ? all.length-bad.length : bad.length;
    b.dataset.empty = n === 0;
  });

  const mRate = recs ? matched/recs*100 : 0;
  const sRate = all.length ? (all.length-bad.length)/all.length*100 : 0;
  const vRate = val ? valOk/val*100 : 0;
  const tone  = p => p>=99 ? "" : p>=80 ? "warn" : "crit";

  const kpis = [
    ["Total transactions", int(recs), "", `across ${all.length} source${all.length===1?"":"s"}`],
    ["Successfully matched", int(matched), matched===recs?"good":"",
      `${recs?(matched/recs*100).toFixed(2):"0"}% of records`],
    ["Reconciled amount", `<small>AED </small>${abbr(valOk)}`, valOk?"good":"crit",
      `of AED ${abbr(val)} processed`],
    ["Balance difference", `<small>AED </small>${abbr(diff)}`, diff?"crit":"good",
      "partner file minus SAP"],
    ["Source exceptions", int(bad.length), bad.length?"crit":"good",
      bad.length ? `${int(anom)} anomalies to clear` : "none outstanding"],
  ].map(([l,v,c,f])=>`<div class="kpi ${c}"><span class="lbl">${l}</span>
      <span class="v">${v}</span><span class="f">${f}</span></div>`).join("");

  const excList = bad.slice().sort((a,b)=>Math.abs(b.balanceDifference)-Math.abs(a.balanceDifference));
  const excHTML = excList.length ? excList.map(r=>`
    <div class="exc-row"><span class="stripe"></span><div class="exc-body">
      <div class="exc-top"><span class="nm">${r.source}</span>
        <span class="vid">${r.vendorId}</span>
        <span class="pill bad">${int(r.anomalies)} anomal${r.anomalies===1?"y":"ies"}</span>
        ${r.runCount>1?`<span class="pill" style="color:var(--warning);background:var(--warning-soft);border-color:var(--warning-line)">${r.runCount} runs &middot; latest shown</span>`:""}
      </div>
      <div class="exc-grid">
        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="facts">
            <span class="fact"><span class="lbl">Records</span><span class="fv">${int(r.recordsPartner)}</span></span>
            <span class="fact"><span class="lbl">Matched</span><span class="fv">${int(r.matched)}</span></span>
            <span class="fact"><span class="lbl">Match rate</span>
              <span class="fv ${(r.matchRatePct??0)<95?"neg":""}">${(r.matchRatePct??0).toFixed(2)}%</span></span>
            <span class="fact"><span class="lbl">Difference</span>
              <span class="fv ${r.balanceDifference?"neg":""}">AED ${aed(r.balanceDifference)}</span></span>
          </div>
          ${r.summary?`<div class="why"><b>Pipeline assessment &middot; </b>${r.summary}</div>`:""}
        </div>
        ${excCharts(r)}
      </div>
    </div></div>`).join("")
    : `<div class="empty"><b>Every source reconciled</b>Nothing outstanding on this date.</div>`;

  $("page").innerHTML = `
    <div class="kpis">${kpis}</div>

    <div class="grid-2" style="margin-top:15px">
      <section class="panel">
        <div class="ph"><div><h3>Reconciliation health</h3>
          <p>Three independent measures &mdash; each answers a different question</p></div></div>
        <div class="pb"><div class="gauges">
          ${gauge(mRate,"Transaction match",`${int(matched)} of ${int(recs)}`,tone(mRate),GAUGE_HUE.match)}
          ${gauge(sRate,"Source completion",`${all.length-bad.length} of ${all.length} sources`,tone(sRate),GAUGE_HUE.source)}
          ${gauge(vRate,"Value reconciled",`AED ${abbr(valOk)} of ${abbr(val)}`,tone(vRate),GAUGE_HUE.value)}
        </div></div>
      </section>
      <section class="panel">
        <div class="ph"><div><h3>Source status</h3><p>Completion by bank and vendor feed</p></div></div>
        <div class="pb"><div class="donut-row">${donut(all.length-bad.length, bad.length)}
          <div class="legend">
            <div class="leg"><span class="sw" style="background:var(--green)"></span>
              <span class="nm">Reconciled</span><span class="ct">${all.length-bad.length}</span></div>
            <div class="leg"><span class="sw" style="background:var(--red)"></span>
              <span class="nm">Needs action</span><span class="ct">${bad.length}</span></div>
            <div class="leg"><span class="sw" style="background:var(--amber)"></span>
              <span class="nm">Anomalies detected</span><span class="ct">${int(anom)}</span></div>
            <div class="leg"><span class="sw" style="background:var(--border-strong)"></span>
              <span class="nm">Duplicate runs collapsed</span><span class="ct">${reruns}</span></div>
          </div></div></div>
      </section>
    </div>

    <section class="panel" style="margin-top:15px">
      <div class="ph"><div><h3>Requires action</h3>
        <p>Sources that did not reconcile, with the pipeline&rsquo;s own assessment</p></div>
        <span class="lbl">${excList.length} of ${all.length}</span></div>
      ${excHTML}
    </section>

    ${all.length < 3 ? `<section class="panel" style="margin-top:15px">
      <div class="ph"><div><h3>Source comparison</h3>
        <p>Ranking charts appear when three or more sources reported</p></div></div>
      <div class="chartskip">Only ${all.length} source${all.length===1?"":"s"} on this date &mdash;
        the table below already shows everything a ranking chart would.</div>
    </section>` : `
    <div class="grid-half" style="margin-top:15px">
      <section class="panel">
        <div class="ph"><div><h3>Reconciled amount by source</h3><p>Ranked by AED value</p></div></div>
        <div class="pb"><div class="bars">${barsHTML(
          all.map(r=>[r.source, r.amountPartner, r.status!=="Reconciled"]), v=>"AED "+abbr(v))}</div>
          <p class="chartnote">A red dot marks a source that did not reconcile
            &mdash; its value is reported, not confirmed.</p></div>
      </section>
      <section class="panel">
        <div class="ph"><div><h3>Transaction volume</h3><p>Records processed per source</p></div></div>
        <div class="pb"><div class="bars">${barsHTML(
          all.map(r=>[r.source, r.recordsPartner, r.status!=="Reconciled"]), int)}</div>
          <p class="chartnote">Volume and value rank differently &mdash;
            that gap is where risk hides.</p></div>
      </section>
    </div>`}

    <section class="panel" style="margin-top:15px">
      <div class="ph"><div><h3>Reconciliation detail</h3>
        <p>${shown.length===all.length
            ? `All ${all.length} source${all.length===1?"":"s"}`
            : `${shown.length} of ${all.length} sources`
              + (state.filter==="ok" ? " &middot; filtered to reconciled"
               : state.filter==="bad" ? " &middot; filtered to exceptions" : "")
              + (state.q ? ` &middot; matching &ldquo;${state.q}&rdquo;` : "")}</p></div></div>
      <div class="tw"><table>
        <thead><tr><th>Bank / source</th><th>Vendor</th><th class="r">Records</th>
          <th class="r">Matched</th><th class="r">Anomalies</th><th class="r">Match&nbsp;%</th>
          <th class="r">Partner AED</th><th class="r">SAP AED</th><th class="r">Difference</th>
          <th>Status</th></tr></thead>
        <tbody>${shown.slice().sort((a,b)=>b.recordsPartner-a.recordsPartner).map(r=>`<tr>
          <td><b>${r.source}</b>${r.runCount>1?`<span class="rerun">${r.runCount}&times;</span>`:""}</td>
          <td class="num" style="color:var(--ink-3)">${r.vendorId}</td>
          <td class="n">${int(r.recordsPartner)}</td><td class="n">${int(r.matched)}</td>
          <td class="n${r.anomalies?" neg":""}">${int(r.anomalies)}</td>
          <td class="n">${(r.matchRatePct??0).toFixed(2)}</td>
          <td class="n">${aed(r.amountPartner)}</td><td class="n">${aed(r.amountSap)}</td>
          <td class="n${r.balanceDifference?" neg":""}">${aed(r.balanceDifference)}</td>
          <td><span class="pill ${r.status==="Reconciled"?"ok":"bad"}">${r.status}</span></td>
        </tr>`).join("") || `<tr><td colspan="10" class="empty">
          <b>${ state.q ? "Nothing matches your search"
               : state.filter==="ok" ? "No sources reconciled on this date"
               : state.filter==="bad" ? "No exceptions on this date"
               : "No sources on this date" }</b>
          ${ state.q ? `No bank, vendor ID or assessment contains &ldquo;${state.q}&rdquo;.`
             : state.filter==="ok"
               ? `All ${all.length} source${all.length===1?"":"s"} on ${fmtD(state.date)}
                  ${all.length===1?"is":"are"} still awaiting reconciliation.`
             : state.filter==="bad"
               ? `Every source reconciled cleanly on ${fmtD(state.date)}.`
               : "" }
          <button class="clearf" id="clearf">Show all ${all.length} source${all.length===1?"":"s"}</button>
        </td></tr>`}
        </tbody></table></div>
    </section>

    <div class="note ${varied.length?"warn":""}" style="margin-top:15px">${
      varied.length
        ? `<b>Warning &middot; </b>${varied.map(r=>r.source).join(", ")} produced different figures
           across re-runs on this date. The latest run is shown &mdash; verify which is
           authoritative before reporting these numbers.`
        : reruns
          ? `<b>Deduplication applied &middot; </b>${reruns} duplicate run${reruns===1?"":"s"}
             collapsed. The source table logs every reconciliation run, so a re-run would
             otherwise be counted twice. Figures were identical across runs.`
          : `<b>Deduplication &middot; </b>No re-runs on this date. Each source reported once.`
    }</div>`;
  const cf = $("clearf");
  if (cf) cf.addEventListener("click", ()=>{
    state.filter = "all"; state.q = ""; $("q").value = "";
    document.querySelectorAll(".seg button").forEach(x=>
      x.setAttribute("aria-pressed", x.dataset.f==="all" ? "true" : "false"));
    render();
  });
}

/* ---------- wiring ---------- */
$("dpick").addEventListener("change", e => { state.date = e.target.value; render(); });
$("prev").addEventListener("click", ()=>{
  const i = DATES.indexOf(state.date); if (i>0){ state.date = DATES[i-1]; render(); }});
$("next").addEventListener("click", ()=>{
  const i = DATES.indexOf(state.date); if (i>=0 && i<DATES.length-1){ state.date = DATES[i+1]; render(); }});
$("q").addEventListener("input", e => { state.q = e.target.value; render(); });
document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", ()=>{
  document.querySelectorAll(".seg button").forEach(x=>x.setAttribute("aria-pressed","false"));
  b.setAttribute("aria-pressed","true"); state.filter = b.dataset.f; render();
}));
$("dl").addEventListener("click", ()=>{
  if (!state.date) return;
  window.location.href = `/api/report/excel?date=${state.date}`;
});

/* ---------- load from the API ---------- */
function fail(title, detail){
  $("page").innerHTML = `<section class="panel"><div class="empty">
    <b>${title}</b>${detail}</div></section>`;
}

(async function init(){
  try{
    const res = await fetch("/api/rows");
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    DATA = await res.json();
  }catch(e){
    return fail("Cannot reach the API",
      `${e.message}<br>Is the server running? Start it with <code>run_api.bat</code>
       and reload this page.`);
  }
  if (!DATA.length) return fail("No reconciliation data",
    "The summarylogs table returned no rows.");

  DATES = [...new Set(DATA.map(r=>r.date))].sort();
  state.date = DATES[DATES.length-1];
  $("dpick").min = DATES[0];
  $("dpick").max = DATES[DATES.length-1];
  render();
})();
