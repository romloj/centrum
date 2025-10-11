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

    function renderHistory(history) {
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
                        <td>${new Date(session.date).toLocaleString('pl-PL')}</td>
                        <td>${session.therapist}</td>
                        <td><span class="badge text-bg-secondary">${session.status}</span></td>
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
