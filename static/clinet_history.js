document.addEventListener('DOMContentLoaded', () => {
    const API = "";
    const clientSelector = document.getElementById('clientSelector');
    const historyContainer = document.getElementById('historyContainer');
    const alertBox = document.getElementById('alertBox');
    // POCZĄTEK ZMIANY: Referencja do pola wyszukiwania
    const searchInput = document.getElementById('searchInput');
    let allClients = []; // Zmienna do przechowywania wszystkich klientów
    // KONIEC ZMIANY

    const showAlert = (msg, type = "success") => {
        alertBox.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${msg}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
    };

    async function fetchJSON(url, options = {}) {
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: `Błąd serwera: ${response.status}` }));
                throw new Error(errorData.error);
            }
            return response.json();
        } catch (error) {
            console.error("Błąd API:", error);
            throw error;
        }
    }

    // POCZĄTEK ZMIANY: Funkcja renderująca opcje w selektorze
    function renderClientOptions(searchTerm = '') {
        const lowerCaseSearchTerm = searchTerm.toLowerCase();
        const filteredClients = allClients.filter(client =>
            client.full_name.toLowerCase().includes(lowerCaseSearchTerm)
        );

        clientSelector.innerHTML = '<option value="">-- Wybierz klienta --</option>';
        if (filteredClients.length > 0) {
            filteredClients.forEach(client => {
                const option = new Option(client.full_name, client.client_id);
                clientSelector.add(option);
            });
        } else {
             clientSelector.innerHTML = '<option value="">Brak pasujących klientów</option>';
        }
    }
    // KONIEC ZMIANY

    async function initializeClientSelector() {
        try {
            const clients = await fetchJSON(`${API}/api/clients?include_inactive=true`);
            allClients = clients.sort((a, b) => a.full_name.localeCompare(b.full_name));
            renderClientOptions(); // Wywołaj, aby wypełnić listę na starcie
        } catch (error) {
            showAlert(`Nie udało się załadować listy klientów: ${error.message}`, 'danger');
        }
    }

    async function loadClientHistory() {
        const clientId = clientSelector.value;
        if (!clientId) {
            historyContainer.innerHTML = '<p class="text-center text-muted p-5">Wybierz klienta, aby zobaczyć jego historię.</p>';
            return;
        }

        historyContainer.innerHTML = '<p class="text-center text-muted p-5">Ładowanie historii...</p>';
        try {
            const history = await fetchJSON(`${API}/api/clients/${clientId}/history`);
            renderHistory(history);
        } catch (error) {
            historyContainer.innerHTML = `<div class="alert alert-danger">Wystąpił błąd: ${error.message}</div>`;
        }
    }

    // Funkcja do skracania tekstu - DODAJ TO
function truncateText(text, maxLength = 100) {
    if (!text) return '-';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
    }

