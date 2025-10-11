function formatMinutesAsHours(mins) {
  if (mins === null || typeof mins === 'undefined' || isNaN(mins)) {
    return "—";
  }
  const hours = Math.floor(mins / 60);
  const remainingMinutes = mins % 60;

  if (hours > 0 && remainingMinutes > 0) {
    return `${hours} h ${remainingMinutes} m`;
  }
  if (hours > 0) {
    return `${hours} h`;
  }
  return `${remainingMinutes} m`;
}

const API = "";

let _clientEditId = null;
let lastClients = [];

const packageTypeModalEl = document.getElementById('packageTypeModal');
const packageTypeModal = new bootstrap.Modal(packageTypeModalEl);
let _clientIdForNewPackage = null;

let currentlyDisplayedClientIds = [];

function filterTherapistsTable(selectedTherapistId) {
  const therapistsTbody = document.getElementById("therapistsTbody");
  const therapistRows = therapistsTbody.querySelectorAll("tr");

  if (selectedTherapistId === "all" || !selectedTherapistId) {
    therapistRows.forEach(row => row.style.display = "");
    return;
  }

  therapistRows.forEach(row => {
    const rowId = row.querySelector("td")?.textContent;
    row.style.display = (rowId === selectedTherapistId) ? "" : "none";
  });
}

async function filterDriversTable(clientIds) {
  const driversTbody = document.getElementById("driversTbody");
  const driverRows = driversTbody.querySelectorAll("tr");
  const selectedTherapistId = document.getElementById("therapistFilter").value;

  if (selectedTherapistId === "all") {
    driverRows.forEach(row => row.style.display = "");
    return;
  }

  if (!clientIds || clientIds.length === 0) {
    driverRows.forEach(row => row.style.display = "none");
    return;
  }

  try {
    const fetchPromises = clientIds.map(cid =>
      fetch(`${API}/api/client/${cid}/packages`).then(res => res.ok ? res.json() : [])
    );

    const packagesPerClient = await Promise.all(fetchPromises);
    const allPackages = packagesPerClient.flat();

    const relevantDriverIds = new Set(
      allPackages.filter(pkg => pkg.driver_id).map(pkg => String(pkg.driver_id))
    );

    driverRows.forEach(row => {
      const rowId = row.querySelector("td")?.textContent;
      row.style.display = (rowId && relevantDriverIds.has(rowId)) ? "" : "none";
    });
  } catch (err) {
    console.error("Błąd podczas filtrowania kierowców:", err);
    driverRows.forEach(row => row.style.display = "");
  }
}

const monthInput = document.getElementById("monthInput");
const reloadBtn = document.getElementById("reloadBtn");
const reloadSpinner = document.getElementById("reloadSpinner");
const reloadTxt = document.getElementById("reloadTxt");
const tbody = document.getElementById("clientsTbody");
const alertBox = document.getElementById("alertBox");

const thSelect = document.getElementById("thSelect");
const pkDriverSelect = document.getElementById("pkDriverSelect");
const dpDriverSelect = document.getElementById("dpDriverSelect");

const packageCanvas = new bootstrap.Offcanvas('#packageCanvas');
const allocCanvas = new bootstrap.Offcanvas('#allocCanvas');

const pkgClientId = document.getElementById("pkgClientId");
const pkgLabel = document.getElementById("pkgLabel");
const thId = document.getElementById("thSelect");
const thDate = document.getElementById("thDate");
const thStart = document.getElementById("thStart");
const thEnd = document.getElementById("thEnd");
const thPlace = document.getElementById("thPlace");
const withPickup = document.getElementById("withPickup");
const withDropoff = document.getElementById("withDropoff");
const pickupFields = document.getElementById("pickupFields");
const dropoffFields = document.getElementById("dropoffFields");
const pkDriverId = document.getElementById("pkDriverSelect");
const pkVehicleId = document.getElementById("pkVehicleId");
const pkStart = document.getElementById("pkStart");
const pkEnd = document.getElementById("pkEnd");
const pkFrom = document.getElementById("pkFrom");
const pkTo = document.getElementById("pkTo");
const dpDriverId = document.getElementById("dpDriverSelect");
const dpVehicleId = document.getElementById("dpVehicleId");
const dpStart = document.getElementById("dpStart");
const dpEnd = document.getElementById("dpEnd");
const dpFrom = document.getElementById("dpFrom");
const dpTo = document.getElementById("dpTo");
const pkgSaveBtn = document.getElementById("pkgSaveBtn");
const pkgSpinner = document.getElementById("pkgSpinner");

const allocClientId = document.getElementById("allocClientId");
const allocClientName = document.getElementById("allocClientName");
const allocMonth = document.getElementById("allocMonth");
const allocMinutes = document.getElementById("allocMinutes");
const allocSaveBtn = document.getElementById("allocSaveBtn");
const allocSpinner = document.getElementById("allocSpinner");

function showAlert(msg, type="success") {
  alertBox.innerHTML = `
    <div class="alert alert-${type} alert-dismissible fade show" role="alert">
      ${msg}
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>`;
}

function parseLocalTimestamp(str){
  if (!str) return null;
  const s = str.trim().replace('T', ' ');
  const m = /^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/.exec(s);
  if (!m) return null;
  const [_, Y, M, D, h, mnt, sec] = m;
  return new Date(
    Number(Y),
    Number(M) - 1,
    Number(D),
    Number(h),
    Number(mnt),
    Number(sec)
  );
}

