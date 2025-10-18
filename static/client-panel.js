 const API = ""; // ten sam origin

    // ===== helpery UI/API =====
    function api(url){ return `${(window.API ?? "")}${url}`; }
    function showAlert(msg, type="success"){
      const box = document.getElementById("alertBox");
      box.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">
        ${msg}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
    }
    async function assertOkAndJSON(res){
      const ct = res.headers.get("content-type") || "";
      const body = await res.text();
      if(!res.ok) throw new Error(`HTTP ${res.status}: ${body.slice(0,300)}`);
      if(!ct.includes("application/json")) throw new Error(`Nie-JSON (${ct}): ${body.slice(0,300)}`);
      return JSON.parse(body);
    }

    function parsePgTs(iso){ if(!iso||typeof iso!=="string")return null; const d=new Date(iso.replace(" ","T")); return isNaN(d)?null:d; }
    function fmtTime(iso){ const d=parsePgTs(iso); if(!d) return ""; return d.toLocaleTimeString("pl-PL",{hour:"2-digit",minute:"2-digit"}); }
    function initials(name){ if(!name) return ""; return name.split(/\s+/).filter(Boolean).slice(0,3).map(w=>w[0].toUpperCase()).join(""); }
    function colorForId(id){ const h=(Number(id)*47)%360, s=75, l=80, bl=60; return { bg:`hsl(${h} ${s}% ${l}%)`, border:`hsl(${h} ${s}% ${bl}%)`, text:l<60?"#fff":"#000" }; }
    const dowShort = ["Pn","Wt","Śr","Cz","Pt","So","Nd"];

    // ===== stan / stałe =====
    const TP_START_HOUR=7, TP_END_HOUR=20, PX_PER_MIN=24/30;
    let _state = {
      mode: "week",           // week | month
      clientId: "all",
      refDate: new Date(),
      refMonth: new Date(),
      clients: [],
      rows: []                // tylko kind === 'therapy'
    };

    // ===== init =====
    (async function init(){
      const t = new Date();
      document.getElementById("refDate").value = t.toISOString().slice(0,10);
      document.getElementById("refMonth").value= t.toISOString().slice(0,7);
      _state.refDate=t; _state.refMonth=new Date(t.getFullYear(), t.getMonth(), 1);

      // klienci
      try{
        const res = await fetch(api("/api/clients?month="+encodeURIComponent(t.toISOString().slice(0,7))));
        const data = await assertOkAndJSON(res);
        _state.clients = data.map(r => ({ id: r.client_id, full_name: r.full_name })).filter(x => !!x.id);
        const sel = document.getElementById("clSelect");
        sel.innerHTML = `<option value="all">— wszyscy klienci —</option>` +
          _state.clients.map(c => `<option value="${c.id}">${c.full_name}</option>`).join("");
      }catch(e){ showAlert("Błąd ładowania klientów: "+e.message,"danger"); }

      // UI
      document.getElementById("vmWeek").addEventListener("change", ()=>switchMode("week"));
      document.getElementById("vmMonth").addEventListener("change",()=>switchMode("month"));
      document.getElementById("clSelect").addEventListener("change", reload);
      document.getElementById("refDate").addEventListener("change", e => { _state.refDate=new Date(e.target.value); reload(); });
      document.getElementById("refMonth").addEventListener("change", e => {
        const [y,m]=e.target.value.split("-").map(Number); _state.refMonth=new Date(y,m-1,1); reload();
      });
      document.getElementById("btnPrev").addEventListener("click", shiftPrev);
      document.getElementById("btnNext").addEventListener("click", shiftNext);
      document.getElementById("btnToday").addEventListener("click", goToday);
      document.getElementById("btnPrint").addEventListener("click", printView);

      reload();
    })();

    function switchMode(mode){
      _state.mode=mode;
      document.getElementById("refDate").classList.toggle("d-none", mode!=="week");
      document.getElementById("refMonth").classList.toggle("d-none", mode!=="month");
      reload();
    }
    function shiftPrev(){
      if(_state.mode==="week"){
        const d=new Date(_state.refDate); d.setDate(d.getDate()-7);
        _state.refDate=d; document.getElementById("refDate").value=d.toISOString().slice(0,10);
      }else{
        const d=new Date(_state.refMonth.getFullYear(), _state.refMonth.getMonth()-1,1);
        _state.refMonth=d; document.getElementById("refMonth").value=d.toISOString().slice(0,7);
      }
      reload();
    }
    function shiftNext(){
      if(_state.mode==="week"){
        const d=new Date(_state.refDate); d.setDate(d.getDate()+7);
        _state.refDate=d; document.getElementById("refDate").value=d.toISOString().slice(0,10);
      }else{
        const d=new Date(_state.refMonth.getFullYear(), _state.refMonth.getMonth()+1,1);
        _state.refMonth=d; document.getElementById("refMonth").value=d.toISOString().slice(0,7);
      }
      reload();
    }
    function goToday(){
      const t=new Date();
      if(_state.mode==="week"){
        _state.refDate=t; document.getElementById("refDate").value=t.toISOString().slice(0,10);
      }else{
        const m=new Date(t.getFullYear(),t.getMonth(),1);
        _state.refMonth=m; document.getElementById("refMonth").value=m.toISOString().slice(0,7);
      }
      reload();
    }

    // ===== RELOAD: pobranie /packages i przygotowanie therapist_display =====
    async function reload(){
      const host = document.getElementById("calendarHost");
      host.innerHTML = `<div class="text-muted p-3">Ładowanie…</div>`;

      _state.clientId = document.getElementById("clSelect").value || "all"; // <— tu była literówka
      const ref = _state.mode === "week" ? _state.refDate : _state.refMonth;
      const mk  = `${ref.getFullYear()}-${String(ref.getMonth()+1).padStart(2,"0")}`;

      try {
        if (_state.clientId === "all") {
          const promises = _state.clients.map(async (c) => {
            try {
              const res  = await fetch(api(`/api/client/${c.id}/packages?month=${encodeURIComponent(mk)}`));
              const rows = await assertOkAndJSON(res);
              const therapyRows = rows
                .filter(r => r.kind === "therapy")
                .map(r => ({
                  ...r,
                  client_id: c.id,
                  client_name: c.full_name,
                  therapist_display: (r.therapist_name && r.therapist_name.trim())
                    ? r.therapist_name.trim()
                    : (r.therapist_id ? `ID ${r.therapist_id}` : "")
                }));
              return therapyRows;
            } catch (e) {
              console.warn("Client packages fetch failed", c.id, e);
              return [];
            }
          });
          _state.rows = (await Promise.all(promises)).flat();
        } else {
          const cid  = Number(_state.clientId);
          
          // === POCZĄTEK POPRAWKI ===
          // Znajdź pełną nazwę klienta na podstawie jego ID
          const client = _state.clients.find(c => c.id === cid);
          const clientName = client ? client.full_name : `Klient #${cid}`;
          // === KONIEC POPRAWKI ===

          const res  = await fetch(api(`/api/client/${cid}/packages?month=${encodeURIComponent(mk)}`));
          const rows = await assertOkAndJSON(res);
          _state.rows = rows
            .filter(r => r.kind === "therapy")
            .map(r => ({
              ...r,
              client_id: cid,
              client_name: clientName, // <-- DODANA LINIA
              therapist_display: (r.therapist_name && r.therapist_name.trim())
                ? r.therapist_name.trim()
                : (r.therapist_id ? `ID ${r.therapist_id}` : "")
            }));
        }

        renderSchedule();
      } catch (err) {
        host.innerHTML = `<div class="text-danger p-3">Błąd ładowania: ${err.message}</div>`;
      }
    }

    // ===== RENDER (week/month) =====
    function renderSchedule(){
      if (_state.mode === "week") renderWeek();
      else renderMonth();
    }

    function weekRange(date){
      const d = new Date(date);
      const dow = (d.getDay()+6)%7; // pn=0
      const start = new Date(d); start.setDate(d.getDate()-dow); start.setHours(0,0,0,0);
      const days = Array.from({length:7},(_,i)=> new Date(start.getFullYear(), start.getMonth(), start.getDate()+i));
      return { start, days };
    }
    function monthMatrix(firstDay){
      const first=new Date(firstDay.getFullYear(),firstDay.getMonth(),1);
      const offset=(first.getDay()+6)%7; // pn=0
      const start=new Date(first); start.setDate(first.getDate()-offset); start.setHours(0,0,0,0);
      return Array.from({length:42},(_,i)=> new Date(start.getFullYear(), start.getMonth(), start.getDate()+i));
    }

    // Zastąp całą tę funkcję w swoim pliku
