import os
import functools
from flask import Blueprint, render_template, request, redirect, session, url_for, jsonify

# Utworzenie Blueprint o nazwie 'auth'
# __name__ pomaga Flaskowi zlokalizować zasoby (np. szablony)
# template_folder wskazuje, gdzie szukać plików HTML dla tego Blueprintu
auth_bp = Blueprint('auth', __name__, template_folder='templates')

# --- Konfiguracja (przeniesiona do app.py, ale hasło nadal potrzebne tutaj) ---
POPRAWNE_HASLO = os.environ.get('ADMIN_PASSWORD')
# Sekretny klucz jest ustawiany w głównej aplikacji (app.py)

if not POPRAWNE_HASLO:
    print("="*50)
    print("BŁĄD: Nie ustawiono zmiennej środowiskowej 'ADMIN_PASSWORD'!")
    print("Moduł logowania nie będzie działać poprawnie.")
    print("="*50)

# --- Dekorator sprawdzający logowanie ---
def login_required(view):
    """
    Dekorator, który przekierowuje niezalogowanych użytkowników
    do strony logowania.
    """
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            # Jeśli użytkownik nie jest zalogowany, przekieruj do strony logowania Blueprintu 'auth'
            return redirect(url_for('auth.login_page'))
        # Jeśli zalogowany, wykonaj oryginalną funkcję widoku
        return view(**kwargs)
    return wrapped_view

# --- Strony (Route'y) Blueprintu ---

@auth_bp.route('/login', methods=['GET'])
def login_page():
    """ Wyświetla stronę logowania """
    # Jeśli użytkownik jest już zalogowany, przekieruj go na stronę główną
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('main_index')) # 'main_index' to nazwa funkcji dla '/' w app.py
    return render_template('login.html', error=None)

@auth_bp.route('/api/login', methods=['POST'])
def handle_login():
    """ Obsługuje dane logowania wysłane przez JavaScript (POST) """
    data = request.get_json()
    error = None

    if not data or 'password' not in data:
        return jsonify({'error': 'Brak hasła w zapytaniu'}), 400

    wpisane_haslo = data.get('password')
    username = data.get('username') # Można dodać walidację nazwy użytkownika, jeśli potrzebne

    # Porównaj hasło
    if wpisane_haslo == POPRAWNE_HASLO:
        session['logged_in'] = True
        session['username'] = username # Opcjonalnie zapisz nazwę użytkownika
        # Zwróć URL do przekierowania po stronie klienta
        return jsonify({'redirect_url': url_for('main_index')}) # Przekieruj na główną stronę app.py
    else:
        # Hasło niepoprawne
        return jsonify({'error': 'Niepoprawne hasło lub nazwa użytkownika.'}), 401 # Unauthorized

@auth_bp.route('/logout')
@login_required # Tylko zalogowany użytkownik może się wylogować
def logout():
    """ Wylogowanie """
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('auth.login_page')) # Przekieruj z powrotem do logowania
