    const API_BASE_URL = window.location.origin;
    let sessions = [];
    let selectedNotes = [];
    let currentSessionIndex = null;
    let editMode = false;

    // PRZENIEŚ WSZYSTKIE FUNKCJE NA ZEWNĄTRZ window.onload
    function toggleNoteSelection(index) {
        const sessionItem = document.getElementById(`session-${index}`);
        const checkbox = sessionItem.querySelector('.session-checkbox');

        if (checkbox.checked) {
            sessionItem.classList.add('selected');
            if (!selectedNotes.includes(index)) {
                selectedNotes.push(index);
            }
        } else {
            sessionItem.classList.remove('selected');
            selectedNotes = selectedNotes.filter(i => i !== index);
        }

        safeUpdateDeleteButton();
    }

    function safeUpdateDeleteButton() {
        const deleteBtn = document.getElementById('deleteBtn');
        const selectedCount = document.getElementById('selectedCount');

        if (selectedCount) {
            selectedCount.textContent = selectedNotes.length;
        }

        if (deleteBtn) {
            deleteBtn.disabled = selectedNotes.length === 0;

            if (selectedNotes.length > 0) {
                deleteBtn.innerHTML = `🗑️ Usuń zaznaczone sesji (${selectedNotes.length})`;
            } else {
                deleteBtn.innerHTML = `🗑️ Usuń zaznaczone sesji (0)`;
            }
        }
    }

    function updateDeleteButton() {
        safeUpdateDeleteButton();
    }

    async function deleteSelectedNotes() {
        if (selectedNotes.length === 0) return;
    
        const clientId = document.getElementById('clientId').value;
        if (!clientId) {
            showError('Wybierz klienta!');
            return;
        }
    
        const confirmDelete = confirm(`Czy na pewno chcesz usunąć ${selectedNotes.length} zaznaczonych sesji?`);
        if (!confirmDelete) return;
    
        const deleteBtn = document.getElementById('deleteBtn');
        deleteBtn.disabled = true;
        deleteBtn.textContent = '⏳ Usuwanie...';
    
        try {
            const sortedIndices = [...selectedNotes].sort((a, b) => b - a);
            let deletedCount = 0;
            let errors = [];
    
            for (const index of sortedIndices) {
                const session = sessions[index];
                if (!session) continue;
    
                console.log(`🗑️ Usuwanie sesji ID: ${session.id}`);
    
                try {
                    const response = await fetch(`${API_BASE_URL}/api/schedule/${session.id}`, {
                        method: 'DELETE'
                    });
    
                    if (response.ok) {
                        console.log(`✅ Usunięto sesję ${session.id}`);
                        deletedCount++;
                    } else {
                        const errorText = await response.text();
                        console.error(`❌ Błąd usuwania: ${errorText}`);
                        errors.push(`Sesja z ${formatDateTime(session.starts_at)} - ${response.status}`);
                    }
                } catch (error) {
                    console.error(`❌ Błąd: ${error}`);
                    errors.push(`Sesja z ${formatDateTime(session.starts_at)} - ${error.message}`);
                }
            }
    
            await loadClientSessions();
    
            if (errors.length > 0) {
                showError(`Usunięto ${deletedCount} sesji, błędy: ${errors.length}`);
            } else {
                showSuccess(`Usunięto ${deletedCount} sesji`);
            }
    
        } catch (error) {
            console.error('❌ Błąd:', error);
            showError('Nie udało się usunąć sesji: ' + error.message);
        } finally {
            safeUpdateDeleteButton();
        }
    }

    function viewNote(index) {
        const session = sessions[index];
        if (!session) return;

        currentSessionIndex = index;
        editMode = false;

        const clientSelect = document.getElementById('clientId');
        const selectedOption = clientSelect.options[clientSelect.selectedIndex];
        const clientName = selectedOption.dataset.fullName || selectedOption.text;

        document.getElementById('modalClientName').textContent = clientName;
        document.getElementById('modalSessionDate').textContent = formatDateTime(session.starts_at);
        document.getElementById('modalTherapist').textContent = session.therapist_name || 'Nieznany';
        document.getElementById('modalPlace').textContent = session.place_to || 'Nie podano';
        document.getElementById('modalTopic').textContent = session.label || 'Bez tematu';
        document.getElementById('modalNoteContent').textContent = session.notes || 'Brak notatek';

        document.getElementById('printDate').textContent = new Date().toLocaleDateString('pl-PL');

        document.getElementById('viewMode').style.display = 'block';
        document.getElementById('editMode').style.display = 'none';
        document.getElementById('viewModeActions').style.display = 'flex';
        document.getElementById('editModeActions').style.display = 'none';

        const modal = document.getElementById('noteModal');
        modal.classList.add('show');

        modal.onclick = function(event) {
            if (event.target === modal) closeNoteModal();
        };
    }

    function enableEditMode() {
        const session = sessions[currentSessionIndex];
        if (!session) return;

        console.log('🔧 Przełączam na tryb edycji...');
        editMode = true;

        document.getElementById('editNoteContent').value = session.notes || '';

        document.getElementById('viewMode').style.display = 'none';
        document.getElementById('editMode').style.display = 'block';

        document.getElementById('viewModeActions').style.display = 'none';
        document.getElementById('editModeActions').style.display = 'flex';

        document.getElementById('editNoteContent').focus();
    }

    function cancelEdit() {
        console.log('❌ Anulowanie edycji...');
        editMode = false;

        document.getElementById('viewMode').style.display = 'block';
        document.getElementById('editMode').style.display = 'none';

        document.getElementById('viewModeActions').style.display = 'flex';
        document.getElementById('editModeActions').style.display = 'none';
    }

    async function saveNoteEdit() {
        const session = sessions[currentSessionIndex];
        if (!session) {
            console.error('❌ Brak sesji!');
            return;
        }

        const newContent = document.getElementById('editNoteContent').value.trim();
        const clientId = document.getElementById('clientId').value;

        console.log('💾 Zapisywanie notatki...');
        console.log('  - Client ID:', clientId);
        console.log('  - Session ID:', session.id);
        console.log('  - Note ID:', session.note_id);
        console.log('  - Treść:', newContent.substring(0, 50) + '...');

        if (!newContent) {
            alert('Notatka nie może być pusta!');
            return;
        }

        const saveBtn = document.getElementById('btnSaveEdit');
        saveBtn.disabled = true;
        saveBtn.textContent = '⏳ Zapisywanie...';

        try {
            if (session.note_id) {
                console.log('📝 Aktualizacja istniejącej notatki:', session.note_id);

                const response = await fetch(`${API_BASE_URL}/api/clients/${clientId}/notes/${session.note_id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: newContent,
                        category: 'session'
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || 'Błąd aktualizacji notatki');
                }

                console.log('✅ Notatka zaktualizowana');
            } else {
                console.log('📝 Tworzenie nowej notatki dla sesji');

                const response = await fetch(`${API_BASE_URL}/api/clients/${clientId}/notes`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: newContent,
                        category: 'session',
                        created_by_name: 'System',
                        created_at: session.starts_at
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || 'Błąd tworzenia notatki');
                }

                const result = await response.json();
                session.note_id = result.id;
                console.log('✅ Notatka utworzona, ID:', result.id);
            }

            session.notes = newContent;
            document.getElementById('modalNoteContent').textContent = newContent;
            renderSessions();
            cancelEdit();
            alert('✅ Notatka została zapisana!');

        } catch (error) {
            console.error('❌ Błąd zapisu:', error);
            alert('Nie udało się zapisać notatki:\n' + error.message);
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = '💾 Zapisz zmiany';
        }
    }

    function closeNoteModal() {
        const modal = document.getElementById('noteModal');
        modal.classList.remove('show');

        currentSessionIndex = null;
        editMode = false;

        document.getElementById('viewMode').style.display = 'block';
        document.getElementById('editMode').style.display = 'none';
        document.getElementById('viewModeActions').style.display = 'flex';
        document.getElementById('editModeActions').style.display = 'none';
    }

    function printNote() {
        if (editMode) {
            console.log('⚠️ Anulowanie edycji przed drukowaniem...');
            cancelEdit();
        }

        console.log('🖨️ Drukowanie notatki...');
        window.print();
    }

    function formatDateTime(isoString) {
        if (!isoString) return 'Brak daty';
        const date = new Date(isoString);
        return date.toLocaleDateString('pl-PL') + ' ' + date.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
    }

    function showSuccess(message = 'Sesja została pomyślnie zapisana!') {
        const alert = document.getElementById('successAlert');
        alert.textContent = `✅ ${message}`;
        alert.classList.add('show');
        setTimeout(() => alert.classList.remove('show'), 5000);
    }

    function showError(message) {
        const alert = document.getElementById('errorAlert');
        document.getElementById('errorMessage').textContent = message;
        alert.classList.add('show');
        setTimeout(() => alert.classList.remove('show'), 8000);
    }

    // POZOSTAŁE FUNKCJE (loadClients, loadTherapists, loadClientSessions, renderSessions, saveSession, itp.)
    // mogą pozostać wewnątrz window.onload lub też zostać przeniesione na zewnątrz

    window.onload = function() {
        loadClients();
        loadTherapists();
        setDefaultDateTime();
        setDefaultMonth();

        function setDefaultMonth() {
            const now = new Date();
            const monthStr = now.toISOString().slice(0, 7);
            document.getElementById('monthSelector').value = monthStr;
        }

        function setDefaultDateTime() {
            const now = new Date();
            const dateStr = now.toISOString().split('T')[0];
            const timeStr = now.toTimeString().slice(0, 5);
            document.getElementById('sessionDate').value = dateStr;
            document.getElementById('sessionTime').value = timeStr;
        }

        async function loadClients() {
            try {
                console.log('🔄 Ładowanie klientów...');
                const response = await fetch(API_BASE_URL + '/api/clients');

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const clients = await response.json();
                console.log('✅ Otrzymano klientów:', clients.length);

                const select = document.getElementById('clientId');
                select.innerHTML = '<option value="">Wybierz klienta</option>';

                clients.forEach(client => {
                    const isActive = client.active === undefined || client.active === true;

                    if (isActive) {
                        const clientId = client.client_id || client.id;
                        const clientName = client.full_name || `${client.first_name} ${client.last_name}` || 'Bez nazwy';

                        const option = document.createElement('option');
                        option.value = clientId;
                        option.textContent = clientName;
                        option.dataset.fullName = clientName;
                        select.appendChild(option);
                    }
                });

                // Event listener - automatyczne ładowanie sesji
                select.addEventListener('change', function() {
                    const selectedOption = this.options[this.selectedIndex];
                    const clientName = selectedOption.dataset.fullName || selectedOption.text;

                    if (this.value) {
                        document.getElementById('clientInfoBox').style.display = 'block';
                        document.getElementById('selectedClientName').textContent = clientName;
                        console.log('📡 Ładuję sesje dla:', clientName);
                        loadClientSessions();
                    } else {
                        document.getElementById('clientInfoBox').style.display = 'none';
                        document.getElementById('sessionsList').innerHTML = '<div class="empty-state" style="padding: 80px 20px;"><div style="font-size: 48px; margin-bottom: 15px;">👈</div><div style="font-size: 16px; color: #666;">Wybierz klienta w formularzu po lewej stronie,<br>aby zobaczyć jego sesje i notatki.</div></div>';
                    }
                });

            } catch (error) {
                console.error('❌ Błąd ładowania klientów:', error);
                showError('Nie udało się załadować listy klientów');
            }
        }

        async function loadTherapists() {
            try {
                const response = await fetch(API_BASE_URL + '/api/therapists');
                const therapists = await response.json();

                const select = document.getElementById('therapistId');
                select.innerHTML = '<option value="">Wybierz terapeutę</option>';

                therapists.forEach(therapist => {
                    const option = document.createElement('option');
                    option.value = therapist.id;
                    option.textContent = therapist.full_name + (therapist.specialization ? ' - ' + therapist.specialization : '');
                    select.appendChild(option);
                });
            } catch (error) {
                console.error('Błąd ładowania terapeutów:', error);
                showError('Nie udało się załadować listy terapeutów');
            }
        }

        async function loadClientSessions() {
            const clientId = document.getElementById('clientId').value;
            const month = document.getElementById('monthSelector').value;
            const list = document.getElementById('sessionsList');
            const loading = document.getElementById('loadingIndicator');

            console.log('🔍 loadClientSessions - clientId:', clientId);

            if (!clientId) {
                list.innerHTML = '<div class="empty-state" style="padding: 80px 20px;"><div style="font-size: 48px; margin-bottom: 15px;">👈</div><div style="font-size: 16px; color: #666;">Wybierz klienta w formularzu po lewej stronie,<br>aby zobaczyć jego sesje i notatki.</div></div>';
                return;
            }

            loading.style.display = 'block';
            list.innerHTML = '';
            sessions = [];
            selectedNotes = [];

            // Bezpieczna aktualizacja przycisku
            safeUpdateDeleteButton();

            try {
                const url = `${API_BASE_URL}/api/clients/${clientId}/sessions?month=${month}`;
                console.log('📡 Pobieranie:', url);

                const response = await fetch(url);
                console.log('Status:', response.status);

                if (response.status === 404) {
                    throw new Error('Backend nie ma endpointu /clients/{id}/sessions');
                }

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || response.statusText);
                }

                const data = await response.json();
                sessions = data;
                console.log('✅ Pobrano sesji:', sessions.length);

                renderSessions();

            } catch (error) {
                console.error('❌ Błąd:', error);
                list.innerHTML = `<div class="empty-state">❌ ${error.message}<br><br><em>Sprawdź konsolę (F12)</em></div>`;
            } finally {
                loading.style.display = 'none';
            }
        }

        function renderSessions() {
            const list = document.getElementById('sessionsList');

            if (sessions.length === 0) {
                list.innerHTML = '<div class="empty-state">Brak sesji w wybranym miesiącu.</div>';
                return;
            }

            list.innerHTML = sessions.map((session, index) => `
                <div class="session-item" id="session-${index}">
                    <input type="checkbox" class="session-checkbox" onchange="toggleNoteSelection(${index})">
                    <div class="session-header">
                        <div class="session-title">${session.label || 'Sesja terapeutyczna'}</div>
                        <div class="session-date">${formatDateTime(session.starts_at)}</div>
                    </div>
                    <div class="session-info">
                        <strong>Terapeuta:</strong> ${session.therapist_name || 'Nieznany'}
                    </div>
                    <div class="session-info">
                        <strong>Czas trwania:</strong> ${session.duration_minutes || 60} min
                    </div>
                    ${session.place_to ? `<div class="session-info"><strong>Miejsce:</strong> ${session.place_to}</div>` : ''}
                    ${session.notes ? `
                        <div class="session-notes">
                            <strong>Notatki:</strong>
                            <div class="notes-preview">${session.notes.substring(0, 100)}${session.notes.length > 100 ? '...' : ''}</div>
                            <button class="expand-btn" onclick="viewNote(${index})">📋 Zobacz pełną notatkę</button>
                        </div>
                    ` : '<div class="session-info" style="color: #999;">Brak notatek</div>'}
                </div>
            `).join('');
        }

         async function saveSession() {
                const btn = document.getElementById('saveBtn');
                const clientId = document.getElementById('clientId').value;
                const therapistId = document.getElementById('therapistId').value;
                const sessionDate = document.getElementById('sessionDate').value;
                const sessionTime = document.getElementById('sessionTime').value;
                const duration = parseInt(document.getElementById('duration').value);
                const place = document.getElementById('place').value;
                const topic = document.getElementById('topic').value;
                const notes = document.getElementById('notes').value;
    
                if (!clientId || !therapistId || !sessionDate || !sessionTime || !place || !topic) {
                    showError('Proszę wypełnić wszystkie wymagane pola!');
                    return;
                }
    
                btn.disabled = true;
                btn.textContent = '⏳ Zapisywanie...';
    
                try {
                    const startsAt = `${sessionDate}T${sessionTime}:00`;
                    const [startHour, startMinute] = sessionTime.split(':').map(Number);
                    const totalMinutes = startHour * 60 + startMinute + duration;
                    const endHour = Math.floor(totalMinutes / 60);
                    const endMinute = totalMinutes % 60;
                    const endsAt = `${sessionDate}T${String(endHour).padStart(2, '0')}:${String(endMinute).padStart(2, '0')}:00`;
    
                    const response = await fetch(API_BASE_URL + '/api/schedule/group', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            client_id: parseInt(clientId),
                            label: topic,
                            notes: notes || undefined,
                            therapy: {
                                therapist_id: parseInt(therapistId),
                                starts_at: startsAt,
                                ends_at: endsAt,
                                place: place,
                                notes: notes || undefined
                            },
                            status: 'planned'
                        })
                    });
    
                    const result = await response.json();
    
                    if (!response.ok) {
                        if (response.status === 409) {
                            throw new Error('Konflikt czasowy - terapeuta ma już zajęty ten czas. Wybierz inną godzinę.');
                        }
                        throw new Error(result.error || result.message || 'Błąd zapisu sesji');
                    }
    
                    console.log('✅ Sesja zapisana');
                    showSuccess();
                    clearForm();
    
                    // Jeśli są notatki, zapisz je do client_notes
                    if (notes && notes.trim()) {
                        try {
                            console.log('📝 Zapisuję notatki do client_notes...');
                            const notesResponse = await fetch(`${API_BASE_URL}/api/clients/${clientId}/notes`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    content: notes.trim(),
                                    category: 'session',
                                    created_by_name: 'System',
                                    created_at: startsAt
                                })
                            });
    
                            if (notesResponse.ok) {
                                console.log('✅ Notatki zapisane do client_notes');
                            } else {
                                console.warn('⚠️ Nie udało się zapisać notatek do client_notes');
                            }
                        } catch (noteError) {
                            console.error('❌ Błąd zapisu notatek:', noteError);
                        }
                    }
    
                    await loadClientSessions();
    
                } catch (error) {
                    console.error('❌ Błąd:', error);
                    showError(error.message);
                } finally {
                    btn.disabled = false;
                    btn.textContent = '💾 Zapisz Sesję';
                }
            }

        function clearForm() {
            document.getElementById('topic').value = '';
            document.getElementById('notes').value = '';
            document.getElementById('duration').value = '60';
            document.getElementById('place').value = 'Poradnia';
            setDefaultDateTime();
        }
		//tu koniec
    };

    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') closeNoteModal();
    });
