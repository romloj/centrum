document.addEventListener('DOMContentLoaded', () => {
    const API = window.location.origin;
    const clientSelector = document.getElementById('clientSelector');
    const historyContainer = document.getElementById('historyContainer');
    const alertBox = document.getElementById('alertBox');
    const searchInput = document.getElementById('searchInput');
    const monthSelector = document.getElementById('monthSelector');
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

    async function loadClientHistory() {
        const clientId = clientSelector.value;
        const month = monthSelector.value;
        currentClientId = clientId; 

        if (!clientId) {
            historyContainer.innerHTML = '<p class="text-center text-muted p-3">Wybierz klienta, aby zobaczyć jego historię.</p>';
            return;
        }

        historyContainer.innerHTML = '<p class="text-center text-muted p-3">Ładowanie historii...</p>';
        try {
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

    function renderHistory(allSessions, tusHistory) {
        const individualAndJournalSessions = allSessions.filter(s => s.source_type !== 'tus');

        let html = `
            <div class="card mb-3">
                <div class="card-header bg-primary text-white py-2">
                    <h5 class="mb-0" style="font-size: 1.1rem;"><i class="bi bi-calendar-check"></i> Wszystkie Sesje Indywidualne i Wpisy Dziennika</h5>
                </div>
                <div class="card-body p-2">
                  <div class="table-responsive" style="max-height: 300px; overflow-y: auto;">
                   
                        <table class="table table-striped table-hover table-sm">
                            <thead class="table-light">
                                <tr>
                                    <th style="width:15%">Data i Godzina</th>
                                    <th style="width:15%">Typ / Terapeuta</th>
                                    <th style="width:25%">Temat</th>
                                    <th style="width:45%" >Notatki</th>
                                    <th style="width:5%">Akcje</th>
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
                    `<span class="badge bg-info text-dark" style="font-size: 0.7rem;">Dziennik</span>` :
                    `<span class="badge bg-secondary" style="font-size: 0.7rem;">Indywidualna</span>`;
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
                    source_id: session.source_id
                };

                html += `
                    <tr>
                        <td style="font-size: 0.85rem;">${new Date(date).toLocaleString('pl-PL', {
                            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
                        })}</td>
                        <td style="font-size: 0.85rem;">${typeLabel}<br><span class="small">${therapist}</span></td>
                        <td style="font-size: 0.85rem;"><strong>${topic}</strong></td>
                        <td style="font-size: 0.85rem;">
                            ${notes ? `<div class="text-muted small">${truncatedNotes}</div>` : '<span class="text-muted fst-italic">Brak notatek</span>'}
                        </td>
                        <td>
                            <button class="btn btn-sm btn-outline-primary py-1 px-2"
                                data-session='${JSON.stringify(modalData).replace(/'/g, "&apos;")}'
                                onclick="showSessionDetails(this)"
                                style="font-size: 0.75rem; min-width: 40px;">
                                <i class="bi bi-eye"></i>
                            </button>
                        </td>
                    </tr>
                `;
            });
        } else {
            html += '<tr><td colspan="5" class="text-center text-muted" style="font-size: 0.85rem;">Brak wpisów w historii indywidualnej lub dzienniku (dla wybranego miesiąca).</td></tr>';
        }
        html += `</tbody></table></div></div></div>`;

        // Sekcja TUS
        html += `
            <div class="card">
                <div class="card-header bg-success text-white py-2">
                    <h5 class="mb-0" style="font-size: 1.1rem;"><i class="bi bi-star"></i> Sesje Grupowe TUS</h5>
                </div>
                <div class="card-body p-2">
                    <div class="table-responsive">
                        <table class="table table-striped table-hover table-sm">
                            <thead class="table-light">
                                <tr>
                                    <th style="font-size: 0.85rem;">Data i Godzina</th>
                                    <th style="font-size: 0.85rem;">Grupa</th>
                                    <th style="font-size: 0.85rem;">Zrealizowany Temat</th>
                                </tr>
                            </thead>
                            <tbody>`;

        if (tusHistory && tusHistory.length > 0) {
            tusHistory.forEach(session => {
                const sessionTime = session.time ? ` ${session.time}` : '';
                html += `
                    <tr>
                        <td style="font-size: 0.85rem;">${new Date(session.date).toLocaleDateString('pl-PL')}${sessionTime}</td>
                        <td style="font-size: 0.85rem;">${session.group}</td>
                        <td style="font-size: 0.85rem;">${session.topic}</td>
                    </tr>
                `;
            });
        } else {
            html += '<tr><td colspan="3" class="text-center text-muted" style="font-size: 0.85rem;">Brak sesji TUS w historii (dla wybranego miesiąca).</td></tr>';
        }
        html += `</tbody></table></div></div></div>`;

        historyContainer.innerHTML = html;
    }

    function setDefaultMonth() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        monthSelector.value = `${year}-${month}`;
    }

    clientSelector.addEventListener('change', loadClientHistory);
    searchInput.addEventListener('input', () => {
        renderClientOptions(searchInput.value);
    });
    monthSelector.addEventListener('change', loadClientHistory);

    setDefaultMonth(); 
    initializeClientSelector();
    loadClientHistory();
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
                        <div class="modal-header py-2">
                            <h5 class="modal-title" style="font-size: 1.1rem;">
                                📋 Szczegóły ${isJournal ? 'Wpisu Dziennika' : 'Sesji Indywidualnej'}
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body py-2">
                            <div class="mb-2">
                                <strong>📅 Data i godzina:</strong>
                                <p class="mb-1" style="font-size: 0.9rem;">${new Date(session.date).toLocaleString('pl-PL')}</p>
                            </div>
                            <div class="mb-2">
                                <strong>👨‍⚕️ Terapeuta:</strong>
                                <p class="mb-1" style="font-size: 0.9rem;">${session.therapist || '-'}</p>
                            </div>
                            <div class="mb-2">
                                <strong>📝 Temat:</strong>
                                <p class="mb-1" style="font-size: 0.9rem;">${session.topic || 'Bez tematu'}</p>
                            </div>
                            ${session.place && !isJournal ? `
                            <div class="mb-2">
                                <strong>📍 Miejsce:</strong>
                                <p class="mb-1" style="font-size: 0.9rem;">${session.place}</p>
                            </div>
                            ` : ''}
                            ${session.duration ? `
                            <div class="mb-2">
                                <strong>⏱️ Czas trwania:</strong>
                                <p class="mb-1" style="font-size: 0.9rem;">${session.duration} min</p>
                            </div>
                            ` : ''}

                            <div id="viewMode">
                                <div class="mb-2">
                                    <strong>📄 Notatki / Cele:</strong>
                                    <div class="border rounded p-2 bg-light mt-1">
                                        <pre style="white-space: pre-wrap; font-family: inherit; margin: 0; font-size: 0.9rem;">${session.notes || 'Brak notatek'}</pre>
                                    </div>
                                </div>
                            </div>

                            <div id="editMode" style="display: none;">
                                <div class="mb-2">
                                    <label class="form-label">
                                        <strong>📄 Edytuj Notatki ${isJournal ? '(z tabeli dziennik)' : ''}:</strong>
                                    </label>
                                    <textarea id="editNoteContent" class="form-control" rows="6" style="font-family: inherit; font-size: 0.9rem;">${session.notes || ''}</textarea>
                                </div>
                            </div>
                        </div>

                        <div class="modal-footer py-2" id="viewModeButtons">
                            <button type="button" class="btn btn-primary btn-sm" onclick="toggleEditMode(true)">
                                ✏️ Edytuj
                            </button>
                            <button type="button" class="btn btn-secondary btn-sm" onclick="window.print()">
                                🖨️ Drukuj
                            </button>
                            <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Zamknij</button>
                        </div>

                        <div class="modal-footer py-2" id="editModeButtons" style="display: none;">
                            <button type="button" class="btn btn-success btn-sm"
                                onclick="saveNoteEdit(
                                    '${clientId}',
                                    '${session.date}',
                                    '${session.note_id || ''}',
                                    '${isJournal ? session.source_id : ''}',
                                    '${session.source_type}'
                                )">
                                💾 Zapisz
                            </button>
                            <button type="button" class="btn btn-secondary btn-sm" onclick="toggleEditMode(false)">Anuluj</button>
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
        
        const API = window.location.origin;

        try {
            let response;

            if (sourceType === 'journal') {
                response = await fetch(`${API}/api/journal/${journalId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cele: newContent 
                    })
                });
            } else {
                if (noteId && noteId !== 'null') {
                    response = await fetch(`${API}/api/clients/${clientId}/notes/${noteId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            content: newContent,
                            category: 'session'
                        })
                    });
                } else {
                    const datePart = new Date(sessionDate).toISOString().split('T')[0];
                    response = await fetch(`${API}/api/clients/${clientId}/notes`, {
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

    window.showSessionDetails = showSessionDetails;
    window.toggleEditMode = toggleEditMode;
    window.saveNoteEdit = saveNoteEdit;