function fmtLocalDateTime(str){
  const d = parseLocalTimestamp(str);
  if (!d) return "—";
  return d.toLocaleString("pl-PL", { year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit" });
}

function fmtLocalTime(str){
  const d = parseLocalTimestamp(str);
  if (!d) return "";
  return d.toLocaleTimeString("pl-PL", { hour:"2-digit", minute:"2-digit" });
}

function minutesBetweenLocal(a, b){
  const A = parseLocalTimestamp(a), B = parseLocalTimestamp(b);
  if (!A || !B) return 0;
  return Math.max(0, Math.round((B - A) / 60000));
}

function dateKeyPLLocal(str){
  const d = parseLocalTimestamp(str);
  if (!d) return { key:"", label:"" };
  const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const label = d.toLocaleDateString("pl-PL", { weekday:"long", day:"2-digit", month:"2-digit", year:"numeric" });
  return { key, label };
}

function pad2(n){ return String(n).padStart(2,'0'); }
function isoLocal(dateStr, timeStr){ return `${dateStr}T${timeStr}:00`; }
function setBtnBusy(btn, spinnerEl, busy){
  if(busy){ spinnerEl.classList.remove('d-none'); btn.setAttribute('disabled','disabled'); }
  else { spinnerEl.classList.add('d-none'); btn.removeAttribute('disabled'); }
}

let clientsNameCache = new Map();

const clientFilter = document.getElementById("clientFilter");
const therapistFilter = document.getElementById("therapistFilter");

async function fillTherapistFilter() {
  try {
    const res = await fetch(`${API}/api/therapists`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const active = data.filter(t => t.active !== false);
    therapistFilter.innerHTML = `<option value="">— wszyscy terapeuci —</option>` +
      active.map(t => `<option value="${t.id}">${t.full_name}${t.specialization ? " – " + t.specialization : ""}</option>`).join("");
  } catch (err) {
    showAlert(`Nie udało się pobrać listy terapeutów do filtra: ${err.message}`, "danger");
  }
}

async function refreshAllViews() {
  await loadClients();

  const selectedTherapistId = therapistFilter.value;
  filterTherapistsTable(selectedTherapistId);
  await filterDriversTable(currentlyDisplayedClientIds);
}

clientFilter.addEventListener("input", refreshAllViews);
therapistFilter.addEventListener("change", refreshAllViews);
monthInput.addEventListener("change", () => {
  refreshAllViews();
  checkMonthlyGaps();
});

fillTherapistFilter();

async function loadClients() {
  setBtnBusy(reloadBtn, reloadSpinner, true);
  tbody.innerHTML = `
    <tr><td colspan="9" class="text-center py-4">
      <div class="d-inline-flex align-items-center gap-2 text-muted">
        <div class="spinner-border spinner-border-sm"></div>
        <span>Ładowanie…</span>
      </div>
    </td></tr>`;

  const mk = monthInput.value;
  const q  = (clientFilter.value || "").trim();
  const tid = therapistFilter.value || "";

  const params = new URLSearchParams();
  if (mk)  params.set("month", mk);
  if (q)   params.set("q", q);
  if (tid) params.set("therapist_id", tid);

  try {
    const res = await fetch(`${API}/api/clients?` + params.toString());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    lastClients = data;
    currentlyDisplayedClientIds = data.map(c => c.client_id);

    clientsNameCache.clear();
    data.forEach(r => clientsNameCache.set(r.client_id, r.full_name));

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted py-4">Brak klientów</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(row => {
      const quota = formatMinutesAsHours(row.minutes_quota);
      const used  = formatMinutesAsHours(row.minutes_used);
      const left  = formatMinutesAsHours(row.minutes_left);
      const statusBadge = row.needs_allocation
        ? `<span class="badge text-bg-warning">Brak przydziału</span>`
        : `<span class="badge text-bg-success">OK</span>`;
      return `
        <tr>
          <td>${row.full_name}</td>
          <td class="d-none d-md-table-cell">${row.phone ?? ""}</td>
          <td class="d-none d-lg-table-cell">${row.address ?? ""}</td>
          <td><code>${row.month_key}</code></td>
          <td>${quota}</td>
          <td>${used}</td>
          <td>${left}</td>
          <td>${statusBadge}</td>
          <td class="text-end">
            <div class="actions d-grid d-sm-inline-flex gap-1">
              <button class="btn btn-sm btn-success" onclick="aiSuggestForClient(${row.client_id})">🤖 Zaproponuj</button>
              <button class="btn btn-sm btn-primary" onclick="choosePackageType(${row.client_id})">Dodaj pakiet</button>
              <button class="btn btn-sm btn-outline-secondary" onclick="openAllocationCanvas(${row.client_id}, '${row.month_key}', ${row.minutes_quota ?? 'null'})">Ustaw przydział</button>
              <button class="btn btn-sm btn-outline-primary" onclick="openClientPackages(${row.client_id}, '${row.full_name.replace(/'/g, "\\'")}')">Pakiety</button>
            </div>
          </td>
        </tr>`;
    }).join("");

  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-danger py-4">Błąd ładowania: ${e.message}</td></tr>`;
  } finally {
    setBtnBusy(reloadBtn, reloadSpinner, false);
  }
}

document.getElementById("reloadBtn").addEventListener("click", loadClients);

async function suggestForClient(clientId, dateStr){
  try{
    const res = await fetch(`${API}/api/ai/recommend?client_id=${clientId}&date=${encodeURIComponent(dateStr||"")}`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const j = await res.json();

    const topT = (j.therapists||[])[0];
    if (topT){
      [...thSelect.options].forEach(o=>{
        if (Number(o.value)===Number(topT.therapist_id)) o.textContent = `⭐ ${o.textContent}`;
      });
      thSelect.value = String(topT.therapist_id);
    }

    const topD = (j.drivers||[])[0];
    if (topD){
      [...pkDriverSelect.options].forEach(o=>{
        if (Number(o.value)===Number(topD.driver_id)) o.textContent = `⭐ ${o.textContent}`;
      });
      [...dpDriverSelect.options].forEach(o=>{
        if (Number(o.value)===Number(topD.driver_id)) o.textContent = `⭐ ${o.textContent}`;
      });
      pkDriverSelect.value = String(topD.driver_id);
      dpDriverSelect.value = String(topD.driver_id);
    }

    const tp = (j.time_prefs||[])[0];
    if (tp){
      thStart.value = String(tp.hour).padStart(2,"0")+":00";
      const endH = (tp.hour+1);
      thEnd.value   = String(endH).padStart(2,"0")+":00";
    }
  }catch(err){
    console.warn("AI suggest error:", err);
  }
}

function openPackageCanvas(clientId) {
  const client = lastClients.find(c => c.client_id === clientId);

  if (client && !client.has_unavailability_plan) {
    const confirmation = confirm(
      `Przed dodaniem pakietu, musisz najpierw zdefiniować plan lekcji tego klienta (np. godziny szkolne), aby uniknąć konfliktów.\n\nCzy chcesz teraz przejść do strony zarządzania dostępnością?`
    );

    if (confirmation) {
      window.location.href = `dostepnosc.html?client_id=${clientId}`;
    }

    return;
  }

  _editingGroupId = null;
  pkgClientId.value = clientId;
  pkgLabel.value = "";
  thPlace.value = "Poradnia";

  const d = new Date();
  d.setDate(d.getDate() + 1);
  const dStr = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  thDate.value = dStr;
  thStart.value = "09:00";
  thEnd.value = "10:00";

  loadTherapistsAndDrivers().catch(err => {
    showAlert(`Nie udało się pobrać listy terapeutów/kierowców: ${err.message}`, "danger");
  });

  thSelect.value = "";
  pkDriverSelect.value = "";
  dpDriverSelect.value = "";

  withPickup.checked = false; pickupFields.classList.add("d-none");
  pkFrom.value = "Dom"; pkTo.value = "Poradnia";
  pkStart.value = "08:30"; pkEnd.value = "09:00";

  withDropoff.checked = false; dropoffFields.classList.add("d-none");
  dpFrom.value = "Poradnia"; dpTo.value = "Dom";
  dpStart.value = "10:05"; dpEnd.value = "10:35";

  document.getElementById("pkgStatus").value = "planned";
  packageCanvas.show();
}

window.openPackageCanvas = openPackageCanvas;

document.getElementById("withPickup").addEventListener("change", () => {
  pickupFields.classList.toggle("d-none", !withPickup.checked);
});
document.getElementById("withDropoff").addEventListener("change", () => {
  dropoffFields.classList.toggle("d-none", !withDropoff.checked);
});

document.getElementById("packageForm").addEventListener("submit", async (e) => {
  e.preventDefault();

  const client_id = Number(pkgClientId.value);
  const therapist_id = Number(thSelect.value || 0);
  if (!client_id || !therapist_id){
    showAlert("Uzupełnij klienta i terapeutę.", "warning");
    return;
  }

  const payload = {
    group_id: _editingGroupId || null,
    client_id,
    label: pkgLabel.value || null,
    therapy: {
      therapist_id,
      starts_at: isoLocal(thDate.value, thStart.value),
      ends_at: isoLocal(thDate.value, thEnd.value),
      place: thPlace.value || null
    },
    status: document.getElementById("pkgStatus").value
  };

  if (withPickup.checked){
    const id = Number(pkDriverSelect.value || 0);
    if (!id) { showAlert("Wybierz kierowcę (pickup) lub wyłącz pickup.", "warning"); return; }
    payload.pickup = {
      driver_id: id,
      vehicle_id: pkVehicleId.value ? Number(pkVehicleId.value) : null,
      starts_at: isoLocal(thDate.value, pkStart.value),
      ends_at: isoLocal(thDate.value, pkEnd.value),
      from: pkFrom.value || null,
      to: pkTo.value || null
    };
  } else {
    payload.pickup = null;
  }

  if (withDropoff.checked){
    const id = Number(dpDriverSelect.value || 0);
    if (!id) { showAlert("Wybierz kierowcę (dropoff) lub wyłącz dropoff.", "warning"); return; }
    payload.dropoff = {
      driver_id: id,
      vehicle_id: dpVehicleId.value ? Number(dpVehicleId.value) : null,
      starts_at: isoLocal(thDate.value, dpStart.value),
      ends_at: isoLocal(thDate.value, dpEnd.value),
      from: dpFrom.value || null,
      to: dpTo.value || null
    };
  } else {
    payload.dropoff = null;
  }

  try {
    const conflicts = await checkPackageConflicts(payload);

    if (conflicts.total > 0) {
      const conflictMessage = formatConflictsMessage(conflicts);

      const confirmDiv = document.createElement('div');
      confirmDiv.innerHTML = conflictMessage + `
        <div class="d-flex gap-2 mt-3">
          <button class="btn btn-danger" id="confirmSaveWithConflicts">Tak, zapisz mimo kolizji</button>
          <button class="btn btn-secondary" id="cancelSaveConflicts">Anuluj</button>
        </div>
      `;

      const oldAlerts = alertBox.querySelectorAll('.alert');
      oldAlerts.forEach(a => a.remove());

      alertBox.appendChild(confirmDiv);
      alertBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

      return new Promise((resolve) => {
        document.getElementById('confirmSaveWithConflicts').onclick = async () => {
          confirmDiv.remove();
          await savePackage(payload);
          resolve();
        };

        document.getElementById('cancelSaveConflicts').onclick = () => {
          confirmDiv.remove();
          resolve();
        };
      });
    } else {
      await savePackage(payload);
    }

  } catch (err) {
    showAlert(`Błąd sprawdzania kolizji: ${err.message}`, "danger");
  }
});

async function savePackage(payload) {
  try {
    setBtnBusy(pkgSaveBtn, pkgSpinner, true);

    let url, method;
    if (_editingGroupId) {
      url = `${API}/api/groups/${_editingGroupId}`;
      method = "PUT";
    } else {
      url = `${API}/api/schedule/group`;
      method = "POST";
    }

    const res = await fetch(url, {
      method,
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });

    await assertOk(res);
    await res.json();

    packageCanvas.hide();
    showAlert(_editingGroupId ? "Zaktualizowano pakiet." : "Dodano pakiet.", "success");
    _editingGroupId = null;

    loadClients();
    refreshClientPackagesModal();

  } catch(err) {
    showAlert(`Błąd zapisu pakietu: ${err.message}`, "danger");
  } finally {
    setBtnBusy(pkgSaveBtn, pkgSpinner, false);
  }
}

function choosePackageType(clientId) {
  _clientIdForNewPackage = clientId;
  packageTypeModal.show();
}

async function openPackageEdit(groupId) {
  console.log('openPackageEdit wywołane z groupId:', groupId);

  const modalEl = document.getElementById('clientPackagesModal');
  const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);

  const waitHidden = new Promise(resolve => {
    const onHidden = () => {
      modalEl.removeEventListener('hidden.bs.modal', onHidden);
      resolve();
    };
    modalEl.addEventListener('hidden.bs.modal', onHidden, { once: true });
  });
  modal.hide();
  await waitHidden;

  try {
    await loadTherapistsAndDrivers();

    const res = await fetch(`${API}/api/groups/${groupId}`);

    console.log('Status odpowiedzi:', res.status);

    if (!res.ok) {
      let errorMessage = `HTTP ${res.status}`;
      try {
        const errorData = await res.json();
        console.error('Błąd z serwera:', errorData);
        errorMessage = errorData.error || errorMessage;
      } catch (e) {
        const errorText = await res.text();
        console.error('Tekst błędu:', errorText);
        errorMessage = errorText || errorMessage;
      }
      throw new Error(errorMessage);
    }

    const g = await res.json();
    console.log('Otrzymane dane pakietu:', g);

    _editingGroupId = g.group_id;

    pkgClientId.value = g.client_id;
    pkgLabel.value = g.label || "";
    document.getElementById("pkgStatus").value = g.status || "planned";

    if (g.therapy) {
      thSelect.value = g.therapy.therapist_id || "";
      thPlace.value = g.therapy.place || "Poradnia";

      if (g.therapy.starts_at) {
        const [tDate, tTime] = g.therapy.starts_at.split('T');
        thDate.value = tDate || "";
        thStart.value = tTime ? tTime.slice(0, 5) : "";
      }
      if (g.therapy.ends_at) {
        const [, eTime] = g.therapy.ends_at.split('T');
        thEnd.value = eTime ? eTime.slice(0, 5) : "";
      }
    }

    if (g.pickup) {
      withPickup.checked = true;
      pickupFields.classList.remove("d-none");
      pkDriverSelect.value = g.pickup.driver_id || "";
      pkVehicleId.value = g.pickup.vehicle_id ?? "";
      pkFrom.value = g.pickup.from || "Dom";
      pkTo.value = g.pickup.to || "Poradnia";

      if (g.pickup.starts_at) {
        pkStart.value = g.pickup.starts_at.split('T')[1]?.slice(0, 5) || "";
      }
      if (g.pickup.ends_at) {
        pkEnd.value = g.pickup.ends_at.split('T')[1]?.slice(0, 5) || "";
      }
    } else {
      withPickup.checked = false;
      pickupFields.classList.add("d-none");
    }

    if (g.dropoff) {
      withDropoff.checked = true;
      dropoffFields.classList.remove("d-none");
      dpDriverSelect.value = g.dropoff.driver_id || "";
      dpVehicleId.value = g.dropoff.vehicle_id ?? "";
      dpFrom.value = g.dropoff.from || "Poradnia";
      dpTo.value = g.dropoff.to || "Dom";

      if (g.dropoff.starts_at) {
        dpStart.value = g.dropoff.starts_at.split('T')[1]?.slice(0, 5) || "";
      }
      if (g.dropoff.ends_at) {
        dpEnd.value = g.dropoff.ends_at.split('T')[1]?.slice(0, 5) || "";
      }
    } else {
      withDropoff.checked = false;
      dropoffFields.classList.add("d-none");
    }

    packageCanvas.show();
    setTimeout(() => { try { thSelect.focus(); } catch(e) {} }, 200);

  } catch (err) {
    console.error('Pełny błąd w openPackageEdit:', err);
    showAlert(`Nie udało się otworzyć edycji pakietu: ${err.message}`, "danger");
  }
}

window.openPackageEdit = openPackageEdit;

async function confirmDeletePackage(groupId) {
  if (!confirm("Czy na pewno chcesz trwale usunąć cały pakiet (terapię i powiązane kursy)? Tej operacji nie można cofnąć.")) {
    return;
  }

  try {
    const res = await fetch(`${API}/api/groups/${groupId}`, {
      method: "DELETE"
    });

    await assertOk(res);

    showAlert("Pakiet został pomyślnie usunięty.", "success");

    refreshClientPackagesModal();
    loadClients();

  } catch (err) {
    showAlert(`Błąd podczas usuwania pakietu: ${err.message}`, "danger");
  }
}
window.confirmDeletePackage = confirmDeletePackage;

function openAllocationCanvas(clientId, monthKey, currentQuota) {
  allocClientId.value = clientId;
  allocClientName.value = clientsNameCache.get(clientId) || `ID ${clientId}`;
  allocMonth.value = monthKey || monthInput.value;
  allocMinutes.value = (currentQuota ?? 1200) / 60;
  allocCanvas.show();
}
window.openAllocationCanvas = openAllocationCanvas;

document.getElementById("allocForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const cid = Number(allocClientId.value);
  const mk = allocMonth.value;
  const q = Number(allocMinutes.value) * 60;

  if (!cid || !mk || isNaN(q) || q < 0) {
    showAlert("Uzupełnij poprawnie pola przydziału.", "warning");
    return;
  }

  try {
    setBtnBusy(allocSaveBtn, allocSpinner, true);
    const res = await fetch(`${API}/api/suo/allocation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: cid, month_key: mk, minutes_quota: q })
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`HTTP ${res.status}: ${t}`);
    }
    await res.json();
    allocCanvas.hide();
    showAlert(`Ustawiono przydział ${q} min dla klienta #${cid} w ${mk}.`);
    loadClients();
  } catch (err) {
    showAlert(`Błąd zapisu przydziału: ${err.message}`, "danger");
  } finally {
    setBtnBusy(allocSaveBtn, allocSpinner, false);
  }
});

(function initMonth(){
  const today = new Date();
  const y = today.getFullYear();
  const m = String(today.getMonth()+1).padStart(2,'0');
  monthInput.value = `${y}-${m}`;
})();
refreshAllViews();

const clientCanvasEl     = document.getElementById('clientCanvas');
const therapistCanvasEl  = document.getElementById('therapistCanvas');
const driverCanvasEl     = document.getElementById('driverCanvas');

const clientOC    = bootstrap.Offcanvas.getOrCreateInstance(clientCanvasEl);
const therapistOC = bootstrap.Offcanvas.getOrCreateInstance(therapistCanvasEl);
const driverOC    = bootstrap.Offcanvas.getOrCreateInstance(driverCanvasEl);

document.getElementById("addClientBtn").addEventListener("click", (e)=>{
  e.preventDefault();
  resetClientForm();
  _clientEditId = null;
  clientOC.show();
});
clientOC.hide();

document.getElementById("addTherapistBtn").addEventListener("click", (e)=>{
  e.preventDefault();
  resetTherapistForm();
  _therapistEditId = null;
  therapistOC.show();
});

document.getElementById("addDriverBtn").addEventListener("click", (e)=>{
  e.preventDefault();
  resetDriverForm();
  driverOC.show();
});

const clName = document.getElementById("clName");
const clPhone = document.getElementById("clPhone");
const clAddress = document.getElementById("clAddress");
const clActive = document.getElementById("clActive");
const clSaveBtn = document.getElementById("clSaveBtn");
const clSpinner = document.getElementById("clSpinner");

function resetClientForm(){ clName.value=""; clPhone.value=""; clAddress.value=""; clActive.checked=true; }

const thName = document.getElementById("thName");
const thSpec = document.getElementById("thSpec");
const thPhone2 = document.getElementById("thPhone");
const thActiveChk = document.getElementById("thActive");
const thSaveBtn2 = document.getElementById("thSaveBtn");
const thSpinner2 = document.getElementById("thSpinner");

function resetTherapistForm(){ thName.value=""; thSpec.value=""; thPhone2.value=""; thActiveChk.checked=true; }

document.getElementById("therapistForm").addEventListener("submit", async (e)=>{
  e.preventDefault();
  const name = document.getElementById("thName").value.trim();
  const spec = document.getElementById("thSpec").value.trim();
  const phone = document.getElementById("thPhone").value.trim();
  const active = document.getElementById("thActive").checked;

  if(!name){ showAlert("Podaj imię i nazwisko terapeuty.", "warning"); return; }

  const url = _therapistEditId ? `${API}/api/therapists/${_therapistEditId}` : `${API}/api/therapists`;
  const method = _therapistEditId ? "PUT" : "POST";
  const payload = { full_name: name, specialization: spec || null, phone: phone || null, active };

  const therapistCanvasEl = document.getElementById('therapistCanvas');

  try {
    const res = await fetch(url, { method, headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
    await assertOk(res);
    await res.json();

    bootstrap.Offcanvas.getInstance(therapistCanvasEl).hide();

    showAlert(_therapistEditId ? "Zaktualizowano terapeutę." : "Dodano terapeutę.", "success");
    _therapistEditId = null;
    loadTherapists();
    checkDailyGaps();
  } catch(err) {
    bootstrap.Offcanvas.getInstance(therapistCanvasEl).hide();
    showAlert(`Błąd zapisu terapeuty: ${err.message}`, "danger");
  }
});

const drName = document.getElementById("drName");
const drPhone = document.getElementById("drPhone");
const drActiveChk = document.getElementById("drActive");
const drSaveBtn = document.getElementById("drSaveBtn");
const drSpinner = document.getElementById("drSpinner");

function resetDriverForm(){ drName.value=""; drPhone.value=""; drActiveChk.checked=true; }

document.getElementById("driverForm").addEventListener("submit", async (e)=>{
  e.preventDefault();
  const name = document.getElementById("drName").value.trim();
  const phone = document.getElementById("drPhone").value.trim();
  const active = document.getElementById("drActive").checked;

  if (!name){ showAlert("Podaj imię i nazwisko kierowcy.", "warning"); return; }
  if (!_driverEditId && existsDriverByName(name)){ showAlert("Taki kierowca już istnieje.", "warning"); return; }

  const btn = document.getElementById("drSaveBtn");
  const spn = document.getElementById("drSpinner");
  spn.classList.remove('d-none'); btn.setAttribute('disabled','disabled');

  const driverCanvasEl = document.getElementById('driverCanvas');

  try {
    const url = _driverEditId ? `${API}/api/drivers/${_driverEditId}` : `${API}/api/drivers`;
    const method = _driverEditId ? "PUT" : "POST";
    const payload = { full_name: name, phone: phone || null, active };

    const res = await fetch(url, { method, headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
    await assertOk(res);
    await res.json();

    bootstrap.Offcanvas.getInstance(driverCanvasEl).hide();

    showAlert(_driverEditId ? "Zaktualizowano kierowcę." : "Dodano kierowcę.", "success");
    _driverEditId = null;
    loadDrivers();
    checkDailyGaps();
  } catch (err) {
    bootstrap.Offcanvas.getInstance(driverCanvasEl).hide();
    showAlert(`Błąd zapisu kierowcy: ${err.message}`, "danger");
  } finally {
    spn.classList.add('d-none'); btn.removeAttribute('disabled');
  }
});

function showError(msg) {
  const box = document.getElementById("errorBox");
  box.textContent = msg;
  box.classList.remove("d-none");
  setTimeout(() => box.classList.add("d-none"), 5000);
}

async function submitForm(url, payload) {
  try {
    const res = await fetch(`${API}${url}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || `Błąd API (${res.status})`);
    }
    return await res.json();
  } catch (err) {
    showError(`Operacja nieudana: ${err.message}`);
    throw err;
  }
}

document.getElementById("btnOpenTherapistAdd").addEventListener("click", (e)=>{
  e.preventDefault();
  document.getElementById("thName").value = "";
  document.getElementById("thSpec").value = "";
  document.getElementById("thPhone").value = "";
  document.getElementById("thActive").checked = true;
  (new bootstrap.Offcanvas('#therapistCanvas')).show();
});

document.getElementById("btnOpenDriverAdd").addEventListener("click", (e)=>{
  e.preventDefault();
  document.getElementById("drName").value = "";
  document.getElementById("drPhone").value = "";
  document.getElementById("drActive").checked = true;
  (new bootstrap.Offcanvas('#driverCanvas')).show();
});

async function loadTherapists(){
  const tbody = document.getElementById("therapistsTbody");
  tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">Ładowanie…</td></tr>`;
  try{
    const res = await fetch(`${API}/api/therapists`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if(!data.length){
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">Brak terapeutów</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(t => {
      const badge = t.active ? `<span class="badge text-bg-success">aktywny</span>`
                             : `<span class="badge text-bg-secondary">nieaktywny</span>`;
      return `
        <tr>
          <td>${t.id}</td>
          <td>${t.full_name}</td>
          <td class="d-none d-md-table-cell">${t.specialization ?? ""}</td>
          <td class="d-none d-lg-table-cell">${t.phone ?? ""}</td>
          <td>${badge}</td>
          <td class="text-end">
            <div class="btn-group">
              <button class="btn btn-sm btn-outline-primary" onclick="openTherapistEdit(${t.id})">Edytuj</button>
              <button class="btn btn-sm btn-outline-warning" onclick="openAbsenceModal('therapist', ${t.id})">Dodaj L4/U</button>
              <button class="btn btn-sm btn-outline-danger" onclick="confirmDeleteTherapist(${t.id})">Usuń</button>
              <button class="btn btn-sm btn-outline-primary" onclick="openTherapistSchedule(${t.id}, '${(t.full_name || '').replace(/'/g, "\\'")}')">Grafik</button>
              <button class="btn btn-sm btn-outline-secondary" onclick="openTherapistReport(${t.id}, '${(t.full_name || '').replace(/'/g, "\\'")}')">Zestawienie</button>
            </div>
          </td>
        </tr>`;
    }).join("");
  }catch(err){
    tbody.innerHTML = `<tr><td colspan="6" class="text-danger py-3">Błąd ładowania: ${err.message}</td></tr>`;
  }
}
window.loadTherapists = loadTherapists;

async function loadDrivers(){
  const tbody = document.getElementById("driversTbody");
  tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">Ładowanie…</td></tr>`;
  try{
    const res = await fetch(`${API}/api/drivers`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if(!data.length){
      tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">Brak kierowców</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(d => {
    const badge = d.active ? `<span class="badge text-bg-success">aktywny</span>`
                           : `<span class="badge text-bg-secondary">nieaktywny</span>`;
    return `
      <tr>
        <td>${d.id}</td>
        <td>${d.full_name}</td>
        <td class="d-none d-lg-table-cell">${d.phone ?? ""}</td>
        <td>${badge}</td>
        <td class="text-end">
          <div class="btn-group">
            <button class="btn btn-sm btn-outline-primary" onclick="openDriverEdit(${d.id})">Edytuj</button>
            <button class="btn btn-sm btn-outline-warning" onclick="openAbsenceModal('driver', ${d.id})">Dodaj L4/U</button>
            <button class="btn btn-sm btn-outline-danger" onclick="confirmDeleteDriver(${d.id})">Usuń</button>
            <button class="btn btn-sm btn-outline-primary" onclick="openDriverSchedule(${d.id}, '${(d.full_name || '').replace(/'/g, "\\'")}')">Kursy</button>
          </div>
        </td>
      </tr>`;
  }).join("");
  }catch(err){
    tbody.innerHTML = `<tr><td colspan="5" class="text-danger py-3">Błąd ładowania: ${err.message}</td></tr>`;
  }
}
window.loadDrivers = loadDrivers;

async function confirmDeleteTherapist(id){
  if(!confirm("Usunąć terapeutę? (domyślnie: oznacz jako nieaktywny)")) return;
  try{
    const res = await fetch(`${API}/api/therapists/${id}`, { method: "DELETE" });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    loadTherapists();
    showAlert("Usunięto terapeutę (lub oznaczono jako nieaktywnego).", "success");
  }catch(err){
    showAlert(`Błąd usuwania terapeuty: ${err.message}`, "danger");
  }
}
window.confirmDeleteTherapist = confirmDeleteTherapist;

async function confirmDeleteDriver(id){
  if(!confirm("Usunąć kierowcę? (domyślnie: oznacz jako nieaktywnego)")) return;
  try{
    const res = await fetch(`${API}/api/drivers/${id}`, { method: "DELETE" });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    loadDrivers();
    showAlert("Usunięto kierowcę (lub oznaczono jako nieaktywnego).", "success");
  }catch(err){
    showAlert(`Błąd usuwania kierowcy: ${err.message}`, "danger");
  }
}
window.confirmDeleteDriver = confirmDeleteDriver;

async function assertOk(res) {
  if (res.ok) return;
  let msg = `HTTP ${res.status}`;
  try {
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      const j = await res.json();
      if (j && j.error) msg = j.error;
    } else {
      msg = (await res.text()) || msg;
    }
  } catch {}
  const err = new Error(msg);
  err.status = res.status;
  throw err;
}

loadTherapists();
loadDrivers();

function existsClientByName(name){
  const needle = (name || "").trim().toLowerCase();
  if (!needle) return false;
  const rows = document.querySelectorAll("#clientsTbody tr");
  for (const tr of rows) {
    const td = tr.querySelector("td");
    if (!td) continue;
    const val = td.textContent.trim().toLowerCase();
    if (val === needle) return true;
  }
  return false;
}

function existsTherapistByName(name){
  const needle = (name || "").trim().toLowerCase();
  if (!needle) return false;
  const rows = document.querySelectorAll("#therapistsTbody tr");
  for (const tr of rows) {
    const td = tr.children[1];
    if (!td) continue;
    const val = td.textContent.trim().toLowerCase();
    if (val === needle) return true;
  }
  return false;
}

function existsDriverByName(name){
  const needle = (name || "").trim().toLowerCase();
  if (!needle) return false;
  const rows = document.querySelectorAll("#driversTbody tr");
  for (const tr of rows) {
    const td = tr.children[1];
    if (!td) continue;
    const val = td.textContent.trim().toLowerCase();
    if (val === needle) return true;
  }
  return false;
}

let _editingGroupId = null;
let therapistsList = [];
let driversList = [];

function fillSelect(selectEl, items, valueKey, labelFn) {
  const current = selectEl.value;
  selectEl.innerHTML = `<option value="">— wybierz —</option>` +
    items.map(it => `<option value="${it[valueKey]}">${labelFn(it)}</option>`).join("");
  if (current && [...selectEl.options].some(o => o.value === current)) {
    selectEl.value = current;
  }
}

async function loadTherapistsAndDrivers() {
  const [tRes, dRes] = await Promise.all([
    fetch(`${API}/api/therapists`),
    fetch(`${API}/api/drivers`)
  ]);
  if (!tRes.ok) throw new Error(`Therapists HTTP ${tRes.status}`);
  if (!dRes.ok) throw new Error(`Drivers HTTP ${dRes.status}`);
  therapistsList = await tRes.json();
  driversList = await dRes.json();

  const therapistsActive = therapistsList.filter(t => t.active !== false);
  const driversActive = driversList.filter(d => d.active !== false);

  fillSelect(thSelect, therapistsActive, "id", t => t.full_name + (t.specialization ? ` – ${t.specialization}` : ""));
  fillSelect(pkDriverSelect, driversActive, "id", d => d.full_name + (d.phone ? ` – ${d.phone}` : ""));
  fillSelect(dpDriverSelect, driversActive, "id", d => d.full_name + (d.phone ? ` – ${d.phone}` : ""));
}

function fmt(dtStr){
  if(!dtStr) return "—";
  const d = new Date(dtStr);
  const y = d.getFullYear();
  const m = String(d.getMonth()+1).padStart(2,'0');
  const day = String(d.getDate()).padStart(2,'0');
  const hh = String(d.getHours()).padStart(2,'0');
  const mm = String(d.getMinutes()).padStart(2,'0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

const clientPackagesCanvas = new bootstrap.Offcanvas('#clientPackagesCanvas');

function groupByDate(items) {
  const groups = {};
  items.forEach(p => {
    const date = new Date(p.starts_at).toLocaleDateString("pl-PL");
    if (!groups[date]) groups[date] = [];
    groups[date].push(p);
  });
  return groups;
}

async function openTherapistSchedule(tid, name){
  document.getElementById("tsTherapistName").textContent = name || `ID ${tid}`;
  const tbody = document.getElementById("therapistScheduleTbody");
  tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-3">Ładowanie…</td></tr>`;
  const therapistScheduleCanvas = new bootstrap.Offcanvas('#therapistScheduleCanvas');
  therapistScheduleCanvas.show();
  const mk = monthInput.value || "";
  try{
    const res = await fetch(`${API}/api/therapists/${tid}/schedule?month=${encodeURIComponent(mk)}`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if(!data.length){
      tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-3">Brak zdarzeń</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(r => `
      <tr>
        <td><span class="badge text-bg-${r.kind==='therapy'?'primary':(r.kind==='pickup'?'info':'secondary')}">${r.kind}</span></td>
        <td>${r.client_name} <small class="text-muted">(#${r.client_id})</small></td>
        <td>${ fmtLocalDateTime(r.starts_at)}</td>
        <td>${fmtLocalDateTime(r.ends_at)}</td>
        <td>${r.place_from ?? "—"}</td>
        <td>${r.place_to ?? "—"}</td>
        <td>${r.status}</td>
      </tr>`).join("");
  }catch(err){
    tbody.innerHTML = `<tr><td colspan="7" class="text-danger py-3">Błąd: ${err.message}</td></tr>`;
  }
}
window.openTherapistSchedule = openTherapistSchedule;

let _lastDriverSchedule = { driverId: null, fullName: "", rows: [] };

async function openDriverSchedule(did, fullName){
  console.log("openDriverSchedule called with:", did, fullName);
  const modalEl = document.getElementById("driverScheduleModal");
  const titleEl = document.getElementById("driverScheduleTitle");
  const bodyEl  = document.getElementById("driverScheduleBody");
  if (!modalEl || !titleEl || !bodyEl) {
    showAlert("Brak szablonu modala kierowcy w HTML.", "danger");
    return;
  }

  titleEl.textContent = `Kursy: ${fullName || `ID ${did}`}`;
  bodyEl.innerHTML = `<div class="text-muted py-3">Ładowanie…</div>`;

  const mk = monthInput.value || "";
  try{
    const res = await fetch(`${API}/api/drivers/${did}/schedule?month=${encodeURIComponent(mk)}`);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    _lastDriverSchedule = { driverId: did, fullName: fullName || `ID ${did}`, rows: data };

    bodyEl.innerHTML = renderDriverScheduleHTML(_lastDriverSchedule.fullName, data);

    new bootstrap.Modal(modalEl).show();
  }catch(err){
    bodyEl.innerHTML = `<div class="text-danger py-3">Błąd: ${err.message}</div>`;
  }
}
window.openDriverSchedule = openDriverSchedule;

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "printDriverBtn") {
    e.preventDefault();
    printDriverSchedule();
  }
});

function minutesToHM(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h && m) return `${h} h ${m} min`;
  if (h) return `${h} h`;
  return `${m} min`;
}

function renderDriverScheduleHTML(fullName, data) {
  const groups = new Map();
  let sumMonth = 0;

  for (const row of data) {
    const iso = row.starts_at || row.ends_at;
    if (!iso) continue;
    const { key, label } = dateKeyPLLocal(iso);

    if (!key) continue;
    if (!groups.has(key)) groups.set(key, { label, items: [], sumDay: 0 });

    const g = groups.get(key);
    const mins = minutesBetweenLocal(row.starts_at, row.ends_at);

    g.sumDay += mins;
    sumMonth += mins;
    g.items.push(row);
  }

  const ordered = [...groups.entries()].sort(([a],[b]) => a.localeCompare(b));

  let html = `
    <div class="mb-2"><strong>Kierowca:</strong> ${fullName}</div>
    ${monthInput && monthInput.value ? `<div class="mb-2"><strong>Miesiąc:</strong> ${monthInput.value}</div>` : ""}
    <div class="mb-3">
      <span class="badge text-bg-dark">Razem w miesiącu: ${minutesToHM(sumMonth)}</span>
    </div>`;

  if (!ordered.length) {
    html += `<div class="text-muted">Brak kursów w wybranym zakresie.</div>`;
    return html;
  }

  for (const [, group] of ordered) {
    const header = `
      <div class="d-flex flex-wrap align-items-center justify-content-between mt-3 mb-2">
        <h6 class="m-0">${group.label}</h6>
        <span class="badge text-bg-primary">Suma dnia: ${minutesToHM(group.sumDay)}</span>
      </div>`;

    const rows = group.items
    .sort((a,b) => (a.starts_at||"").localeCompare(b.starts_at||""))
    .map(row => {
        const mins = minutesBetweenLocal(row.starts_at, row.ends_at);
        const route = [row.place_from, row.place_to].filter(Boolean).join(" → ");
        return `
          <tr>
            <td><span class="badge text-bg-${row.kind === 'pickup' ? 'info' : 'secondary'}">${row.kind}</span></td>
            <td>${fmtLocalTime(row.starts_at)}–${fmtLocalTime(row.ends_at)}</td>
            <td>${minutesToHM(mins)}</td>
            <td>${row.client_name || `klient #${row.client_id ?? ""}`}</td>
            <td>${route || "—"}</td>
            <td>${row.vehicle_id ?? "—"}</td>
            <td>${row.distance_km ? `${row.distance_km} km` : '—'}</td>
            <td><code>${row.status || ""}</code></td>
          </tr>`;
      }).join("");

    html += `
      ${header}
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead class="table-light">
            <tr>
              <th>Rodzaj</th><th>Godzina</th><th>Czas</th><th>Klient</th><th>Trasa</th><th>Pojazd</th><th>Dystans</th><th>Status</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  return html;
}

function printDriverSchedule() {
  const { fullName, rows } = _lastDriverSchedule || {};
  if (!rows || !rows.length) {
    showAlert("Brak danych do wydruku kursów.", "warning");
    return;
  }
  const content = renderDriverScheduleHTML(fullName, rows);
  const monthInfo = (monthInput && monthInput.value)
    ? `<div><strong>Miesiąc:</strong> ${monthInput.value}</div>` : "";

  const html = `<!doctype html>
  <html lang="pl">
  <head>
    <meta charset="utf-8">
    <title>Kursy kierowcy – ${String(fullName).replace(/</g,'&lt;')}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      @media print {
        .badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        body { font-size: 12px; }
        h6 { margin-top: 0.5rem; }
        table { page-break-inside: avoid; }
      }
      body { padding: 1rem; }
    </style>
  </head>
  <body>
    <div class="d-flex justify-content-between align-items-start mb-3">
      <div>
        <h4 class="mb-1">Kursy kierowcy</h4>
        <div><strong>Kierowca:</strong> ${String(fullName).replace(/</g,'&lt;')}</div>
        ${monthInfo}
      </div>
      <div class="text-end">
        <small class="text-muted">Wygenerowano: ${new Date().toLocaleString("pl-PL")}</small>
      </div>
    </div>
    ${content}
  </body>
  </html>`;

  const iframe = document.createElement("iframe");
  iframe.style.position = "fixed";
  iframe.style.right = "0";
  iframe.style.bottom = "0";
  iframe.style.width = "0";
  iframe.style.height = "0";
  iframe.style.border = "0";
  iframe.setAttribute("aria-hidden", "true");
  document.body.appendChild(iframe);

  const ifrw = iframe.contentWindow;
  const ifrd = iframe.contentDocument || ifrw.document;
  ifrd.open(); ifrd.write(html); ifrd.close();

  let printed = false;
  const cleanup = () => setTimeout(() => iframe.remove(), 100);

  iframe.onload = () => {
    if (printed) return;
    printed = true;
    try { ifrw.focus(); setTimeout(() => { try { ifrw.print(); } catch(e){} }, 0); } catch(e){}
  };
  if (ifrw) ifrw.onafterprint = cleanup;
  setTimeout(cleanup, 5000);
}

window.renderClientPackagesHTML = function(fullName, data) {
  const groups = new Map();
  let sumMonth = 0;

  for (const row of data) {
    const iso = row.starts_at || row.ends_at;
    if (!iso) continue;
    const { key, label } = dateKeyPLLocal(iso);
    if (!key) continue;

    if (!groups.has(key)) {
      groups.set(key, { label, items: [], sumTherapy: 0, sumAll: 0 });
    }

    const g = groups.get(key);
    const mins = minutesBetweenLocal(row.starts_at, row.ends_at);

    g.sumAll += mins;
    sumMonth += mins;
    if (row.kind === "therapy") g.sumTherapy += mins;
    g.items.push(row);
  }

  const ordered = [...groups.entries()].sort(([a],[b]) => a.localeCompare(b));

  const monthInfo = (monthInput && monthInput.value)
    ? `<div class="mb-3"><strong>Miesiąc:</strong> ${monthInput.value}</div>` : "";

  let html = `
    <div class="mb-2"><strong>Klient:</strong> ${fullName}</div>
    ${monthInfo}
    <div class="mb-3">
      <span class="badge text-bg-dark">Razem w miesiącu: ${minutesToHM(sumMonth)}</span>
    </div>`;

  if (!ordered.length) {
    html += `<div class="text-muted">Brak pakietów w wybranym zakresie.</div>`;
    return html;
  }

  for (const [, group] of ordered) {
    const header = `
      <div class="d-flex flex-wrap align-items-center justify-content-between mt-3 mb-2">
        <h6 class="m-0">${group.label}</h6>
        <div class="d-flex gap-2">
          <span class="badge text-bg-primary">Razem (terapia): ${minutesToHM(group.sumTherapy)}</span>
          <span class="badge text-bg-secondary">Razem (wszystkie): ${minutesToHM(group.sumAll)}</span>
        </div>
      </div>`;

    const rows = group.items
      .sort((a,b) => (a.starts_at||"").localeCompare(b.starts_at||""))
      .map(row => {
        const mins = minutesBetweenLocal(row.starts_at, row.ends_at);

        const who = row.kind === "therapy"
          ? (row.therapist_name || `terapeuta #${row.therapist_id || "?"}`)
          : (row.driver_name || `kierowca #${row.driver_id || "?"}`);

        const route = row.kind === "therapy"
          ? (row.place_to || "—")
          : [row.place_from, row.place_to].filter(Boolean).join(" → ") || "—";

        const slotId = row.slot_id || row.id;
        const currentStatus = row.status || 'planned';
        const statusHTML = slotId ? `
          <select class="form-select form-select-sm quick-status-select"
                  data-slot-id="${slotId}"
                  data-original-value="${currentStatus}"
                  style="min-width:130px;">
            <option value="planned" ${currentStatus === 'planned' ? 'selected' : ''}>Zaplanowany</option>
            <option value="confirmed" ${currentStatus === 'confirmed' ? 'selected' : ''}>Potwierdzony</option>
            <option value="done" ${currentStatus === 'done' ? 'selected' : ''}>Wykonany</option>
            <option value="cancelled" ${currentStatus === 'cancelled' ? 'selected' : ''}>Anulowany</option>
          </select>
        ` : `<code>${currentStatus}</code>`;

        const groupId = row.group_id;
        const actionsHTML = groupId ? `
          <div class="btn-group btn-group-sm">
            <button class="btn btn-outline-warning btn-sm pkg-edit-btn"
                    data-group-id="${groupId}"
                    title="Edytuj pakiet">
              <i class="bi bi-pencil"></i>
            </button>
            <button class="btn btn-outline-danger btn-sm pkg-delete-btn"
                    data-group-id="${groupId}"
                    title="Usuń pakiet">
              <i class="bi bi-trash"></i>
            </button>
          </div>
        ` : `<span class="text-muted">—</span>`;

        return `
          <tr>
            <td><span class="badge text-bg-${row.kind === 'therapy' ? 'success' : 'info'}">${row.kind}</span></td>
            <td>${fmtLocalTime(row.starts_at)}–${fmtLocalTime(row.ends_at)}</td>
            <td>${minutesToHM(mins)}</td>
            <td>${who}</td>
            <td>${route}</td>
            <td>${statusHTML}</td>
            <td>${actionsHTML}</td>
          </tr>`;
      }).join("");

    html += `
      ${header}
      <div class="table-responsive">
        <table class="table table-sm table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Typ</th>
              <th>Godzina</th>
              <th>Czas</th>
              <th>Osoba</th>
              <th>Trasa</th>
              <th>Status</th>
              <th>Akcje</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  return html;
};

let _lastClientPackages = { clientId: null, fullName: "", rows: [] };

async function openClientPackages(clientId, fullName) {
  try {
    const mk = monthInput.value;
    const qs = mk ? `?month=${encodeURIComponent(mk)}` : "";
    const res = await fetch(`${API}/api/client/${clientId}/packages${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    _lastClientPackages = { clientId, fullName, rows: data };

    document.getElementById("clientPackagesTitle").textContent = `Pakiety: ${fullName}`;
    document.getElementById("clientPackagesBody").innerHTML = renderClientPackagesHTML(fullName, data);

    const btn = document.getElementById("printPackagesBtn");
    if (btn) btn.onclick = () => printClientPackages();

    new bootstrap.Modal(document.getElementById("clientPackagesModal")).show();
  } catch (err) {
    showAlert(`Błąd pobierania pakietów: ${err.message}`, "danger");
  }
}
window.openClientPackages = openClientPackages;

function printClientPackages() {
  const { fullName, rows } = _lastClientPackages || {};
  if (!rows || !rows.length) {
    showAlert("Brak danych do wydruku.", "warning");
    return;
  }

  const content = renderClientPackagesHTML(fullName, rows);
  const monthInfo = (monthInput && monthInput.value)
    ? `<div><strong>Miesiąc:</strong> ${monthInput.value}</div>`
    : "";

  const html = `<!doctype html>
  <html lang="pl">
  <head>
    <meta charset="utf-8">
    <title>Pakiety – ${String(fullName).replace(/</g,'&lt;')}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      @media print {
        .badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        body { font-size: 12px; }
        h6 { margin-top: 0.5rem; }
        table { page-break-inside: avoid; }
      }
      body { padding: 1rem; }
    </style>
  </head>
  <body>
    <div class="d-flex justify-content-between align-items-start mb-3">
      <div>
        <h4 class="mb-1">Pakiety klienta</h4>
        <div><strong>Klient:</strong> ${String(fullName).replace(/</g,'&lt;')}</div>
        ${monthInfo}
      </div>
      <div class="text-end">
        <small class="text-muted">Wygenerowano: ${new Date().toLocaleString("pl-PL")}</small>
      </div>
    </div>
    ${content}
  </body>
  </html>`;

  const iframe = document.createElement("iframe");
  iframe.style.position = "fixed";
  iframe.style.right = "0";
  iframe.style.bottom = "0";
  iframe.style.width = "0";
  iframe.style.height = "0";
  iframe.style.border = "0";
  iframe.setAttribute("aria-hidden", "true");
  document.body.appendChild(iframe);

  const ifrw = iframe.contentWindow;
  const ifrd = iframe.contentDocument || ifrw.document;
  ifrd.open();
  ifrd.write(html);
  ifrd.close();

  let printed = false;

  const cleanup = () => {
    if (iframe.parentNode) {
      setTimeout(() => iframe.remove(), 100);
    }
  };

  iframe.onload = () => {
    if (printed) return;
    printed = true;

    try {
      ifrw.focus();
      setTimeout(() => {
        try { ifrw.print(); } catch (e) {}
      }, 0);
    } catch (e) {
      console.error("Print iframe error:", e);
    }
  };

  if (ifrw) {
    ifrw.onafterprint = cleanup;
  }
  setTimeout(cleanup, 5000);
}

async function refreshClientPackagesModal() {
  const { clientId, fullName } = _lastClientPackages || {};
  if (!clientId) return;

  const mk = monthInput.value;
  const qs = mk ? `?month=${encodeURIComponent(mk)}` : "";
  try {
    const res = await fetch(`${API}/api/client/${clientId}/packages${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    _lastClientPackages.rows = data;
    document.getElementById("clientPackagesBody").innerHTML =
      renderClientPackagesHTML(fullName, data);
  } catch (err) {
    showAlert(`Błąd odświeżania pakietów: ${err.message}`, "danger");
  }
}

function openClientEdit(cid){
  const cl = lastClients.find(c => c.client_id === cid);
  if (!cl) { showAlert("Nie znaleziono klienta w bieżącej liście.", "warning"); return; }

  _clientEditId = cid;
  document.getElementById("clId").value = cid;
  document.getElementById("clName").value = cl.full_name || "";
  document.getElementById("clPhone").value = cl.phone || "";
  document.getElementById("clAddress").value = cl.address || "";
  document.getElementById("clActive").checked = !(cl.active === false);

  (new bootstrap.Offcanvas('#clientCanvas')).show();
}

let _clientSubmitting = false;

document.getElementById("clientForm").addEventListener("submit", async (e)=>{
  e.preventDefault();
  if (_clientSubmitting) return;
  _clientSubmitting = true;

  const cid    = _clientEditId;
  const name   = document.getElementById("clName").value.trim();
  const phone  = document.getElementById("clPhone").value.trim();
  const address= document.getElementById("clAddress").value.trim();
  const active = document.getElementById("clActive").checked;

  if (!name){
    showAlert("Podaj imię i nazwisko klienta.", "warning");
    _clientSubmitting = false; return;
  }

  if (cid == null && existsClientByName(name)){
    showAlert("Taki klient już widnieje na liście (imię i nazwisko).", "warning");
    _clientSubmitting = false; return;
  }

  const btn = document.getElementById("clSaveBtn");
  const spn = document.getElementById("clSpinner");
  spn.classList.remove('d-none'); btn.setAttribute('disabled','disabled');

  try{
    const url    = cid == null ? `${API}/api/clients` : `${API}/api/clients/${cid}`;
    const method = cid == null ? "POST" : "PUT";
    const payload= { full_name: name, phone: phone || null, address: address || null, active };

    const res = await fetch(url, {
      method,
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    await assertOk(res);
    await res.json();

    clientOC.hide();

    showAlert(cid == null ? "Dodano klienta." : "Zmieniono dane klienta.", "success");
    _clientEditId = null;
    loadClients();
  } catch (err){
    showAlert(`Błąd zapisu klienta: ${err.message}`, "danger");
  } finally {
    spn.classList.add('d-none'); btn.removeAttribute('disabled');
    _clientSubmitting = false;
  }
});

async function confirmDeleteClient(cid){
  const confirmationText = "Czy na pewno chcesz TRWALE usunąć tego klienta? Spowoduje to kaskadowe usunięcie wszystkich jego pakietów, wizyt u terapeutów i kursów z kierowcami. Tej operacji NIE MOŻNA cofnąć.";

  if(!confirm(confirmationText)) return;

  try{
    const res = await fetch(`${API}/api/clients/${cid}`, { method: "DELETE" });
    await assertOk(res);

    showAlert("Klient i wszystkie jego powiązania zostały trwale usunięte.", "success");
    loadClients();
  }catch(err){
    showAlert(`Błąd usuwania klienta: ${err.message}`, "danger");
  }
}
window.confirmDeleteClient = confirmDeleteClient;

let _therapistEditId = null;
async function openTherapistEdit(id){
  _therapistEditId = id;
  const res = await fetch(`${API}/api/therapists?include_inactive=1`);
  const list = await res.json();
  const t = list.find(x => x.id === id);
  if(!t){ showAlert("Nie znaleziono terapeuty.", "danger"); return; }
  document.getElementById("thName").value = t.full_name || "";
  document.getElementById("thSpec").value = t.specialization || "";
  document.getElementById("thPhone").value = t.phone || "";
  document.getElementById("thActive").checked = !!t.active;
  (new bootstrap.Offcanvas('#therapistCanvas')).show();
}
window.openTherapistEdit = openTherapistEdit;

let _driverEditId = null;
async function openDriverEdit(id){
  _driverEditId = id;
  const res = await fetch(`${API}/api/drivers?include_inactive=1`);
  const list = await res.json();
  const d = list.find(x => x.id === id);
  if(!d){ showAlert("Nie znaleziono kierowcy.", "danger"); return; }
  document.getElementById("drName").value = d.full_name || "";
  document.getElementById("drPhone").value = d.phone || "";
  document.getElementById("drActive").checked = !!d.active;
  (new bootstrap.Offcanvas('#driverCanvas')).show();
}
window.openDriverEdit = openDriverEdit;

const dayInput = document.getElementById("dayInput");
const gapsBox  = document.getElementById("gapsBox");

(function initDay(){
  const t = new Date();
  const ds = `${t.getFullYear()}-${String(t.getMonth()+1).padStart(2,'0')}-${String(t.getDate()).padStart(2,'0')}`;
  dayInput.value = ds;
})();
dayInput.addEventListener("change", () => checkDailyGaps());

async function checkDailyGaps(){
  const d = dayInput.value;
  if (!d) return;

  gapsBox.innerHTML = `
    <div class="alert alert-info d-flex align-items-center gap-2 mb-0">
      <div class="spinner-border spinner-border-sm" role="status"></div>
      <div>Sprawdzam braki na <strong>${d}</strong>…</div>
    </div>`;

  try{
    const res = await fetch(`${API}/api/gaps/day?date=${encodeURIComponent(d)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const c = data.counts || {clients:0,therapists:0,drivers:0};
    const list = (arr, kind) => {
      if (!arr || !arr.length) return `<div class="text-muted">Brak</div>`;

      return `
        <details class="mt-2">
          <summary class="cursor-pointer">Pokaż listę (${arr.length})</summary>
          <ul class="mb-0 mt-2">
            ${arr.map(x => {
              const personId = x.id || x.client_id || x.therapist_id || x.driver_id;
              const fullName = x.full_name || 'Brak nazwy';

              let buttons = '';
              if (personId) {
                  if (kind === 'clients') {
                      buttons = `<button class="btn btn-sm btn-outline-primary ms-2" onclick="openPackageCanvas(${personId})">Dodaj pakiet</button>`;
                  } else if (kind === 'therapists') {
                      buttons = `<button class="btn btn-sm btn-outline-primary ms-2" onclick="openTherapistSchedule(${personId}, '${fullName.replace(/'/g, "\\'")}')">Grafik</button>`;
                  } else if (kind === 'drivers') {
                      buttons = `<button class="btn btn-sm btn-outline-primary ms-2" onclick="openDriverSchedule(${personId}, '${fullName.replace(/'/g, "\\'")}')">Kursy</button>`;
                  }
              } else {
                  buttons = `<span class="text-danger small ms-2">(Brak ID)</span>`;
              }

              return `<li>${fullName} ${buttons}</li>`;
            }).join("")}
          </ul>
        </details>`;
    };

    gapsBox.innerHTML = `
      <div class="card shadow-sm">
        <div class="card-body">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
            <div><strong>Braki na dzień:</strong> ${data.date}</div>
            <div class="d-flex flex-wrap gap-2">
              <span class="badge text-bg-secondary">Klienci: ${c.clients}</span>
              <span class="badge text-bg-secondary">Terapeuci: ${c.therapists}</span>
              <span class="badge text-bg-secondary">Kierowcy: ${c.drivers}</span>
              <button class="btn btn-sm btn-outline-primary" onclick="checkDailyGaps()">Odśwież</button>
            </div>
          </div>

          <div class="row g-3">
            <div class="col-12 col-lg-4">
              <h6 class="mb-1">Klienci bez zdarzeń</h6>
              ${list(data.clients || [], 'clients')}
            </div>
            <div class="col-12 col-lg-4">
              <h6 class="mb-1">Terapeuci bez terapii</h6>
              ${list(data.therapists || [], 'therapists')}
            </div>
            <div class="col-12 col-lg-4">
              <h6 class="mb-1">Kierowcy bez kursów</h6>
              ${list(data.drivers || [], 'drivers')}
            </div>
          </div>
        </div>
      </div>`;
  } catch (err){
    gapsBox.innerHTML = `<div class="alert alert-danger mb-0">Błąd sprawdzania braków: ${err.message}</div>`;
  }
}

checkDailyGaps();

document.getElementById("packageForm").addEventListener("submit", async (e)=>{
  setTimeout(checkDailyGaps, 300);
});

document.getElementById("gapsMonthBtn").addEventListener("click", checkMonthlyGaps);

async function checkMonthlyGaps(){
  const mk = monthInput.value;
  if (!mk) { showAlert("Wybierz miesiąc.", "warning"); return; }

  gapsBox.innerHTML = `
    <div class="alert alert-info d-flex align-items-center gap-2 mb-0">
      <div class="spinner-border spinner-border-sm" role="status"></div>
      <div>Sprawdzam braki w miesiącu <strong>${mk}</strong>…</div>
    </div>`;

  try{
    const res = await fetch(`${API}/api/gaps/month?month=${encodeURIComponent(mk)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const c = data.counts || {clients:0,therapists:0,drivers:0};
    const list = (arr, kind) => {
      if (!arr.length) return `<div class="text-muted">Brak</div>`;

      return `
        <details class="mt-2">
          <summary>Lista (${arr.length})</summary>
          <ul class="mb-0 mt-2">
            ${arr.map(x => {
                let absenceBadge = '';
                if (x.absence_status) {
                    const statusLabel = x.absence_status === 'L4' ? 'L4' : 'U';
                    absenceBadge = `<span class="badge text-bg-danger ms-2" title="${x.absence_status}">${statusLabel}</span>`;
                }

                const personId = x.id;
                const fullName = x.full_name || 'Brak nazwy';

                let buttons = '';
                if (personId) {
                    if (kind === 'clients') {
                        buttons = `<button class="btn btn-sm btn-outline-primary ms-2" onclick="openPackageCanvas(${personId})">Dodaj pakiet</button>`;
                    } else {
                        const scheduleFn = kind === 'therapists' ? 'openTherapistSchedule' : 'openDriverSchedule';
                        const scheduleLabel = kind === 'therapists' ? 'Grafik' : 'Kursy';
                        buttons = `<button class="btn btn-sm btn-outline-primary ms-2" onclick="${scheduleFn}(${personId}, '${fullName.replace(/'/g, "\\'")}')">${scheduleLabel}</button>`;
                    }
                }
                return `<li>${fullName} ${absenceBadge} ${buttons}</li>`;
            }).join("")}
          </ul>
        </details>`;
    };

    gapsBox.innerHTML = `
      <div class="card shadow-sm">
        <div class="card-body">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
            <div><strong>Braki w miesiącu:</strong> ${data.month}</div>
            <div class="d-flex flex-wrap gap-2">
              <span class="badge text-bg-secondary">Klienci: ${c.clients}</span>
              <span class="badge text-bg-secondary">Terapeuci: ${c.therapists}</span>
              <span class="badge text-bg-secondary">Kierowcy: ${c.drivers}</span>
              <button class="btn btn-sm btn-outline-primary" onclick="checkMonthlyGaps()">Odśwież</button>
            </div>
          </div>

          <div class="row g-3">
            <div class="col-12 col-lg-4">
              <h6 class="mb-1">Klienci bez zdarzeń w miesiącu</h6>
              ${list(data.clients || [], 'clients')}
            </div>
            <div class="col-12 col-lg-4">
              <h6 class="mb-1">Terapeuci bez terapii w miesiącu</h6>
              ${list(data.therapists || [], 'therapists')}
            </div>
            <div class="col-12 col-lg-4">
              <h6 class="mb-1">Kierowcy bez kursów w miesiącu</h6>
              ${list(data.drivers || [], 'drivers')}
            </div>
          </div>
        </div>
      </div>`;
  } catch (err){
    gapsBox.innerHTML = `<div class="alert alert-danger mb-0">Błąd sprawdzania braków: ${err.message}</div>`;
  }
}

async function ensureOptionsLoaded(retries=40, delay=50){
  while (retries-- > 0){
    const thOk = thSelect && thSelect.options && thSelect.options.length > 1;
    const pkOk = pkDriverSelect && pkDriverSelect.options && pkDriverSelect.options.length > 1;
    const dpOk = dpDriverSelect && dpDriverSelect.options && dpDriverSelect.options.length > 1;
    if (thOk || pkOk || dpOk) return;
    await new Promise(r => setTimeout(r, delay));
  }
}

async function fetchAISuggestions(){
  const client_id = Number(pkgClientId.value || 0);
  const date      = thDate.value;
  if(!client_id || !date){
    showAlert("Brakuje klienta albo daty do wygenerowania propozycji.", "warning");
    return;
  }

  await ensureOptionsLoaded();

  const res = await fetch(`${API}/api/ai/suggest`, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      client_id: client_id,
      date: date,
      therapy_window: ["08:00","17:00"],
      pickup_offset_min: 30,
      dropoff_offset_min: 30
    })
  });
  if(!res.ok){
    const t = await res.text();
    showAlert(`AI: błąd pobierania propozycji – ${t || res.status}`, "danger");
    return;
  }
  const ai = await res.json();

  const t0 = (ai.therapy || [])[0];
  if (t0){
    thSelect.value = String(t0.therapist_id || "");
    const s = new Date(t0.suggested_start);
    const e = new Date(t0.suggested_end);
    if (!isNaN(s)) thStart.value = `${String(s.getHours()).padStart(2,'0')}:${String(s.getMinutes()).padStart(2,'0')}`;
    if (!isNaN(e)) thEnd.value   = `${String(e.getHours()).padStart(2,'0')}:${String(e.getMinutes()).padStart(2,'0')}`;
    if (!thPlace.value) thPlace.value = "Poradnia";
  }

  const p0 = (ai.drivers_pickup || [])[0];
  if (p0){
    withPickup.checked = true;
    pickupFields.classList.remove("d-none");
    pkDriverSelect.value = String(p0.driver_id || "");
    const ps = new Date(p0.suggested_start);
    const pe = new Date(p0.suggested_end);
    if (!isNaN(ps)) pkStart.value = `${String(ps.getHours()).padStart(2,'0')}:${String(ps.getMinutes()).padStart(2,'0')}`;
    if (!isNaN(pe)) pkEnd.value   = `${String(pe.getHours()).padStart(2,'0')}:${String(pe.getMinutes()).padStart(2,'0')}`;
    if (!pkFrom.value) pkFrom.value = "Dom";
    if (!pkTo.value)   pkTo.value   = "Poradnia";
  } else {
    withPickup.checked = false;
    pickupFields.classList.add("d-none");
  }

  const d0 = (ai.drivers_dropoff || [])[0];
  if (d0){
    withDropoff.checked = true;
    dropoffFields.classList.remove("d-none");
    dpDriverSelect.value = String(d0.driver_id || "");
    const ds = new Date(d0.suggested_start);
    const de = new Date(d0.suggested_end);
    if (!isNaN(ds)) dpStart.value = `${String(ds.getHours()).padStart(2,'0')}:${String(ds.getMinutes()).padStart(2,'0')}`;
    if (!isNaN(de)) dpEnd.value   = `${String(de.getHours()).padStart(2,'0')}:${String(de.getMinutes()).padStart(2,'0')}`;
    if (!dpFrom.value) dpFrom.value = "Poradnia";
    if (!dpTo.value)   dpTo.value   = "Dom";
  } else {
    withDropoff.checked = false;
    dropoffFields.classList.add("d-none");
  }

  showAlert("Wstawiono propozycję pakietu (AI).", "success");
}

window.aiSuggestForClient = async function(clientId){
  openPackageCanvas(clientId);
  await ensureOptionsLoaded();
  await fetchAISuggestions();
};

let _lastTherapistReport = { therapistId: null, fullName: "", rows: [] };

const REPORT_DONE_ONLY = true;

async function openTherapistReport(tid, fullName){
  const modalEl = document.getElementById("therapistReportModal");
  const titleEl = document.getElementById("therapistReportTitle");
  const bodyEl  = document.getElementById("therapistReportBody");
  if (!modalEl || !titleEl || !bodyEl){
    showAlert("Brak szablonu modala zestawienia terapeuty.", "danger");
    return;
  }

  titleEl.textContent = `Zestawienie: ${fullName || `ID ${tid}`}`;
  bodyEl.innerHTML = `<div class="text-muted py-3">Ładowanie…</div>`;

  const mk = monthInput.value || "";
  try{
    const url = `${API}/api/therapists/${tid}/schedule?month=${encodeURIComponent(mk)}`;
    const res = await fetch(url);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const filtered = data.filter(r => r.kind === "therapy" && (!REPORT_DONE_ONLY || r.status === "done"));

    _lastTherapistReport = { therapistId: tid, fullName: fullName || `ID ${tid}`, rows: filtered };

    bodyEl.innerHTML = renderTherapistReportHTML(_lastTherapistReport.fullName, filtered);
    const btn = document.getElementById("printTherapistReportBtn");
    if (btn) btn.onclick = () => printTherapistReport();

    new bootstrap.Modal(modalEl).show();
  }catch(err){
    bodyEl.innerHTML = `<div class="text-danger py-3">Błąd: ${err.message}</div>`;
  }
}
window.openTherapistReport = openTherapistReport;

function renderTherapistReportHTML(fullName, rows){
  const groups = new Map();
  let sumMonth = 0;

  for (const r of rows){
    const iso = r.starts_at || r.ends_at;
    if (!iso) continue;
    const { key, label } = dateKeyPLLocal(iso);
    if (!key) continue;

    const mins = minutesBetweenLocal(r.starts_at, r.ends_at);
    if (!groups.has(key)) groups.set(key, { label, items: [], sumDay: 0 });
    const g = groups.get(key);
    g.items.push(r);
    g.sumDay += mins;
    sumMonth += mins;
  }

  const ordered = [...groups.entries()].sort(([a],[b]) => a.localeCompare(b));

  const mkInfo = (monthInput && monthInput.value)
    ? `<div class="mb-2"><strong>Miesiąc:</strong> ${monthInput.value}</div>` : "";

  let html = `
    <div class="mb-2"><strong>Terapeuta:</strong> ${String(fullName).replace(/</g,'&lt;')}</div>
    ${mkInfo}
    <div class="mb-3">
      <span class="badge text-bg-dark">Razem w miesiącu: ${minutesToHM(sumMonth)}</span>
      ${REPORT_DONE_ONLY ? `<span class="badge text-bg-secondary ms-2">Tylko status: done</span>` : ``}
    </div>`;

  if (!ordered.length){
    html += `<div class="text-muted">Brak zdarzeń spełniających kryteria.</div>`;
    return html;
  }

  for (const [, group] of ordered){
    const header = `
      <div class="d-flex flex-wrap align-items-center justify-content-between mt-3 mb-2">
        <h6 class="m-0">${group.label}</h6>
        <span class="badge text-bg-primary">Suma dnia: ${minutesToHM(group.sumDay)}</span>
      </div>`;

    const rowsHtml = group.items
      .sort((a,b) => (a.starts_at||"").localeCompare(b.starts_at||""))
      .map(p => {
        const mins = minutesBetweenLocal(p.starts_at, p.ends_at);
        const place = p.place_to || "—";
        return `
          <tr>
            <td>${fmtLocalTime(p.starts_at)}–${fmtLocalTime(p.ends_at)}</td>
            <td>${minutesToHM(mins)}</td>
            <td>${p.client_name || `klient #${p.client_id ?? ""}`}</td>
            <td>${place}</td>
            <td><code>${p.status || ""}</code></td>
          </tr>`;
      }).join("");

    html += `
      ${header}
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead class="table-light">
            <tr>
              <th>Godzina</th>
              <th>Czas</th>
              <th>Klient</th>
              <th>Miejsce</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>`;
  }

  return html;
}

function printTherapistReport(){
  const { fullName, rows } = _lastTherapistReport || {};
  if (!rows || !rows.length){
    showAlert("Brak danych do wydruku.", "warning");
    return;
  }
  const content = renderTherapistReportHTML(fullName, rows);
  const monthInfo = (monthInput && monthInput.value)
    ? `<div><strong>Miesiąc:</strong> ${monthInput.value}</div>` : "";

  const html = `<!doctype html>
  <html lang="pl">
  <head>
    <meta charset="utf-8">
    <title>Zestawienie terapeuty – ${String(fullName).replace(/</g,'&lt;')}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      @media print {
        .badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        body { font-size: 12px; }
        h6 { margin-top: 0.5rem; }
        table { page-break-inside: avoid; }
      }
      body { padding: 1rem; }
    </style>
  </head>
  <body>
    <div class="d-flex justify-content-between align-items-start mb-3">
      <div>
        <h4 class="mb-1">Zestawienie miesięczne – terapeuta</h4>
        <div><strong>Terapeuta:</strong> ${String(fullName).replace(/</g,'&lt;')}</div>
        ${monthInfo}
        ${REPORT_DONE_ONLY ? `<div><strong>Filtr:</strong> tylko status <code>done</code></div>` : ``}
      </div>
      <div class="text-end">
        <small class="text-muted">Wygenerowano: ${new Date().toLocaleString("pl-PL")}</small>
      </div>
    </div>
    ${content}
  </body>
  </html>`;

  const iframe = document.createElement("iframe");
  Object.assign(iframe.style, {position:"fixed", right:"0", bottom:"0", width:"0", height:"0", border:"0"});
  iframe.setAttribute("aria-hidden", "true");
  document.body.appendChild(iframe);

  const ifrw = iframe.contentWindow;
  const ifrd = iframe.contentDocument || ifrw.document;
  ifrd.open(); ifrd.write(html); ifrd.close();

  let printed = false;
  const cleanup = () => setTimeout(() => iframe.remove(), 100);

  iframe.onload = () => {
    if (printed) return;
    printed = true;
    try { ifrw.focus(); setTimeout(() => { try { ifrw.print(); } catch(e){} }, 0); } catch(e){}
  };
  if (ifrw) ifrw.onafterprint = cleanup;
  setTimeout(cleanup, 5000);
}

const clientSelectModalEl = document.getElementById('clientSelectModal');
const clientSelectModal = new bootstrap.Modal(clientSelectModalEl);
const modalClientSelect = document.getElementById('modalClientSelect');

document.getElementById('openClientSelectModalBtn').addEventListener('click', async () => {
  modalClientSelect.innerHTML = '<option value="">Ładowanie...</option>';
  modalClientSelect.disabled = true;

  try {
    let clientsToDisplay = lastClients;
    if (!clientsToDisplay || clientsToDisplay.length === 0) {
        const res = await fetch(`${API}/api/clients`);
        clientsToDisplay = await res.json();
    }

    const activeClients = clientsToDisplay.filter(c => c.active !== false);

    if (activeClients.length > 0) {
      modalClientSelect.innerHTML = '<option value="">-- wybierz klienta --</option>' +
        activeClients.map(c => `<option value="${c.client_id}">${c.full_name}</option>`).join('');
    } else {
      modalClientSelect.innerHTML = '<option value="">Brak aktywnych klientów</option>';
    }
  } catch (err) {
    modalClientSelect.innerHTML = `<option value="">Błąd ładowania: ${err.message}</option>`;
  } finally {
    modalClientSelect.disabled = false;
  }

  clientSelectModal.show();
});

document.getElementById('continueWithClientBtn').addEventListener('click', () => {
  const selectedClientId = modalClientSelect.value;

  if (selectedClientId) {
    clientSelectModal.hide();
    choosePackageType(Number(selectedClientId));
  } else {
    alert("Proszę wybrać klienta z listy.");
  }
});

document.addEventListener('DOMContentLoaded', () => {
    const checkUrlForPackageOpen = () => {
        const urlParams = new URLSearchParams(window.location.search);
        const clientIdToOpen = urlParams.get('openPackageFor');

        if (clientIdToOpen) {
            setTimeout(() => {
                openPackageCanvas(Number(clientIdToOpen));

                const newUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
                window.history.pushState({path: newUrl}, '', newUrl);
            }, 500);
        }
    };

    checkUrlForPackageOpen();
});

const absenceModalEl = document.getElementById('absenceModal');
const absenceModal = new bootstrap.Modal(absenceModalEl);
const absenceForm = document.getElementById('absenceForm');

function openAbsenceModal(personType, personId) {
  absenceForm.reset();
  document.getElementById('absencePersonType').value = personType;
  document.getElementById('absencePersonId').value = personId;
  absenceModal.show();
}

absenceForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        person_type: document.getElementById('absencePersonType').value,
        person_id: Number(document.getElementById('absencePersonId').value),
        status: document.getElementById('absenceStatus').value,
        start_date: document.getElementById('absenceStartDate').value,
        end_date: document.getElementById('absenceEndDate').value,
        notes: document.getElementById('absenceNotes').value
    };

    try {
        const response = await fetch(`${API}/api/absences`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error('Błąd serwera podczas zapisywania nieobecności.');

        showAlert('Nieobecność została pomyślnie dodana.', 'success');
        absenceModal.hide();
        checkMonthlyGaps();
    } catch (err) {
        showAlert(err.message, 'danger');
    }
});

document.getElementById('btnGoToIndividualPackage').addEventListener('click', () => {
    packageTypeModal.hide();
    openPackageCanvas(_clientIdForNewPackage);
});

document.getElementById('btnGoToTus').addEventListener('click', async () => {
    packageTypeModal.hide();

    try {
        const response = await fetch(`${API}/api/clients/${_clientIdForNewPackage}/tus-groups`);
        if (!response.ok) throw new Error('Błąd serwera przy sprawdzaniu grupy klienta.');

        const clientGroups = await response.json();

        if (clientGroups.length > 0) {
            const groupId = clientGroups[0].id;
            window.location.href = `tus.html?openGroup=${groupId}`;
        } else {
            alert("Ten klient nie jest jeszcze przypisany do żadnej grupy TUS. Zostaniesz przekierowany na główną stronę modułu, aby go dodać do istniejącej grupy lub stworzyć nową.");
            window.location.href = 'tus.html';
        }
    } catch (err) {
        alert(err.message);
    }
});

document.addEventListener('click', function(e) {
  if (e.target.closest('.pkg-edit-btn')) {
    const btn = e.target.closest('.pkg-edit-btn');
    const groupId = btn.getAttribute('data-group-id');
    if (groupId) {
      openPackageEdit(groupId);
    }
  }

  if (e.target.closest('.pkg-delete-btn')) {
    const btn = e.target.closest('.pkg-delete-btn');
    const groupId = btn.getAttribute('data-group-id');
    if (groupId) {
      confirmDeletePackage(groupId);
    }
  }
});

document.addEventListener('change', function(e) {
  if (e.target.classList.contains('quick-status-select')) {
    const slotId = parseInt(e.target.getAttribute('data-slot-id'));
    const newStatus = e.target.value;

    if (slotId && newStatus) {
      quickChangeStatus(slotId, newStatus);
    }
  }
});

window.quickChangeStatus = async function(slotId, newStatus) {
  console.log('quickChangeStatus wywołane:', { slotId, newStatus });

  if (!slotId || !newStatus) {
    console.error('Brak slotId lub newStatus');
    return;
  }

  const selectElement = document.querySelector(`select[data-slot-id="${slotId}"]`);
  const originalValue = selectElement ? selectElement.dataset.originalValue : newStatus;

  try {
    const res = await fetch(`${API}/api/slots/${slotId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus })
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP ${res.status}`);
    }

    const data = await res.json();
    console.log('Status zaktualizowany:', data);

    if (selectElement) {
      selectElement.dataset.originalValue = newStatus;
    }

    showAlert(`Status zmieniony na: ${newStatus}`, 'success');

    await refreshClientPackagesModal();
    await loadClients();

  } catch (err) {
    console.error('Błąd zmiany statusu:', err);
    showAlert(`Nie udało się zmienić statusu: ${err.message}`, 'danger');

    if (selectElement && originalValue) {
      selectElement.value = originalValue;
    }
  }
};

async function checkPackageConflicts(payload) {
  try {
    const res = await fetch(`${API}/api/schedule/check-conflicts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();

  } catch (err) {
    console.error('Błąd sprawdzania kolizji:', err);
    return { total: 0 };
  }
}

function formatConflictsMessage(conflicts) {
  if (!conflicts.total) return null;

  let message = `<div class="alert alert-warning">
    <h6 class="alert-heading"><i class="bi bi-exclamation-triangle"></i> Wykryto ${conflicts.total} kolizj${conflicts.total === 1 ? 'ę' : 'e/i'} w grafiku:</h6>
    <hr>`;

  if (conflicts.therapy && conflicts.therapy.length > 0) {
    message += `<div class="mb-3">
      <strong>Terapeuta zajęty (${conflicts.therapy.length}):</strong>
      <ul class="mb-0 mt-1">`;
    conflicts.therapy.forEach(c => {
      const start = new Date(c.starts_at).toLocaleString('pl-PL', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
      });
      const end = new Date(c.ends_at).toLocaleTimeString('pl-PL', {
        hour: '2-digit', minute: '2-digit'
      });
      message += `<li><strong>${c.client_name}</strong> - ${start} do ${end}</li>`;
    });
    message += `</ul></div>`;
  }

  if (conflicts.pickup && conflicts.pickup.length > 0) {
    message += `<div class="mb-3">
      <strong>Kierowca zajęty - dowóz (${conflicts.pickup.length}):</strong>
      <ul class="mb-0 mt-1">`;
    conflicts.pickup.forEach(c => {
      const start = new Date(c.starts_at).toLocaleString('pl-PL', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
      });
      const end = new Date(c.ends_at).toLocaleTimeString('pl-PL', {
        hour: '2-digit', minute: '2-digit'
      });
      message += `<li><strong>${c.client_name}</strong> (${c.kind}) - ${start} do ${end}</li>`;
    });
    message += `</ul></div>`;
  }

  if (conflicts.dropoff && conflicts.dropoff.length > 0) {
    message += `<div class="mb-3">
      <strong>Kierowca zajęty - odwóz (${conflicts.dropoff.length}):</strong>
      <ul class="mb-0 mt-1">`;
    conflicts.dropoff.forEach(c => {
      const start = new Date(c.starts_at).toLocaleString('pl-PL', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
      });
      const end = new Date(c.ends_at).toLocaleTimeString('pl-PL', {
        hour: '2-digit', minute: '2-digit'
      });
      message += `<li><strong>${c.client_name}</strong> (${c.kind}) - ${start} do ${end}</li>`;
    });
    message += `</ul></div>`;
  }

  if (conflicts.client && conflicts.client.length > 0) {
    message += `<div class="mb-3">
      <strong>Klient ma już inne zajęcia (${conflicts.client.length}):</strong>
      <ul class="mb-0 mt-1">`;
    conflicts.client.forEach(c => {
      const start = new Date(c.starts_at).toLocaleString('pl-PL', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
      });
      const end = new Date(c.ends_at).toLocaleTimeString('pl-PL', {
        hour: '2-digit', minute: '2-digit'
      });
      const person = c.therapist_name ? `z ${c.therapist_name}` : c.kind;
      message += `<li>${person} - ${start} do ${end}</li>`;
    });
    message += `</ul></div>`;
  }

  message += `<div class="mt-2"><strong>Czy mimo to chcesz zapisać zmiany?</strong></div></div>`;

  return message;
}

window.openAbsenceModal = openAbsenceModal;