// ========================================
// PANEL-FIX.JS - Dodatek naprawiający edycję pakietów
// Nie zmienia istniejącego kodu, tylko dodaje nowe funkcje
// ========================================

console.log('🔧 Panel-fix.js załadowany');

// Czekaj aż cały DOM i panel.js się załadują
window.addEventListener('load', function() {
  console.log('✅ Inicjalizuję naprawę pakietów...');

  // Czekaj jeszcze chwilę na panel.js
  setTimeout(initPackageFix, 500);
});

function initPackageFix() {
  console.log('🚀 Uruchamiam panel-fix...');

  // Znajdź wszystkie pakiety i dodaj im edycję
  addEditToPackages();

  // Obserwuj nowe pakiety
  observeNewPackages();

  console.log('✅ Panel-fix gotowy!');
}

// ========================================
// EDYCJA PAKIETÓW - WERSJA DZIAŁAJĄCA
// ========================================

function addEditToPackages() {
  // Znajdź wszystkie elementy które mogą być pakietami
  const selectors = [
    'tr[data-package-id]',
    'tr[data-id]',
    '.package-row',
    'tbody tr'
  ];

  let foundPackages = 0;

  selectors.forEach(selector => {
    document.querySelectorAll(selector).forEach(row => {
      // Sprawdź czy to pakiet
      const packageId = getPackageId(row);
      if (!packageId) return;

      // Sprawdź czy już ma przycisk
      if (row.querySelector('.pkg-edit-btn')) return;

      // Dodaj przycisk edycji
      addEditButton(row, packageId);
      foundPackages++;
    });
  });

  console.log(`📦 Znaleziono ${foundPackages} pakietów`);
}

// Pobierz ID pakietu z wiersza
function getPackageId(row) {
  // Spróbuj różnych sposobów znalezienia ID
  return row.getAttribute('data-package-id') ||
         row.getAttribute('data-id') ||
         row.getAttribute('data-pkg-id') ||
         row.querySelector('[data-package-id]')?.getAttribute('data-package-id') ||
         row.querySelector('[data-id]')?.getAttribute('data-id');
}

// Dodaj przycisk edycji do wiersza
function addEditButton(row, packageId) {
  // Znajdź kolumnę "Akcje" lub ostatnią kolumnę
  let actionCell = row.querySelector('td:last-child');

  if (!actionCell) return;

  // Stwórz przycisk
  const btn = document.createElement('button');
  btn.className = 'btn btn-sm btn-warning pkg-edit-btn';
  btn.innerHTML = '<i class="bi bi-pencil"></i> Status';
  btn.style.cssText = 'margin-left: 5px; white-space: nowrap;';
  btn.title = 'Zmień status pakietu';

  // Dodaj event
  btn.addEventListener('click', function(e) {
    e.stopPropagation();
    e.preventDefault();
    openStatusEditor(packageId);
  });

  actionCell.appendChild(btn);
}

// Otwórz edytor statusu
function openStatusEditor(packageId) {
  console.log('📝 Edycja pakietu:', packageId);

  // Stwórz modal
  const modal = createStatusModal(packageId);
  document.body.appendChild(modal);

  // Pokaż modal
  const bsModal = new bootstrap.Modal(modal);
  bsModal.show();

  // Usuń po zamknięciu
  modal.addEventListener('hidden.bs.modal', () => {
    modal.remove();
  });
}

// Stwórz modal wyboru statusu
function createStatusModal(packageId) {
  const modal = document.createElement('div');
  modal.className = 'modal fade';
  modal.innerHTML = `
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">
            <i class="bi bi-pencil-square"></i>
            Zmień status pakietu
          </h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">
          <p class="text-muted mb-3">Pakiet ID: ${packageId}</p>

          <div class="d-grid gap-2">
            <button class="btn btn-lg btn-outline-primary status-btn" data-status="planned">
              🔵 Zaplanowany
            </button>
            <button class="btn btn-lg btn-outline-warning status-btn" data-status="confirmed">
              🟡 Potwierdzony
            </button>
            <button class="btn btn-lg btn-outline-success status-btn" data-status="done">
              ✅ Wykonany
            </button>
            <button class="btn btn-lg btn-outline-secondary status-btn" data-status="cancelled">
              ❌ Anulowany
            </button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Dodaj eventy do przycisków
  modal.querySelectorAll('.status-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const status = this.getAttribute('data-status');
      savePackageStatus(packageId, status, modal);
    });
  });

  return modal;
}

// Zapisz status pakietu
async function savePackageStatus(packageId, status, modal) {
  console.log('💾 Zapisuję:', packageId, status);

  try {
    // Wyświetl loading
    const buttons = modal.querySelectorAll('.status-btn');
    buttons.forEach(btn => {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    });

    // Wyślij do API
    const response = await fetch(`/api/packages/${packageId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ status: status })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    // Sukces!
    console.log('✅ Status zapisany');

    // Zamknij modal
    const bsModal = bootstrap.Modal.getInstance(modal);
    bsModal.hide();

    // Pokaż powiadomienie
    showNotification('Status pakietu został zmieniony', 'success');

    // Odśwież stronę po chwili
    setTimeout(() => {
      location.reload();
    }, 800);

  } catch (error) {
    console.error('❌ Błąd zapisu:', error);

    // Przywróć przyciski
    modal.querySelectorAll('.status-btn').forEach(btn => {
      btn.disabled = false;
      const status = btn.getAttribute('data-status');
      const labels = {
        'planned': '🔵 Zaplanowany',
        'confirmed': '🟡 Potwierdzony',
        'done': '✅ Wykonany',
        'cancelled': '❌ Anulowany'
      };
      btn.innerHTML = labels[status];
    });

    // Pokaż błąd
    showNotification('Błąd zapisu: ' + error.message, 'danger');
  }
}

// Pokaż powiadomienie
function showNotification(message, type = 'info') {
  // Usuń stare powiadomienia
  document.querySelectorAll('.fix-notification').forEach(n => n.remove());

  // Stwórz nowe
  const notification = document.createElement('div');
  notification.className = `alert alert-${type} fix-notification`;
  notification.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 9999;
    min-width: 300px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  `;

  const icons = {
    'success': 'check-circle-fill',
    'danger': 'x-circle-fill',
    'warning': 'exclamation-triangle-fill',
    'info': 'info-circle-fill'
  };

  notification.innerHTML = `
    <i class="bi bi-${icons[type]} me-2"></i>
    ${message}
  `;

  document.body.appendChild(notification);

  // Usuń po 3 sekundach
  setTimeout(() => {
    notification.style.transition = 'opacity 0.3s';
    notification.style.opacity = '0';
    setTimeout(() => notification.remove(), 300);
  }, 3000);
}

// Obserwuj nowe pakiety (jeśli są dodawane dynamicznie)
function observeNewPackages() {
  const observer = new MutationObserver(() => {
    addEditToPackages();
  });

  // Obserwuj tbody w tabelach
  document.querySelectorAll('tbody').forEach(tbody => {
    observer.observe(tbody, {
      childList: true,
      subtree: true
    });
  });

  console.log('👁️ Obserwuję nowe pakiety...');
}

// ========================================
// EKSPORT FUNKCJI
// ========================================

// Udostępnij funkcje globalnie (na wypadek gdyby były potrzebne)
window.packageFixUtils = {
  openStatusEditor,
  addEditToPackages,
  showNotification
};

console.log('✅ Panel-fix gotowy do użycia!');