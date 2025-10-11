document.addEventListener('DOMContentLoaded', () => {
    const API_URL = "/api";
    const importDate = document.getElementById('importDate');
    const importTherapist = document.getElementById('importTherapist');
    const imageUpload = document.getElementById('imageUpload');
    const previewCard = document.getElementById('previewCard');
    const imagePreview = document.getElementById('imagePreview');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const resultsCard = document.getElementById('resultsCard');
    const resultsBody = document.getElementById('resultsBody');
    const saveBtn = document.getElementById('saveBtn');

    const showAlert = (msg, type = "danger") => {
        document.getElementById("alertBox").innerHTML = `<div class="alert alert-${type} alert-dismissible fade show">${msg}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
    };

    async function initializeSelectors() {
        try {
            const response = await fetch(`${API_URL}/therapists`);
            if (!response.ok) throw new Error('Błąd ładowania listy terapeutów.');
            const therapists = await response.json();

            importTherapist.innerHTML = '<option value="">-- Wybierz terapeutę --</option>';
            therapists.filter(t => t.active).forEach(therapist => {
                const option = new Option(therapist.full_name, therapist.full_name);
                importTherapist.add(option);
            });
        } catch (error) { showAlert(error.message, 'danger'); }
        importDate.value = new Date().toISOString().split('T')[0];
        checkIfReadyToUpload();
    }

    function checkIfReadyToUpload() {
        imageUpload.disabled = !(importDate.value && importTherapist.value);
    }

    imageUpload.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                imagePreview.src = e.target.result;
                previewCard.classList.remove('d-none');
                resultsCard.classList.add('d-none');
            };
            reader.readAsDataURL(file);
        }
    });

    analyzeBtn.addEventListener('click', async () => {
        const file = imageUpload.files[0];
        if (!file) {
            showAlert('Proszę najpierw wybrać plik z obrazem.');
            return;
        }

        const spinner = document.getElementById('analyzeSpinner');
        spinner.classList.remove('d-none');
        analyzeBtn.disabled = true;

        const formData = new FormData();
        formData.append('schedule_image', file);
        formData.append('date', importDate.value);
        formData.append('therapist_name', importTherapist.value);

        try {
            const response = await fetch(`${API_URL}/parse-schedule-image`, { method: 'POST', body: formData });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: `Błąd serwera: ${response.status}` }));
                throw new Error(errorData.error);
            }
            const data = await response.json();
            renderResults(data);
            resultsCard.classList.remove('d-none');
        } catch (error) {
            showAlert(`Analiza nie powiodła się: ${error.message}`);
        } finally {
            spinner.classList.add('d-none');
            analyzeBtn.disabled = false;
        }
    });

    function renderResults(scheduleItems) {
        if (!scheduleItems || scheduleItems.length === 0) {
            resultsBody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Nie udało się odczytać żadnych wpisów z obrazu.</td></tr>';
            return;
        }
        resultsBody.innerHTML = scheduleItems.map(item => `
            <tr>
                <td><input type="text" value="${item.date || ''}" data-field="date" readonly></td>
                <td><input type="text" value="${item.therapist_name || ''}" data-field="therapist_name" readonly></td>
                <td><input type="text" value="${item.start_time || ''}" data-field="start_time"></td>
                <td><input type="text" value="${item.end_time || ''}" data-field="end_time"></td>
                <td><input type="text" value="${item.client_name || ''}" data-field="client_name"></td>
                <td><input type="text" value="${item.type || 'indywidualne'}" data-field="type"></td>
            </tr>
        `).join('');
    }

    saveBtn.addEventListener('click', async () => {
        const spinner = document.getElementById('saveSpinner');
        spinner.classList.remove('d-none');
        saveBtn.disabled = true;

        const scheduleData = [];
        resultsBody.querySelectorAll('tr').forEach(row => {
            const item = {};
            row.querySelectorAll('input').forEach(input => {
                item[input.dataset.field] = input.value.trim();
            });
            scheduleData.push(item);
        });

        try {
            const response = await fetch(`${API_URL}/save-parsed-schedule`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(scheduleData)
            });
             if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: `Błąd serwera: ${response.status}` }));
                throw new Error(errorData.error);
            }
            const result = await response.json();
            showAlert(`Pomyślnie zapisano ${result.saved_count} z ${result.total_count} wpisów. Ewentualne błędy: ${JSON.stringify(result.errors)}`, 'success');
            resultsCard.classList.add('d-none');
            previewCard.classList.add('d-none');
            imageUpload.value = '';
        } catch (error) {
            showAlert(`Zapis nie powiódł się: ${error.message}`);
        } finally {
            spinner.classList.add('d-none');
            saveBtn.disabled = false;
        }
    });

    importDate.addEventListener('change', checkIfReadyToUpload);
    importTherapist.addEventListener('change', checkIfReadyToUpload);
    initializeSelectors();
});