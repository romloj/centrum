document.addEventListener('DOMContentLoaded', () => {
    const API = window.location.origin;
    const clientSelector = document.getElementById('clientSelector');
    const historyContainer = document.getElementById('historyContainer');
    const alertBox = document.getElementById('alertBox');
    const searchInput = document.getElementById('searchInput');
    const monthSelector = document.getElementById('monthSelector'); // ZMIANA: Dodano selektor miesiąca
    let allClients = [];
    let currentClientId = null;

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
                const option = new Option(client.full_name, client.client_id || client.id);
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
            const clients = await fetchJSON(`${API}/api/clients?include_inactive=true`);
            allClients = clients.sort((a, b) => a.full_name.localeCompare(b.full_name));
            renderClientOptions();
        } catch (error) {
            showAlert(`Nie udało się załadować listy klientów: ${error.message}`, 'danger');
        }
    }

    // ZMIANA: Ta funkcja została zmodyfikowana, aby uwzględnić filtr miesiąca
    async function loadClientHistory() {
        const clientId = clientSelector.value;
        const month = monthSelector.value; // ZMIANA: Odczytaj wartość miesiąca
        currentClientId = clientId; 

        if (!clientId) {
            historyContainer.innerHTML = '<p class="text-center text-muted p-5">Wybierz klienta, aby zobaczyć jego historię.</p>';
            return;
        }

        historyContainer.innerHTML = '<p class="text-center text-muted p-5">Ładowanie historii...</p>';
        try {
            // ZMIANA: Dodaj parametr ?month=... do obu zapytań API
            const queryParams = month ? `?month=${encodeURIComponent(month)}` : '';

            const allSessions = await fetchJSON(`${API}/api/clients/${clientId}/all-sessions${queryParams}`);
            const tusHistory = await fetchJSON(`${API}/api/clients/${clientId}/history${queryParams}`).then(res => res.tus_group || []);

            renderHistory(allSessions, tusHistory);
        } catch (error) {
            historyContainer.innerHTML = `<div class="alert alert-danger">Wystąpił błąd ładowania historii: ${error.message}</div>`;
        }
    }

    function truncateText(text, maxLength = 100) {
        if (!text) return '-';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    // Funkcja renderHistory pozostaje bez zmian
    function renderHistory(allSessions, tusHistory) {
        const individualAndJournalSessions = allSessions.filter(s => s.source_type !== 'tus');

        let html = `
            <div class="card mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="bi bi-calendar-check"></i> Wszystkie Sesje Indywidualne i Wpisy Dziennika</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-striped table-hover">
                            <thead class="table-light">
                                <tr>
                                    <th style="width:15%">Data i Godzina</th>
                                    <th style="width:15%">Typ / Terapeuta</th>
                                    <th style="width:25%">Temat</th>
                                    <th style="width:35%" >Notatki</th>
                                    <th style="width:10%">Akcje</th>
                                </tr>
                            </thead>
                            <tbody>`;

        if (individualAndJournalSessions && individualAndJournalSessions.length > 0) {
            individualAndJournalSessions.forEach(session => {
                const date = session.starts_at;
                const notes = session.notes || '';
                const truncatedNotes = truncateText(notes, 80);
                const isJournal = session.source_type === 'journal';
                const typeLabel = isJournal ?
                    `<span class="badge bg-info text-dark">Dziennik</span>` :
                    `<span class="badge bg-secondary">Indywidualna</span>`;
                const topic = session.topic_or_temat || 'Bez tematu';
                const therapist = session.therapist_name || 'Nieznany';
                const detailId = `${session.source_type}_${session.source_id}`;
                const modalData = {
                    date: date,
                    therapist: therapist,
                    topic: topic,
                    notes: notes,
                    place: session.place || 'N/A',
                    duration: session.duration_minutes || 60,
                    note_id: session.note_id || null, 
                    source_type: session.source_type,
                    source_id: session.source_id // ZMIANA: Dodano source_id do modalu
                };

                html += `
                    <tr>
                        <td>${new Date(date).toLocaleString('pl-PL', {
                            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
                        })}</td>
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
            html += '<tr><td colspan="5" class="text-center text-muted">Brak wpisów w historii indywidualnej lub dzienniku (dla wybranego miesiąca).</td></tr>'; // ZMIANA: Zaktualizowano tekst
        }
        html += `</tbody></table></div></div></div>`;

        // Sekcja TUS
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
            html += '<tr><td colspan="3" class="text-center text-muted">Brak sesji TUS w historii (dla wybranego miesiąca).</td></tr>'; // ZMIANA: Zaktualizowano tekst
        }
        html += `</tbody></table></div></div></div>`;

        historyContainer.innerHTML = html;
    }

    // ZMIANA: Nowa funkcja do ustawiania domyślnego miesiąca
    function setDefaultMonth() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0'); // Miesiące są 0-indeksowane
        monthSelector.value = `${year}-${month}`;
    }

    clientSelector.addEventListener('change', loadClientHistory);
    searchInput.addEventListener('input', () => {
        renderClientOptions(searchInput.value);
    });
    // ZMIANA: Dodano listener na zmianę miesiąca
    monthSelector.addEventListener('change', loadClientHistory);

    // ZMIANA: Ustaw domyślny miesiąc przy starcie
    setDefaultMonth(); 
    initializeClientSelector();
    loadClientHistory(); // Ta linia i tak wyświetli "Wybierz klienta...", co jest OK
});

    // =========================================================================
    // === FUNKCJE MODALA (Przeniesione do globalnego scope) ===
    // =========================================================================

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
                  _             <div class="mb-3">
                                    <label class="form-label">
                                        <strong>📄 Edytuj Notatki ${isJournal ? '(z tabeli dziennik)' : ''}:</strong>
                                    </label>
                                    <textarea id="editNoteContent" class="form-control" rows="8" style="font-family: inherit;">${session.notes || ''}</textarea>
                                </div>
          _                 </div>
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
                                    '${clientId}',
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
        const oldModal = document.getElementById('sessionDetailsModal');
        if (oldModal) oldModal.remove();

        document.body.insertAdjacentHTML('beforeend', modalHTML);
        const modal = new bootstrap.Modal(document.getElementById('sessionDetailsModal'));
        modal.show();

        document.getElementById('sessionDetailsModal').addEventListener('hidden.bs.modal', function () {
            this.remove();
        });
    }

    function toggleEditMode(editMode) {
        document.getElementById('viewMode').style.display = editMode ? 'none' : 'block';
        document.getElementById('editMode').style.display = editMode ? 'block' : 'none';
        document.getElementById('viewModeButtons').style.display = editMode ? 'none' : 'flex';
        document.getElementById('editModeButtons').style.display = editMode ? 'flex' : 'none';
    }

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
        
        // ZMIANA: Użyj API, a nie zahardkodowanego localhost
        const API = window.location.origin; 

        try {
            let response;

            if (sourceType === 'journal') {
                // Zapisz do tabeli 'dziennik'
                response = await fetch(`${API}/api/journal/${journalId}`, { // ZMIANA
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cele: newContent 
                    })
                });
            } else {
                // Zapisz do tabeli 'client_notes'
                if (noteId && noteId !== 'null') { // ZMIANA: Lepsze sprawdzanie 'null'
                    // Aktualizuj istniejącą notatkę
                    response = await fetch(`${API}/api/clients/${clientId}/notes/${noteId}`, { // ZMIANA
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            content: newContent,
                            category: 'session'
                        })
                    });
                } else {
                    // Utwórz nową notatkę
                    const datePart = new Date(sessionDate).toISOString().split('T')[0];
                    response = await fetch(`${API}/api/clients/${clientId}/notes`, { // ZMIANA
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            content: newContent,
                            category: 'session',
                            created_by_name: 'System', 
                            created_at: datePart 
                        })
                    });
                }
            }
            // --- KONIEC LOGIKI ZAPISU ---

            if (!response.ok) {
                const error = await response.json().catch(() => ({ error: `Błąd serwera: ${response.status}` }));
                throw new Error(error.error || 'Błąd zapisu');
            }

            bootstrap.Modal.getInstance(document.getElementById('sessionDetailsModal')).hide();

            const clientSelector = document.getElementById('clientSelector');
            if (clientSelector && clientSelector.value) {
                loadClientHistory(); 
            }

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


