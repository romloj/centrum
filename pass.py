import os
from flask import Flask, render_template, request, redirect, session, url_for

app = Flask(__name__)

# --- Konfiguracja ---
# 1. Hasło, które użytkownik musi wpisać.
#    Wczytujemy je ze zmiennej środowiskowej (tej ustawionej na Render.com)
POPRAWNE_HASLO = os.environ.get('ADMIN_PASSWORD')

# 2. Sekretny klucz dla sesji (potrzebny Flaskowi do "zapamiętania" logowania)
#    To RÓWNIEŻ powinna być zmienna środowiskowa.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'domyslny-klucz-zmien-go')

if not POPRAWNE_HASLO:
    print("="*50)
    print("BŁĄD: Nie ustawiono zmiennej środowiskowej 'ADMIN_PASSWORD'!")
    print("Aplikacja nie będzie mogła poprawnie weryfikować hasła.")
    print("="*50)

# --- Strony (Route'y) ---

@app.route('/')
def index():
    """ "Właściwa strona" (chroniona) """
    
    # Sprawdź, czy użytkownik jest "zapamiętany" w sesji
    if 'logged_in' in session and session['logged_in'] == True:
        # Jeśli tak, pokaż mu właściwą stronę
        return render_template('index.html')
    else:
        # Jeśli nie, przekieruj go do logowania
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """ Strona logowania z formularzem """
    error = None
    
    # Jeśli formularz został wysłany (metoda POST)
    if request.method == 'POST':
        # 1. Pobierz hasło wpisane w formularzu
        wpisane_haslo = request.form.get('password')
        
        # 2. Porównaj hasło wpisane z tym poprawnym
        if wpisane_haslo == POPRAWNE_HASLO:
            # Hasło poprawne!
            # Zapisujemy w sesji (w "pamięci" przeglądarki), że jest zalogowany
            session['logged_in'] = True
            # Przekierowujemy na stronę główną
            return redirect(url_for('index'))
        else:
            # Hasło niepoprawne
            error = 'Niepoprawne hasło. Spróbuj ponownie.'

    # Jeśli strona jest ładowana (metoda GET) lub hasło było błędne
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    """ Wylogowanie """
    session.pop('logged_in', None) # Usuń 'logged_in' z sesji
    return redirect(url_for('login'))

# --- Uruchomienie aplikacji ---
if __name__ == '__main__':
    # Uruchom serwer testowy
    # Na Render.com to polecenie nie jest używane (Render używa Gunicorna)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