function renderWeek() {
    const host = document.getElementById("calendarHost");
    const { days } = weekRange(_state.refDate);

    const head = `<div class="cal-head cal-grid">
      <div style="padding:.5rem">Godz.</div>
      ${days.map((d,i)=>`<div>${dowShort[i]}<br><small>${d.toLocaleDateString("pl-PL")}</small></div>`).join("")}
    </div>`;

    let times = `<div>`;
    for (let h = TP_START_HOUR; h <= TP_END_HOUR; h++) {
        times += `<div class="cal-row"><label>${String(h).padStart(2, "0")}:00</label></div>`;
        if (h !== TP_END_HOUR) times += `<div class="cal-row"></div>`;
    }
    times += `</div>`;
    const colHeight = ((TP_END_HOUR - TP_START_HOUR + 1) * 2) * 24;
    const cols = days.map(d => `<div class="cal-col" data-day="${fmtYYYYMMDD(d)}" style="height:${colHeight}px"></div>`).join("");

    host.innerHTML = `<div class="cal-wrap">
      ${head}<div class="cal-grid">${times}${cols}</div>
      <div class="cal-legend">
        <span><span class="swatch" style="background:rgba(13,110,253,.3);border:1px solid rgba(13,110,253,.5)"></span> planned</span>
        <span><span class="swatch" style="background:rgba(25,135,84,.3);border:1px solid rgba(25,135,84,.5)"></span> done</span>
        <span><span class="swatch" style="background:rgba(220,53,69,.25);border:1px solid rgba(220,53,69,.5)"></span> cancelled</span>
        ${_state.clientId === "all" ? `<span class="ms-2">Kolor = klient</span>` : ``}
      </div>
    </div>`;

    // --- POPRAWKA 1: Używamy atrybutu "data-day" ---
    const dayMap = new Map([...host.querySelectorAll(".cal-col")].map(el => [el.getAttribute("data-day"), el]));

    for (const r of _state.rows) {
        const s = parsePgTs(r.starts_at), e = parsePgTs(r.ends_at);
        if (!s || !e) continue;

        // --- POPRAWKA 2: Używamy funkcji fmtYYYYMMDD, aby uniknąć błędu strefy czasowej ---
        const key = fmtYYYYMMDD(s);
        const col = dayMap.get(key);

        // --- POPRAWKA 3: Usunięto zduplikowany i niepotrzebny kod ---
        if (!col) continue;

        const top = ((s.getHours() - TP_START_HOUR) * 60 + s.getMinutes()) * PX_PER_MIN;
        const height = Math.max(18, Math.max(0, (e - s) / 60000) * PX_PER_MIN);

        const el = document.createElement("div");
        el.className = `cal-event ${r.status || "planned"}`;
        el.style.top = `${top}px`;
        el.style.height = `${height}px`;

        if (_state.clientId === "all") {
            const c = colorForId(r.client_id || 0);
            el.style.background = c.bg;
            el.style.borderColor = c.border;
            el.style.color = c.text;
        }

        const whoLine = (_state.clientId === "all")
            ? (r.client_name || (`klient #${r.client_id ?? ""}`))
            : (r.therapist_display || "");

        el.innerHTML = `
          <div><strong>${fmtTime(r.starts_at)}–${fmtTime(r.ends_at)}</strong></div>
          <div class="text-truncate">${whoLine}</div>
          ${r.place_to ? `<div class="text-truncate"><small>${r.place_to}</small></div>` : ``}
        `;
        col.appendChild(el);
    }
}

    // --- MIESIĄC ---
    function renderMonth(){
      const host = document.getElementById("calendarHost");
      const days = monthMatrix(_state.refMonth);
      const thisMonth = _state.refMonth.getMonth();

      const head = `<div class="month-head">
        ${dowShort.map(d=>`<div>${d}</div>`).join("")}
      </div>`;

      // indeks po dacie
      const map = new Map();
      for (const r of _state.rows){
        const s = parsePgTs(r.starts_at);
        if (!s) continue;
        const k = `${s.getFullYear()}-${String(s.getMonth() + 1).padStart(2, '0')}-${String(s.getDate()).padStart(2, '0')}`;
        if (!map.has(k)) map.set(k, []);
        map.get(k).push(r);
      }

      const grid = days.map(d => {
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        const items = map.get(key) || [];
        const muted = d.getMonth() !== thisMonth ? "opacity:.55" : "";

        const chips = items.slice(0,8).map(r => {
          const base = `display:inline-block;margin:.15rem .15rem 0 0;padding:.1rem .35rem;border-radius:999px;font-size:11px;border:1px solid transparent;`;
          const cls  = r.status === "done" ? "border-color:rgba(25,135,84,.35);background:rgba(25,135,84,.15)"
                    : r.status === "cancelled" ? "border-color:rgba(220,53,69,.35);background:rgba(220,53,69,.12);text-decoration:line-through"
                    : "border-color:rgba(13,110,253,.35);background:rgba(13,110,253,.12)";
          if (_state.clientId === "all") {
            const c = colorForId(r.client_id || 0);
            return `<span class="day-chip" style="${base};background:${c.bg};border-color:${c.border};color:${c.text}">
              <span class="mini" style="opacity:.7">${fmtTime(r.starts_at)}–${fmtTime(r.ends_at)}</span> • ${initials(r.client_name||"")}
            </span>`;
          } else {
            return `<span class="day-chip" style="${base};${cls}">
              <span class="mini" style="opacity:.7">${fmtTime(r.starts_at)}–${fmtTime(r.ends_at)}</span> • ${r.therapist_display || ""}
            </span>`;
          }
        }).join("");

        const more = items.length>8 ? `<div><small class="text-muted">+${items.length-8} więcej…</small></div>` : "";

        return `<div class="day-cell cal-day" data-date="${key}" style="${muted}">
          <div class="day-num">${d.getDate()}</div>
          ${chips}${more}
        </div>`;
      }).join("");

      const title = `${_state.refMonth.toLocaleDateString("pl-PL", {month:"long", year:"numeric"})}`;

      host.innerHTML = `
        <div class="sticky-month-title"><h5 class="m-0">${title}</h5></div>
        <div class="month-wrap">
          ${head}
          <div class="month-grid">${grid}</div>
        </div>`;
    }

    // ===== DRUK (poziomo, wspólny dla obu trybów) =====
    function assignMissingDatesForPrint(host){
      const cells = host.querySelectorAll(".cal-day[data-date], .day-cell[data-date]");
      if(cells.length) return true;

      const mondayOf=d=>{const r=new Date(d), w=(r.getDay()+6)%7; r.setDate(r.getDate()-w); return r;};
      let start;
      if(_state.mode==="week") start = mondayOf(_state.refDate);
      else { const first=new Date(_state.refMonth.getFullYear(), _state.refMonth.getMonth(), 1); start=mondayOf(first); }

      const list = host.querySelectorAll(_state.mode==="week" ? ".cal-col,.cal-day" : ".day-cell");
      if(!list.length) return false;

      let d=new Date(start);
      list.forEach((el,idx)=>{ if(idx>0) d.setDate(d.getDate()+1); el.setAttribute("data-date", d.toISOString().slice(0,10)); });
      return true;
    }

    function printView(){
      const host=document.getElementById("calendarHost");
      if(!host){ showAlert("Brak kontenera grafiku do wydruku.","warning"); return; }
      assignMissingDatesForPrint(host);

      const dayNodes = host.querySelectorAll(".cal-day[data-date], .day-cell[data-date]");
      if(!dayNodes.length){ showAlert("Brak rozpoznanych komórek dni do wydruku (sprawdź .cal-day/.day-cell albo data-date).","warning"); return; }

      const eventsByDate=new Map();
      dayNodes.forEach(node=>{
        const iso=node.getAttribute("data-date");
        const evs=[...node.querySelectorAll(".cal-event, .day-chip")].map(e=>e.textContent.trim()).filter(Boolean);
        eventsByDate.set(iso, evs);
      });

      const fmtISO=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
      const mondayOf=d=>{const r=new Date(d), w=(r.getDay()+6)%7; r.setDate(r.getDate()-w); return r;};
      let startDate,endDate;
      if(_state.mode==="month"){
        const firstOfMonth=new Date(_state.refMonth.getFullYear(), _state.refMonth.getMonth(), 1);
        const lastOfMonth=new Date(_state.refMonth.getFullYear(), _state.refMonth.getMonth()+1, 0);
        startDate=mondayOf(firstOfMonth);
        const tmp=new Date(lastOfMonth); const dow=(tmp.getDay()+6)%7; tmp.setDate(tmp.getDate()+(6-dow));
        endDate=tmp;
      }else{
        startDate=mondayOf(_state.refDate); endDate=new Date(startDate); endDate.setDate(startDate.getDate()+6);
      }

      const rows=[]; let cursor=new Date(startDate);
      while(cursor<=endDate){
        const tds=[];
        for(let k=0;k<7;k++){
          const iso=fmtISO(cursor);
          const evs=eventsByDate.get(iso)||[];
          const evHtml=evs.map(txt=>{
            const safe=String(txt).replace(/[<>&]/g, s=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[s]));
            return `<div class="event">${safe}</div>`;
          }).join("");
          tds.push(`<td data-date="${iso}"><div class="day-head"><span class="day-number">${cursor.getDate()}</span></div><div class="events">${evHtml}</div></td>`);
          cursor.setDate(cursor.getDate()+1);
        }
        rows.push(`<tr>${tds.join("")}</tr>`);
      }

      const sel=document.getElementById("clSelect");
      const isAll = sel && sel.value==="all";
      const clientName = isAll ? "Wszyscy klienci" : (sel?.options?.[sel.selectedIndex]?.textContent || "");

      const html = `<!doctype html><html lang="pl"><head>
        <meta charset="utf-8"><title>Grafik klientów – ${_state.mode==="week"?"tydzień":"miesiąc"}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          @page{size:A4 landscape;margin:10mm}
          *{box-sizing:border-box}
          html,body{height:100%}
          body{font:11px/1.35 Arial,Helvetica,sans-serif;color:#111;margin:0}
          .doc-header{display:flex;justify-content:space-between;align-items:flex-start;margin:0 0 10px 0;padding:0 2mm}
          .doc-header h1{font-size:18px;margin:0 0 2px 0}
          .muted{color:#666;font-size:10px}
          table.calendar{width:100%;border-collapse:collapse;table-layout:fixed}
          .calendar th,.calendar td{border:1px solid #333;vertical-align:top;padding:3px 4px}
          .calendar thead th{background:#f1f3f4;text-align:center;font-weight:700;font-size:11px;white-space:nowrap}
          .calendar td{height:30mm;overflow:hidden}
          .day-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:2px}
          .day-number{font-weight:700;font-size:12px}
          .events{font-size:10px}
          .event{margin:2px 0;padding:2px 3px;border:1px solid #777;border-radius:3px;page-break-inside:avoid;word-wrap:break-word}
          .calendar tbody tr:nth-child(even) td{background:#fcfcfc}
        </style>
      </head><body>
        <div class="doc-header">
          <div>
            <h1>Grafik klientów – ${_state.mode==="week"?"tydzień":"miesiąc"}</h1>
            <div>${isAll ? "" : "<strong>Klient:</strong> "}${(clientName||"").replace(/</g,"&lt;")}</div>
          </div>
          <div class="muted">Wygenerowano: ${new Date().toLocaleString("pl-PL")}</div>
        </div>
        <table class="calendar">
          <thead><tr><th>Pon</th><th>Wt</th><th>Śr</th><th>Czw</th><th>Pt</th><th>Sob</th><th>Nd</th></tr></thead>
          <tbody>${rows.join("\n")}</tbody>
        </table>
      </body></html>`;

      const iframe=document.createElement("iframe");
      Object.assign(iframe.style,{position:"fixed",right:"0",bottom:"0",width:"0",height:"0",border:"0"});
      iframe.setAttribute("aria-hidden","true");
      document.body.appendChild(iframe);
      const ifrw=iframe.contentWindow; const ifrd=iframe.contentDocument||ifrw.document;
      ifrd.open(); ifrd.write(html); ifrd.close();

      let printed=false; const cleanup=()=>setTimeout(()=>iframe.remove(),100);
      iframe.onload=()=>{ if(printed) return; printed=true; try{ ifrw.focus(); setTimeout(()=>{ try{ ifrw.print(); }catch(_){ } },0); }catch(_){ } };
      if(ifrw) ifrw.onafterprint=cleanup; setTimeout(cleanup,5000);
    }
      function fmtYYYYMMDD(date) {
    if (!date || isNaN(date)) return "";
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0'); // Miesiące są 0-indeksowane
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}
      document.addEventListener('DOMContentLoaded', () => {
        const fabContainer = document.getElementById('fab-container');
        const fabMainBtn = document.getElementById('fab-main-btn');

        fabMainBtn.addEventListener('click', () => {
            fabContainer.classList.toggle('open');
        });

    });
