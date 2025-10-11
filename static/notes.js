import React, { useState } from 'react';
import { Calendar, Users, FileText, Save, CheckCircle } from 'lucide-react';

export default function TherapySessionManager() {
  // Przykładowe dane - w prawdziwej aplikacji pochodziłyby z bazy danych
  const [clients] = useState([
    { id: 1, name: 'Anna Kowalska', age: 32 },
    { id: 2, name: 'Jan Nowak', age: 45 },
    { id: 3, name: 'Maria Wiśniewska', age: 28 },
    { id: 4, name: 'Piotr Zieliński', age: 38 }
  ]);

  const [therapists] = useState([
    { id: 1, name: 'Dr Katarzyna Lewandowska', specialization: 'Psychoterapia poznawczo-behawioralna' },
    { id: 2, name: 'Dr Marcin Kamiński', specialization: 'Psychoterapia psychodynamiczna' },
    { id: 3, name: 'Dr Agnieszka Wójcik', specialization: 'Terapia rodzin' }
  ]);

  const [sessions, setSessions] = useState([]);
  const [showSuccess, setShowSuccess] = useState(false);

  // Dane formularza
  const [formData, setFormData] = useState({
    clientId: '',
    therapistId: '',
    date: '',
    time: '',
    topic: '',
    notes: ''
  });

  const handleSubmit = () => {
    // Walidacja
    if (!formData.clientId || !formData.therapistId || !formData.date ||
        !formData.time || !formData.topic || !formData.notes) {
      alert('Proszę wypełnić wszystkie pola!');
      return;
    }

    const client = clients.find(c => c.id === parseInt(formData.clientId));
    const therapist = therapists.find(t => t.id === parseInt(formData.therapistId));

    const newSession = {
      id: Date.now(),
      client: client.name,
      therapist: therapist.name,
      date: formData.date,
      time: formData.time,
      topic: formData.topic,
      notes: formData.notes,
      createdAt: new Date().toISOString()
    };

    setSessions([newSession, ...sessions]);

    // Reset formularza
    setFormData({
      clientId: '',
      therapistId: '',
      date: '',
      time: '',
      topic: '',
      notes: ''
    });

    // Pokaż komunikat sukcesu
    setShowSuccess(true);
    setTimeout(() => setShowSuccess(false), 3000);
  };

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    });
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-4 md:p-8">
      <div className="max-w-6xl mx-auto">
        {/* Nagłówek */}
        <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
          <h1 className="text-3xl font-bold text-gray-800 flex items-center gap-3">
            <FileText className="text-indigo-600" />
            System Zarządzania Sesjami Terapeutycznymi
          </h1>
          <p className="text-gray-600 mt-2">Dokumentacja spotkań z klientami</p>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {/* Formularz */}
          <div className="bg-white rounded-lg shadow-lg p-6">
            <h2 className="text-xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <Calendar className="text-indigo-600" />
              Nowa sesja terapeutyczna
            </h2>

            <div className="space-y-4">
              {/* Wybór klienta */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Klient *
                </label>
                <select
                  name="clientId"
                  value={formData.clientId}
                  onChange={handleChange}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">Wybierz klienta</option>
                  {clients.map(client => (
                    <option key={client.id} value={client.id}>
                      {client.name} ({client.age} lat)
                    </option>
                  ))}
                </select>
              </div>

              {/* Wybór terapeuty */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Terapeuta *
                </label>
                <select
                  name="therapistId"
                  value={formData.therapistId}
                  onChange={handleChange}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">Wybierz terapeutę</option>
                  {therapists.map(therapist => (
                    <option key={therapist.id} value={therapist.id}>
                      {therapist.name} - {therapist.specialization}
                    </option>
                  ))}
                </select>
              </div>

              {/* Data i godzina */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Data *
                  </label>
                  <input
                    type="date"
                    name="date"
                    value={formData.date}
                    onChange={handleChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Godzina *
                  </label>
                  <input
                    type="time"
                    name="time"
                    value={formData.time}
                    onChange={handleChange}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              {/* Temat spotkania */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Temat spotkania *
                </label>
                <input
                  type="text"
                  name="topic"
                  value={formData.topic}
                  onChange={handleChange}
                  placeholder="np. Zarządzanie stresem w pracy"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Notatki z przebiegu */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Notatki z przebiegu spotkania *
                </label>
                <textarea
                  name="notes"
                  value={formData.notes}
                  onChange={handleChange}
                  rows={6}
                  placeholder="Wprowadź istotne informacje: przebieg sesji, obserwacje, postępy, zadania domowe..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Przycisk zapisu */}
              <button
                onClick={handleSubmit}
                className="w-full bg-indigo-600 text-white py-3 rounded-md hover:bg-indigo-700 transition-colors flex items-center justify-center gap-2 font-medium"
              >
                <Save size={20} />
                Zapisz sesję
              </button>
            </div>

            {/* Komunikat sukcesu */}
            {showSuccess && (
              <div className="mt-4 bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-md flex items-center gap-2">
                <CheckCircle size={20} />
                Sesja została pomyślnie zapisana!
              </div>
            )}
          </div>

          {/* Lista zapisanych sesji */}
          <div className="bg-white rounded-lg shadow-lg p-6">
            <h2 className="text-xl font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <Users className="text-indigo-600" />
              Ostatnie sesje ({sessions.length})
            </h2>

            <div className="space-y-4 max-h-[600px] overflow-y-auto">
              {sessions.length === 0 ? (
                <p className="text-gray-500 text-center py-8">
                  Brak zapisanych sesji. Dodaj pierwszą sesję używając formularza.
                </p>
              ) : (
                sessions.map(session => (
                  <div key={session.id} className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="font-semibold text-gray-800">{session.topic}</h3>
                      <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                        {session.date} {session.time}
                      </span>
                    </div>
                    <div className="space-y-1 text-sm">
                      <p className="text-gray-600">
                        <span className="font-medium">Klient:</span> {session.client}
                      </p>
                      <p className="text-gray-600">
                        <span className="font-medium">Terapeuta:</span> {session.therapist}
                      </p>
                      <div className="mt-2 pt-2 border-t border-gray-100">
                        <p className="font-medium text-gray-700 mb-1">Notatki:</p>
                        <p className="text-gray-600 text-sm">{session.notes}</p>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}