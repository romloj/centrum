document.addEventListener('DOMContentLoaded', () => {
    // ZMIENIONY: Ustaw poprawny adres URL API, jeśli nie jest lokalny
    //const API = "http://localhost:5000";
    //const API="";
    const API = window.location.origin;
    const clientSelector = document.getElementById('clientSelector');
    const historyContainer = document.getElementById('historyContainer');
    const alertBox = document.getElementById('alertBox');
    const searchInput = document.getElementById('searchInput');
    let allClients = [];
    let currentClientId = null; // Przechowuje aktualnie wybranego klienta

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

    function renderClientOptions(searchTerm = '') {
        const lowerCaseSearchTerm = searchTerm.toLowerCase();
        const filteredClients = allClients.filter(client =>
            client.full_name.toLowerCase().includes(lowerCaseSearchTerm)
        );

        const selectedClientId = clientSelector.value;
        clientSelector.innerHTML = '<option value="">-- Wybierz klienta --</option>';
        if (filteredClients.length > 0) {
            filteredClients.forEach(client => {
                const option = new Option(client.full_name, client.client_id || client.id); // Użyj client_id lub id
                if (option.value === selectedClientId) {
                    option.selected = true;
                }
                clientSelector.add(option);
            });
        } else {
             clientSelector.innerHTML = '<option value="">Brak pasujących klientów</option>';
        }
    }

    async function initializeClientSelector() {
        try {
            // Zmieniono endpoint na standardowy /api/clients
            const clients = await fetchJSON(`${API}/api/clients?include_inactive=true`);
            allClients = clients.sort((a, b) => a.full_name.localeCompare(b.full_name));
            renderClientOptions();
        } catch (error) {
            showAlert(`Nie udało się załadować listy klientów: ${error.message}`, 'danger');
        }
    }

    async function loadClientHistory() {
        const clientId = clientSelector.value;
        currentClientId = clientId; 

        // ZMIENIONA LOGIKA
        if (clientId) {
            // === KOD DLA POJEDYNCZEGO KLIENTA (BEZ ZMIAN) ===
            historyContainer.innerHTML = '<p class="text-center text-muted p-5">Ładowanie historii...</p>';
            try {
                const allSessions = await fetchJSON(`${API}/api/clients/${clientId}/all-sessions`);
                const tusHistory = await fetchJSON(`${API}/api/clients/${clientId}/history`).then(res => res.tus_group || []);
                
                // Przekazujemy 'false' dla widoku indywidualnego
                renderHistory(allSessions, tusHistory, false); 
            } catch (error) {
                historyContainer.innerHTML = `<div class="alert alert-danger">Wystąpił błąd ładowania historii: ${error.message}</div>`;
            }
        } else {
            // === NOWY KOD DLA WIDOKU "WSZYSCY KLIENCI" ===
            historyContainer.innerHTML = '<p class="text-center text-muted p-5">Ładowanie historii wszystkich klientów...</p>';
            try {
                // 1. POTRZEBUJESZ NOWEGO ENDPOINTU W API!
                // Ten endpoint musi zwracać dane tak jak /all-sessions, ALE DODATKOWO
                // musi zawierać 'client_name' i 'client_id' w każdym obiekcie sesji.
                const allSessions = await fetchJSON(`${API}/api/journal/all-history`); // <--- PRZYKŁADOWY NOWY ENDPOINT
                
                // Widok "Wszyscy" prawdopodobnie nie pokazuje TUS, 
                // chyba że masz też do tego globalny endpoint
                const tusHistory = []; 

                // Przekazujemy 'true' dla widoku "wszyscy"
                renderHistory(allSessions, tusHistory, true);
            } catch (error) {
                historyContainer.innerHTML = `<div class="alert alert-danger">Wystąpił błąd ładowania historii: ${error.message}</div>`;
            }
        }
    }

    function truncateText(text, maxLength = 100) {
        if (!text) return '-';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    /**
 * Renderuje historię sesji na stronie.
 * @param {Array} allSessions - Tablica sesji indywidualnych i wpisów dziennika.
 * @param {Array} tusHistory - Tablica sesji grupowych TUS.
 * @param {boolean} isAllClientsView - Flaga określająca, czy renderować widok dla wszystkich klientów.
 */
function renderHistory(allSessions, tusHistory, isAllClientsView = false) {

    const individualAndJournalSessions = allSessions.filter(s => s.source_type !== 'tus');

    // Definicja nagłówka kolumny klienta
    const clientColumnHeader = isAllClientsView ? '<th style="width: 15%;">Klient</th>' : '';
    
    let html = `
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="mb-0"><i class="bi bi-calendar-check"></i> 
                    ${isAllClientsView ? 'Historia wszystkich klientów' : 'Wszystkie Sesje Indywidualne i Wpisy Dziennika'}
                </h5>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-light">
                            <tr>
                                <th style="width: 15%;">Data i Godzina</th>
                                ${clientColumnHeader}
                                <th style="width: 15%;">Typ / Terapeuta</th>
                                <th style="width: 20%;">Temat</th>
                                <th style="width: 25%;">Notatki</th>
                                <th style="width: 10%;">Akcje</th>
                            </tr>
                        </thead>
                        <tbody>`;

    if (individualAndJournalSessions && individualAndJournalSessions.length > 0) {
        individualAndJournalSessions.forEach(session => {
            // Ujednolicone pola
            const date = session.starts_at;
            const notes = session.notes || '';
            const truncatedNotes = truncateText(notes, 80);
            const isJournal = session.source_type === 'journal';

            const typeLabel = isJournal ?
                `<span class="badge bg-info text-dark">Dziennik</span>` :
                `<span class="badge bg-secondary">Indywidualna</span>`;

            const topic = session.topic_or_temat || 'Bez tematu';
            const therapist = session.therapist_name || 'Nieznany';
            
            // Definicja komórki klienta (wymaga, aby API zwracało client_name w widoku globalnym)
            const clientCell = isAllClientsView ? 
                `<td><strong>${session.client_name || 'Brak'}</strong></td>` : '';

            // Przygotowanie danych do modalu
            const modalData = {
                date: date,
                therapist: therapist,
                topic: topic,
                notes: notes,
                place: session.place || 'N/A',
                duration: session.duration_minutes || 60,
                note_id: session.note_id || null,
                source_type: session.source_type,
                source_id: session.source_id 
            };

            html += `
                <tr>
                    <td>${new Date(date).toLocaleString('pl-PL', {
                        year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
                    })}</td>
                    ${clientCell}
                    <td>${typeLabel}<br><span class="small">${therapist}</span></td>
                    <td><strong>${topic}</strong></td>
                    <td>
                        ${notes ? `<div class="text-muted small">${truncatedNotes}</div>` : '<span class="text-muted fst-italic">Brak notatek</span>'}
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary"
                            data-session='${JSON.stringify(modalData).replace(/'/g, "&apos;")}'
                            onclick="showSessionDetails(this)">
                            <i class="bi bi-eye"></i>
                        </button>
                    </td>
                </tr>
            `;
        });
    } else {
        // Używamy dynamicznego colspan w zależności od widoku
        html += `<tr><td colspan="${isAllClientsView ? 6 : 5}" class="text-center text-muted">Brak wpisów w historii.</td></tr>`;
    }
    html += `</tbody></table></div></div></div>`;

    // Sekcja spotkań TUS (renderuj tylko w widoku pojedynczego klienta)
    if (!isAllClientsView) {
        html += `
            <div class="card">
                <div class="card-header bg-success text-white">
                    <h5 class="mb-0"><i class="bi bi-star"></i> Sesje Grupowe TUS</h5>
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

        if (tusHistory && tusHistory.length > 0) {
            tusHistory.forEach(session => {
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
    }

    historyContainer.innerHTML = html;
}

    clientSelector.addEventListener('change', loadClientHistory);
    searchInput.addEventListener('input', () => {
        renderClientOptions(searchInput.value);
    });

    initializeClientSelector();
    loadClientHistory();
});
    // =========================================================================
    // === FUNKCJE MODALA (Przeniesione do globalnego scope) ===
    // =========================================================================

    // Funkcja do wyświetlenia pełnych szczegółów sesji w modalu
    function showSessionDetails(button) {
        const sessionData = button.getAttribute('data-session');
        const session = JSON.parse(sessionData);
        const clientId = document.getElementById('clientSelector').value;
        const isJournal = session.source_type === 'journal';

        const modalHTML = `
            <div class="modal fade" id="sessionDetailsModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">
                                📋 Szczegóły ${isJournal ? 'Wpisu Dziennika' : 'Sesji Indywidualnej'}
                            </h5>
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
                            ${session.place && !isJournal ? `
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

                            <div id="viewMode">
                                <div class="mb-3">
                                    <strong>📄 Notatki / Cele:</strong>
                                    <div class="border rounded p-3 bg-light">
                                        <pre style="white-space: pre-wrap; font-family: inherit; margin: 0;">${session.notes || 'Brak notatek'}</pre>
                                    </div>
                                </div>
                            </div>

                            <div id="editMode" style="display: none;">
                                <div class="mb-3">
                                    <label class="form-label">
                                        <strong>📄 Edytuj Notatki ${isJournal ? '(z tabeli dziennik)' : ''}:</strong>
                                    </label>
                                    <textarea id="editNoteContent" class="form-control" rows="8" style="font-family: inherit;">${session.notes || ''}</textarea>
                                </div>
                            </div>
                        </div>

                        <div class="modal-footer" id="viewModeButtons">
                            <button type="button" class="btn btn-primary" onclick="toggleEditMode(true)">
                                ✏️ Edytuj
                            </button>
                            <button type="button" class="btn btn-secondary" onclick="window.print()">
                                🖨️ Drukuj
                            </button>
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Zamknij</button>
                        </div>

                        <div class="modal-footer" id="editModeButtons" style="display: none;">
                            <button type="button" class="btn btn-success"
                                onclick="saveNoteEdit(
                                    ${clientId},
                                    '${session.date}',
                                    '${session.note_id || ''}',
                                    '${isJournal ? session.source_id : ''}',
                                    '${session.source_type}'
                                )">
                                💾 Zapisz
                            </button>
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
    async function saveNoteEdit(clientId, sessionDate, noteId, journalId, sourceType) {
        const newContent = document.getElementById('editNoteContent').value.trim();
        const alertBox = document.getElementById('alertBox');

        if (!newContent) {
            alert('Notatka nie może być pusta!');
            return;
        }

        const saveBtn = document.querySelector('#editModeButtons .btn-success');
        saveBtn.disabled = true;
        saveBtn.textContent = '⏳ Zapisywanie...';

        try {
            let response;

            // --- LOGIKA ZAPISU DLA RÓŻNYCH ŹRÓDEŁ DANYCH ---
            if (sourceType === 'journal') {
                // Zapisz do tabeli 'dziennik' (aktualizujemy pole 'cele')
                response = await fetch(`http://localhost:5000/api/journal/${journalId}`, {
                    method: 'PUT', // Lub PATCH
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cele: newContent // Zapisujemy nową treść w polu 'cele'
                    })
                });
            } else {
                // Zapisz do tabeli 'client_notes' (dla standardowych sesji)
                if (noteId) {
                    // Aktualizuj istniejącą notatkę
                    response = await fetch(`http://localhost:5000/api/clients/${clientId}/notes/${noteId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            content: newContent,
                            category: 'session'
                        })
                    });
                } else {
                    // Utwórz nową notatkę (na podstawie daty sesji)
                    const datePart = new Date(sessionDate).toISOString().split('T')[0];
                    response = await fetch(`http://localhost:5000/api/clients/${clientId}/notes`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            content: newContent,
                            category: 'session',
                            created_by_name: 'System',
                            created_at: datePart // API mapuje to do DATE(created_at)
                        })
                    });
                }
            }
            // --- KONIEC LOGIKI ZAPISU ---

            if (!response.ok) {
                const error = await response.json().catch(() => ({ error: `Błąd serwera: ${response.status}` }));
                throw new Error(error.error || 'Błąd zapisu');
            }

            // Zamknij modal
            bootstrap.Modal.getInstance(document.getElementById('sessionDetailsModal')).hide();

            // Odśwież listę
            const clientSelector = document.getElementById('clientSelector');
            if (clientSelector && clientSelector.value) {
                loadClientHistory();
            }

            // Pokaż komunikat sukcesu
            showAlert('✅ Notatka została zapisana!', 'success');

        } catch (error) {
            console.error('Błąd zapisu notatki:', error);
            showAlert('❌ Nie udało się zapisać notatki: ' + error.message, 'danger');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = '💾 Zapisz';
        }
    }

    // Globalnie dostępne funkcje
    window.showSessionDetails = showSessionDetails;
    window.toggleEditMode = toggleEditMode;

    window.saveNoteEdit = saveNoteEdit;