// Funkcja renderująca historię z endpointa /sessions (pełne dane)
function renderHistoryFromSessions(sessions) {
    if (!sessions || sessions.length === 0) {
        historyContainer.innerHTML = '<div class="alert alert-info">Brak sesji dla tego klienta.</div>';
        return;
    }

    let html = `
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="mb-0"><i class="bi bi-person-fill"></i> Wszystkie Sesje Terapeutyczne</h5>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-light">
                            <tr>
                                <th style="width: 15%;">Data i Godzina</th>
                                <th style="width: 15%;">Terapeuta</th>
                                <th style="width: 25%;">Temat</th>
                                <th style="width: 35%;">Notatki</th>
                                <th style="width: 10%;">Akcje</th>
                            </tr>
                        </thead>
                        <tbody>`;

    sessions.forEach((session, index) => {
        const topic = session.label || session.topic || 'Bez tematu';
        const notes = session.notes || '';
        const truncatedNotes = truncateText(notes, 80);
        const hasNotes = notes.length > 0;
        const therapist = session.therapist_name || 'Nieznany';
        const date = session.starts_at || session.date;

        html += `
            <tr>
                <td>${new Date(date).toLocaleString('pl-PL', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                })}</td>
                <td>${therapist}</td>
                <td><strong>${topic}</strong></td>
                <td>
                    ${hasNotes ? `
                        <div class="text-muted small">${truncatedNotes}</div>
                    ` : '<span class="text-muted fst-italic">Brak notatek</span>'}
                </td>
                <td>
                    <button class="btn btn-sm btn-outline-primary"
                        data-session='${JSON.stringify({
                            date: date,
                            therapist: therapist,
                            topic: topic,
                            notes: notes,
                            place: session.place_to || session.place || '',
                            duration: session.duration_minutes || 60
                        }).replace(/'/g, "&apos;")}'
                        onclick="showSessionDetails(this)">
                        <i class="bi bi-eye"></i>
                    </button>
                </td>
            </tr>
        `;
    });

    html += `</tbody></table></div></div></div>`;
    historyContainer.innerHTML = html;
}

    function renderHistory(history) {
        console.log('📥 Otrzymane dane z API:', history);
        console.log('📊 Liczba sesji indywidualnych:', history.individual?.length);
        console.log('📋 Pierwsza sesja:', history.individual?.[0]);
        let html = '';

        // Sekcja spotkań indywidualnych
        html += `
            <div class="card mb-4">
                <div class="card-header">
                    <h5 class="mb-0">Spotkania Indywidualne</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-striped table-hover">
                            <thead class="table-light">
                                <tr>
                                    <th>Data i Godzina</th>
                                    <th>Terapeuta</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>`;

        if (history.individual && history.individual.length > 0) {
            history.individual.forEach(session => {
                html += `
    <tr>
            <td>${new Date(session.date).toLocaleString('pl-PL', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            })}</td>
            <td>${session.therapist || '-'}</td>
            <td><strong>${session.topic || 'Bez tematu'}</strong></td>
            <td>
                ${session.notes ? `
                    <div class="text-muted small">${truncateText(session.notes, 80)}</div>
                ` : '<span class="text-muted fst-italic">Brak notatek</span>'}
            </td>
            <td>
                <button class="btn btn-sm btn-outline-primary"
                    data-session='${JSON.stringify(session).replace(/'/g, "&apos;")}'
                    onclick="showSessionDetails(this)">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>
    `;
            });
        } else {
            html += '<tr><td colspan="3" class="text-center text-muted">Brak spotkań indywidualnych w historii.</td></tr>';
        }
        html += `</tbody></table></div></div></div>`;

        // Sekcja spotkań TUS
        html += `
            <div class="card">
                <div class="card-header">
                    <h5 class="mb-0">Sesje Grupowe TUS</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-striped table-hover">
                            <thead class="table-light">
                                <tr>
                                    <th>Data i Godzina</th>
                                    <th>Grupa</th>
                                    <th>Zrealizowany Temat</th>
                                </tr>
                            </thead>
                            <tbody>`;

        if (history.tus_group && history.tus_group.length > 0) {
            history.tus_group.forEach(session => {
                const sessionTime = session.time ? ` ${session.time}` : '';
                html += `
                    <tr>
                        <td>${new Date(session.date).toLocaleDateString('pl-PL')}${sessionTime}</td>
                        <td>${session.group}</td>
                        <td>${session.topic}</td>
                    </tr>
                `;
            });
        } else {
            html += '<tr><td colspan="3" class="text-center text-muted">Brak sesji TUS w historii.</td></tr>';
        }
        html += `</tbody></table></div></div></div>`;

        historyContainer.innerHTML = html;
    }

    clientSelector.addEventListener('change', loadClientHistory);
    // POCZĄTEK ZMIANY: Nasłuchiwanie na wpisywanie w polu wyszukiwania
    searchInput.addEventListener('input', () => {
        renderClientOptions(searchInput.value);
    });
    // KONIEC ZMIANY

    initializeClientSelector();
    loadClientHistory();
});
    document.addEventListener('DOMContentLoaded', () => {
        const fabContainer = document.getElementById('fab-container');
        const fabMainBtn = document.getElementById('fab-main-btn');

        fabMainBtn.addEventListener('click', () => {
            fabContainer.classList.toggle('open');
        });
    });

