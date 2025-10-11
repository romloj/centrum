// ========================================
// MINIMALNA EDYCJA PAKIETU - TYLKO STATUS
// ========================================

// Funkcja: Otwórz prostą edycję pakietu
async function editPackageSimple(packageId) {
  try {
    // Pobierz dane pakietu
    const response = await fetch(`/api/packages/${packageId}`);
    const pkg = await response.json();

    // Pokaż prosty modal
    const currentStatus = pkg.status || 'planned';
    const currentLabel = pkg.label || '';

    const result = confirm(`Pakiet: ${currentLabel || 'ID: ' + packageId}\n\nObecny status: ${getStatusName(currentStatus)}\n\nKliknij OK aby zmienić status`);

    if (result) {
      showStatusSelect(packageId, currentStatus);
    }

  } catch (error) {
    alert('Błąd: ' + error.message);
  }
}

// Funkcja: Pokaż wybór statusu
function showStatusSelect(packageId, currentStatus) {
  // Utwórz overlay
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0,0,0,0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
  `;

  // Utwórz panel
  const panel = document.createElement('div');
  panel.style.cssText = `
    background: white;
    padding: 30px;
    border-radius: 15px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
    max-width: 400px;
    width: 90%;
  `;

  panel.innerHTML = `
    <h4 style="margin: 0 0 20px 0; color: #333;">
      <i class="bi bi-pencil-square"></i> Zmień status
    </h4>

    <div style="margin-bottom: 20px;">
      <label style="display: block; margin-bottom: 10px; font-weight: 600;">Wybierz nowy status:</label>
      <select id="statusSelect" class="form-select form-select-lg" style="font-size: 1rem;">
        <option value="planned" ${currentStatus === 'planned' ? 'selected' : ''}>🔵 Zaplanowany</option>
        <option value="confirmed" ${currentStatus === 'confirmed' ? 'selected' : ''}>🟡 Potwierdzony</option>
        <option value="done" ${currentStatus === 'done' ? 'selected' : ''}>✅ Wykonany</option>
        <option value="cancelled" ${currentStatus === 'cancelled' ? 'selected' : ''}>❌ Anulowany</option>
      </select>
    </div>

    <div style="display: flex; gap: 10px;">
      <button id="cancelBtn" class="btn btn-secondary" style="flex: 1;">
        Anuluj
      </button>
      <button id="saveBtn" class="btn btn-success" style="flex: 1;">
        ✓ Zapisz
      </button>
    </div>
  `;

  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  // Zamknij na kliknięcie tła
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      overlay.remove();
    }
  });

  // Przycisk Anuluj
  panel.querySelector('#cancelBtn').addEventListener('click', () => {
    overlay.remove();
  });

  // Przycisk Zapisz
  panel.querySelector('#saveBtn').addEventListener('click', async () => {
    const newStatus = panel.querySelector('#statusSelect').value;

    try {
      const response = await fetch(`/api/packages/${packageId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });

      if (!response.ok) throw new Error('Błąd zapisu');

      overlay.remove();
      alert('✓ Status zmieniony na: ' + getStatusName(newStatus));
      location.reload();

    } catch (error) {
      alert('Błąd: ' + error.message);
    }
  });
}

// Pomocnicza funkcja - nazwa statusu
function getStatusName(status) {
  const names = {
    'planned': '🔵 Zaplanowany',
    'confirmed': '🟡 Potwierdzony',
    'done': '✅ Wykonany',
    'cancelled': '❌ Anulowany'
  };
  return names[status] || status;
}

// Dodaj przyciski edycji do wszystkich wierszy
function addEditButtons() {
  // Znajdź wszystkie wiersze z pakietami
  document.querySelectorAll('tbody tr').forEach(row => {
    // Pomiń jeśli już ma przycisk
    if (row.querySelector('.edit-package-btn')) return;

    // Spróbuj znaleźć ID pakietu (różne możliwe atrybuty)
    const packageId = row.getAttribute('data-package-id') ||
                      row.getAttribute('data-id') ||
                      row.querySelector('[data-package-id]')?.getAttribute('data-package-id');

    if (!packageId) return;

    // Znajdź ostatnią kolumnę lub stwórz nową
    let lastCell = row.querySelector('td:last-child');

    // Dodaj przycisk edycji
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-warning edit-package-btn';
    btn.innerHTML = '<i class="bi bi-pencil"></i>';
    btn.title = 'Edytuj status';
    btn.style.marginLeft = '5px';
    btn.onclick = (e) => {
      e.stopPropagation();
      editPackageSimple(packageId);
    };

    lastCell.appendChild(btn);
  });
}

// Uruchom po załadowaniu
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', addEditButtons);
} else {
  addEditButtons();
}

// Obserwuj zmiany w tabeli (dla dynamicznie dodawanych wierszy)
const observer = new MutationObserver(addEditButtons);
const tbody = document.querySelector('tbody');
if (tbody) {
  observer.observe(tbody, { childList: true, subtree: true });
}

// Eksportuj do window
window.editPackageSimple = editPackageSimple;