// Funkcja do wyświetlenia pełnych szczegółów sesji w modalu
function showSessionDetails(button) {
    const sessionData = button.getAttribute('data-session');
    const session = JSON.parse(sessionData);
    const clientId = document.getElementById('clientSelector').value;

    const modalHTML = `
        <div class="modal fade" id="sessionDetailsModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">📋 Szczegóły sesji</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <strong>📅 Data i godzina:</strong>
                            <p>${new Date(session.date).toLocaleString('pl-PL')}</p>
                        </div>
                        <div class="mb-3">
                            <strong>👨‍⚕️ Terapeuta:</strong>
                            <p>${session.therapist || '-'}</p>
                        </div>
                        <div class="mb-3">
                            <strong>📝 Temat:</strong>
                            <p>${session.topic || 'Bez tematu'}</p>
                        </div>
                        ${session.place ? `
                        <div class="mb-3">
                            <strong>📍 Miejsce:</strong>
                            <p>${session.place}</p>
                        </div>
                        ` : ''}
                        ${session.duration ? `
                        <div class="mb-3">
                            <strong>⏱️ Czas trwania:</strong>
                            <p>${session.duration} min</p>
                        </div>
                        ` : ''}

                        <!-- TRYB PODGLĄDU -->
                        <div id="viewMode">
                            <div class="mb-3">
                                <strong>📄 Notatki:</strong>
                                <div class="border rounded p-3 bg-light">
                                    <pre style="white-space: pre-wrap; font-family: inherit; margin: 0;">${session.notes || 'Brak notatek'}</pre>
                                </div>
                            </div>
                        </div>

                        <!-- TRYB EDYCJI (ukryty) -->
                        <div id="editMode" style="display: none;">
                            <div class="mb-3">
                                <label class="form-label"><strong>📄 Edytuj notatki:</strong></label>
                                <textarea id="editNoteContent" class="form-control" rows="8" style="font-family: inherit;">${session.notes || ''}</textarea>
                            </div>
                        </div>
                    </div>

                    <!-- PRZYCISKI PODGLĄDU -->
                    <div class="modal-footer" id="viewModeButtons">
                        <button type="button" class="btn btn-primary" onclick="toggleEditMode(true)">✏️ Edytuj</button>
                        <button type="button" class="btn btn-secondary" onclick="window.print()">🖨️ Drukuj</button>
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Zamknij</button>
                    </div>

                    <!-- PRZYCISKI EDYCJI (ukryte) -->
                    <div class="modal-footer" id="editModeButtons" style="display: none;">
                        <button type="button" class="btn btn-success" onclick="saveNoteEdit(${clientId}, '${session.date}', '${session.note_id || ''}')">💾 Zapisz</button>
                        <button type="button" class="btn btn-secondary" onclick="toggleEditMode(false)">Anuluj</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    // Usuń stary modal jeśli istnieje
    const oldModal = document.getElementById('sessionDetailsModal');
    if (oldModal) oldModal.remove();

    // Dodaj nowy modal
    document.body.insertAdjacentHTML('beforeend', modalHTML);
    const modal = new bootstrap.Modal(document.getElementById('sessionDetailsModal'));
    modal.show();

    // Usuń modal po zamknięciu
    document.getElementById('sessionDetailsModal').addEventListener('hidden.bs.modal', function () {
        this.remove();
    });
}

// Przełącz między trybem podglądu a edycji
function toggleEditMode(editMode) {
    document.getElementById('viewMode').style.display = editMode ? 'none' : 'block';
    document.getElementById('editMode').style.display = editMode ? 'block' : 'none';
    document.getElementById('viewModeButtons').style.display = editMode ? 'none' : 'flex';
    document.getElementById('editModeButtons').style.display = editMode ? 'flex' : 'none';
}

// Zapisz edytowaną notatkę
// Zapisz edytowaną notatkę
async function saveNoteEdit(clientId, sessionDate, noteId) {
    const newContent = document.getElementById('editNoteContent').value.trim();

    if (!newContent) {
        alert('Notatka nie może być pusta!');
        return;
    }

    const saveBtn = document.querySelector('#editModeButtons .btn-success');
    saveBtn.disabled = true;
    saveBtn.textContent = '⏳ Zapisywanie...';

    try {
        let response;

        if (noteId) {
            // Aktualizuj istniejącą notatkę
            response = await fetch(`/api/clients/${clientId}/notes/${noteId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: newContent,
                    category: 'session'
                })
            });
        } else {
            // Utwórz nową notatkę
            response = await fetch(`/api/clients/${clientId}/notes`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: newContent,
                    category: 'session',
                    created_by_name: 'System',
                    created_at: sessionDate
                })
            });
        }

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Błąd zapisu');
        }

        // Zamknij modal
        bootstrap.Modal.getInstance(document.getElementById('sessionDetailsModal')).hide();

        // ZMIANA: Odśwież listę używając istniejącej funkcji
        const clientSelector = document.getElementById('clientSelector');
        if (clientSelector && clientSelector.value) {
            // Wywołaj event change żeby odświeżyć
            clientSelector.dispatchEvent(new Event('change'));
        }

        // Pokaż komunikat sukcesu
        const alertBox = document.getElementById('alertBox');
        if (alertBox) {
            alertBox.innerHTML = `
                <div class="alert alert-success alert-dismissible fade show" role="alert">
                    ✅ Notatka została zapisana!
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            `;
            setTimeout(() => alertBox.innerHTML = '', 3000);
        }

    } catch (error) {
        console.error('Błąd zapisu notatki:', error);
        alert('Nie udało się zapisać notatki: ' + error.message);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '💾 Zapisz';
    }
}

// Globalnie dostępne funkcje
window.showSessionDetails = showSessionDetails;
window.toggleEditMode = toggleEditMode;
window.saveNoteEdit = saveNoteEdit;