import base64
import mimetypes
import sys
import io
import json
import re
import math
import os
import traceback
import uuid
from datetime import datetime, timedelta, date, time
from functools import wraps
from math import exp
from zoneinfo import ZoneInfo
import functools # Potrzebne dla dekoratora login_required
from flask import Flask, jsonify, request, g, session, redirect, url_for, send_from_directory, send_file, render_template, Blueprint, flash # Dodano flash
import joblib
import pandas as pd
import psycopg2
import requests
import psutil
from PIL import Image
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename
from requests.exceptions import ReadTimeout, RequestException

from flask_cors import CORS
# Dodaj importy dla Blueprints, render_template
from flask import Flask, jsonify, request, g, session, redirect, url_for, send_from_directory, send_file, render_template, Blueprint
from contextlib import contextmanager
from psycopg2 import errorcodes
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Table,
                        Boolean, Float, Time, create_engine, func, text, bindparam, TIMESTAMP, Date, desc,
                        UniqueConstraint, select, ARRAY, Enum, TEXT, extract)
from sqlalchemy.orm import declarative_base, selectinload
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base, relationship, joinedload, aliased
from sqlalchemy.exc import IntegrityError
from geopy.distance import geodesic
from werkzeug.security import generate_password_hash, check_password_hash

print("--- SERWER ZALADOWAL NAJNOWSZA WERSJE PLIKU ---")

# === KONFIGURACJA APLIKACJI ===
TZ = ZoneInfo("Europe/Warsaw")
# Główna instancja aplikacji
app = Flask(__name__, static_folder="static", static_url_path="", template_folder='templates') # Określamy folder szablonów
CORS(app, supports_credentials=True) # supports_credentials=True jest ważne dla sesji
app.config['DEBUG'] = True

CENTRUM_PASSWORD = os.environ.get('admin') # Zmieniłem nazwę dla jasności
CENTRUM_USERNAME = os.environ.get('ADMIN_USERNAME') # Wczytaj nową zmienną

# Wczytywanie konfiguracji ze zmiennych środowiskowych
DATABASE_URL = os.getenv("DATABASE_URL")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
# Sekretny klucz dla sesji - MUSI być ustawiony dla logowania
app.secret_key = os.environ.get('FLASK_SECRET_KEY', '4a87aef7ea2d5e256d20bea4fb2853612f09475c43cb841f')

# Ustawienia uploadu
UPLOAD_FOLDER = 'uploads/documents'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set!")
if not app.secret_key or app.secret_key == '4a87aef7ea2d5e256d20bea4fb2853612f09475c43cb841f':
     print("="*50)
     print("OSTRZEŻENIE: Używasz domyślnego FLASK_SECRET_KEY. Zmień go w zmiennych środowiskowych!")
     print("="*50)


print(f"--- APLIKACJA ŁĄCZY SIĘ Z BAZĄ DANYCH: {DATABASE_URL[:30]}... ---")
if not GOOGLE_MAPS_API_KEY:
    print("--- OSTRZEŻENIE: Brak klucza Google Maps API (zmienna 'klucz') ---")

# === INICJALIZACJA BAZY DANYCH (ORM) ===
try:
    engine = create_engine(DATABASE_URL, future=True)
    Base = declarative_base()
    SessionLocal = scoped_session(
        sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    )
    print("--- Połączenie SQLAlchemy zainicjalizowane ---")
except Exception as e:
    print(f"--- BŁĄD Inicjalizacji SQLAlchemy: {e} ---")
    sys.exit(1) # Wyjście z aplikacji jeśli baza nie działa



# === MODUŁ LOGOWANIA (Blueprint) ===
auth_bp = Blueprint('auth', __name__, template_folder='templates')
admin_bp = Blueprint('admin', __name__, template_folder='templates')
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                 return jsonify(message="Authentication required"), 401
            # Użycie flash() jest już poprawne dzięki importowi
            flash('Musisz się zalogować, aby uzyskać dostęp do tej strony.')
            return redirect(url_for('auth.login_page'))
        with session_scope() as db_session:
            user = db_session.get(User, session['user_id'])
            if user is None:
                session.clear()
                flash('Użytkownik nie istnieje. Zaloguj się ponownie.')
                return redirect(url_for('auth.login_page'))
        return view(**kwargs)
    return wrapped_view

def admin_required(view):
    @functools.wraps(view)
    @login_required
    def wrapped_view(**kwargs):
        user_id = session.get('user_id')
        with session_scope() as db_session:
            user = db_session.get(User, user_id)
            if not user or not user.is_admin:
                flash('Nie masz uprawnień administratora, aby uzyskać dostęp do tej strony.')
                if request.path.startswith('/api/'):
                    return jsonify(message="Admin privileges required"), 403
                return redirect(url_for('main_index'))
        return view(**kwargs)
    return wrapped_view
  
@admin_bp.route('/admin/change-password', methods=['GET'])

@admin_required # Wymaga zalogowania i uprawnień admina
def admin_change_password_page():
    """Wyświetla stronę do zmiany hasła."""
    return render_template('change_password.html')

@admin_bp.route('/api/admin/change-password', methods=['POST'])
@admin_required # Wymaga zalogowania i uprawnień admina
def handle_admin_change_password():
    """Obsługuje żądanie zmiany hasła przez API."""
    user_id = session.get('user_id') # Pobierz ID zalogowanego admina z sesji
    if not user_id:
        # Ten warunek teoretycznie nie powinien wystąpić przez @admin_required, ale dla bezpieczeństwa
        return jsonify({'error': 'Brak uwierzytelnienia'}), 401

    data = request.get_json()
    new_password = data.get('new_password')

    if not new_password or len(new_password) < 4:
        return jsonify({'error': 'Nowe hasło jest wymagane i musi mieć co najmniej 4 znaki.'}), 400

    try:
        with session_scope() as db_session:
            # Znajdź użytkownika w bazie na podstawie ID z sesji
            user = db_session.get(User, user_id) 
            if not user:
                 session.clear() # Na wszelki wypadek wyczyść sesję
                 return jsonify({'error': 'Użytkownik nie znaleziony'}), 404

            # Ustaw nowe hasło (metoda set_password automatycznie hashuje)
            user.set_password(new_password)
            # session_scope() zrobi commit automatycznie
            
            print(f"Admin '{user.username}' (ID: {user_id}) zmienił swoje hasło.")
            flash('Hasło zostało pomyślnie zmienione.', 'success') # Opcjonalny komunikat flash
            return jsonify({'message': 'Hasło zostało zmienione pomyślnie.'}), 200

    except Exception as e:
        # session_scope() zrobi rollback automatycznie
        print(f"Błąd podczas zmiany hasła dla user_id={user_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Wystąpił błąd serwera podczas zmiany hasła: {str(e)}'}), 500

# W app.py

@admin_bp.route('/admin/manage-users', methods=['GET'])
@admin_required
def manage_users_page():
    """Wyświetla stronę panelu zarządzania użytkownikami i rolami."""
    try:
        with session_scope() as db_session:
            # Pobierz wszystkich użytkowników i od razu ich powiązane profile (dla optymalizacji)
            all_users = db_session.query(User).options(
                joinedload(User.therapist_profile),
                joinedload(User.driver_profile)
            ).order_by(User.username).all()
            
            # Pobierz listy wszystkich dostępnych terapeutów i kierowców do dropdownów
            all_therapists = db_session.query(Therapist).filter_by(active=True).order_by(Therapist.full_name).all()
            all_drivers = db_session.query(Driver).filter_by(active=True).order_by(Driver.full_name).all()

        # Przekaż dane do szablonu HTML
        return render_template(
            'manage_users.html', 
            users=all_users, 
            therapists=all_therapists, 
            drivers=all_drivers
        )
    except Exception as e:
        print(f"Błąd podczas ładowania strony zarządzania użytkownikami: {e}")
        flash(f"Wystąpił błąd podczas ładowania strony: {e}", "danger")
        return redirect(url_for('main_index'))

@admin_bp.route('/api/admin/users/<int:user_id>/link', methods=['POST'])
@admin_required
def link_user_profiles(user_id):
    """API Endpoint do aktualizacji powiązań profilu terapeuty/kierowcy."""
    data = request.get_json()
    if data is None:
        return jsonify({'error': 'Brak danych JSON'}), 400

    # Używamy .get() aby pozwolić na wysłanie 'null' lub brak klucza
    therapist_id = data.get('therapist_id')
    driver_id = data.get('driver_id')

    # Konwertuj puste wartości (np. 0 lub pusty string "") na None (NULL w bazie)
    if not therapist_id: therapist_id = None
    if not driver_id: driver_id = None

    try:
        with session_scope() as db_session:
            user = db_session.get(User, user_id)
            if not user:
                return jsonify({'error': 'Użytkownik nie znaleziony'}), 404
            
            # Zaktualizuj ID profili
            user.therapist_id = therapist_id
            user.driver_id = driver_id
            
            # session_scope() automatycznie wykona commit
            
            print(f"Admin (ID: {session.get('user_id')}) zaktualizował powiązania dla User ID: {user_id}. Nowe T_ID={therapist_id}, D_ID={driver_id}")
            return jsonify({'message': 'Powiązania zaktualizowane pomyślnie'}), 200
            
    except Exception as e:
        # session_scope() automatycznie wykona rollback
        print(f"Błąd podczas aktualizacji powiązań użytkownika: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500


def therapist_required(view):
    """
    Sprawdza, czy użytkownik jest zalogowany I jest adminem LUB ma profil terapeuty.
    """
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            # Nie zalogowany - przekieruj na logowanie
            flash('Musisz się zalogować, aby uzyskać dostęp do tej strony.')
            return redirect(url_for('auth.login_page'))
        
        if session.get('is_admin') or session.get('therapist_id'):
            # Jest adminem LUB terapeutą - zezwól na dostęp
            return view(**kwargs)
        
        # Nie jest ani adminem, ani terapeutą - brak dostępu
        flash('Nie masz uprawnień (terapeuty), aby uzyskać dostęp do tej strony.')
        return redirect(url_for('main_index')) # Przekieruj na stronę główną
    return wrapped_view

def driver_required(view):
    """
    Sprawdza, czy użytkownik jest zalogowany I jest adminem LUB ma profil kierowcy.
    """
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            flash('Musisz się zalogować, aby uzyskać dostęp do tej strony.')
            return redirect(url_for('auth.login_page'))
        
        if session.get('is_admin') or session.get('driver_id'):
            # Jest adminem LUB kierowcą - zezwól na dostęp
            return view(**kwargs)
        
        # Nie jest ani adminem, ani kierowcą - brak dostępu
        flash('Nie masz uprawnień (kierowcy), aby uzyskać dostęp do tej strony.')
        return redirect(url_for('main_index'))
    return wrapped_view

@app.context_processor
def inject_session_vars():
    return {
        'session': session,
        'is_admin': session.get('is_admin', False),
        'therapist_id': session.get('therapist_id'),
        'driver_id': session.get('driver_id')
    }

#tymczasowa naprawa hasła
#@app.route('/api/reset-admin-password-force', methods=['POST'])
#def reset_admin_password_force():
#    """
#    Tymczasowy endpoint do *wymuszonego* zresetowania hasła admina.
#    Użyj go RAZ po wdrożeniu, a potem usuń/zakomentuj.
#    """
#    admin_username = 'admin'
#    new_password = 'admin123' # Możesz zmienić na inne, jeśli chcesz

#    print(f"--- Wymuszone resetowanie hasła dla '{admin_username}' ---")
#    try:
#        with session_scope() as db_session:
#            admin_user = db_session.query(User).filter_by(username=admin_username).first()

 #           if admin_user:
 #               print(f"Znaleziono użytkownika '{admin_username}'. Stary hash (preview): {admin_user.password_hash[:30]}...")
 #               # Używamy metody set_password, która generuje poprawny hash
 #               admin_user.set_password(new_password) 
 #               db_session.flush() # Wymuś zapis przed commitem
  #              print(f"Nowy hash (preview): {admin_user.password_hash[:30]}...")
  #              # session_scope() automatycznie zrobi commit po wyjściu z bloku 'with'
  #              print(f"Hasło dla '{admin_username}' zostało zresetowane na '{new_password}'.")
  #              return jsonify({'message': f'Hasło dla {admin_username} zostało zresetowane.'}), 200
  #          else:
  #             print(f"Użytkownik '{admin_username}' nie istnieje w bazie.")
  #              return jsonify({'error': f'Użytkownik {admin_username} nie istnieje'}), 404

 #   except Exception as e:
 #       print(f"BŁĄD podczas resetowania hasła: {str(e)}")
 #       import traceback
 #       traceback.print_exc()
        # session_scope() automatycznie zrobi rollback w razie błędu
 #       return jsonify({'error': f'Błąd serwera podczas resetowania hasła: {str(e)}'}), 500


  
#tymczasowa naprawa hasła
@app.route('/api/fix-admin-password', methods=['POST'])
def fix_admin_password():
    """Tymczasowy endpoint do naprawy hasła admina"""
    try:
        with session_scope() as db_session:
            admin_user = db_session.query(User).filter_by(username='admin').first()
            
            if admin_user:
                # Ustaw poprawne hasło
                admin_user.set_password('admin123')
                db_session.commit()
                return jsonify({'message': 'Hasło admina zostało naprawione'}), 200
            else:
                return jsonify({'error': 'Użytkownik admin nie istnieje'}), 404
                
    except Exception as e:
        return jsonify({'error': f'Błąd: {str(e)}'}), 500

@auth_bp.route('/login', methods=['GET'])
def login_page():
    if 'user_id' in session:
        return redirect(url_for('main_index'))
    return render_template('login.html', error=None)

def create_default_user():
    """Tworzy domyślnego użytkownika admin jeśli tabela users jest pusta lub naprawia istniejącego"""
    try:
        with session_scope() as db_session:
            admin_user = db_session.query(User).filter_by(username='admin').first()
            
            if not admin_user:
                # Tworzymy domyślnego admina
                admin_user = User(username='admin', is_admin=True)
                admin_user.set_password('admin123')
                db_session.add(admin_user)
                print("=" * 50)
                print("UTWORZONO DOMYŚLNEGO UŻYTKOWNIKA:")
                print("Nazwa użytkownika: admin")
                print("Hasło: admin123")
                print("=" * 50)
            else:
                # Sprawdź czy hasło jest poprawne, jeśli nie - napraw
                try:
                    # Testujemy czy hasło działa
                    test_result = admin_user.check_password('admin123')
                    if not test_result:
                        # Jeśli nie działa, ustaw nowe hasło
                        admin_user.set_password('admin123')
                        db_session.commit()
                        print("=" * 50)
                        print("NAPRAWIONO HASŁO ADMINA:")
                        print("Nowe hasło: admin123")
                        print("=" * 50)
                except Exception as e:
                    # Jeśli jest błąd z hashowaniem, napraw
                    print(f"Błąd hashowania: {e}, naprawiam...")
                    admin_user.set_password('admin123')
                    db_session.commit()
                    print("=" * 50)
                    print("NAPRAWIONO USZKODZONE HASŁO ADMINA")
                    print("Nowe hasło: admin123")
                    print("=" * 50)
                
    except Exception as e:
        print(f"Błąd tworzenia/naprawy użytkownika: {e}")
        import traceback
        traceback.print_exc()

@auth_bp.route('/api/login', methods=['POST'])
def handle_login():
    data = request.get_json()
    print(f"Login attempt for: {data.get('username')}")
    
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Brak nazwy użytkownika lub hasła'}), 400
    
    username = data.get('username')
    password = data.get('password')
    
    with session_scope() as db_session:
        user = db_session.query(User).filter_by(username=username).first()
        
        if user:
            print(f"User found: {user.username}, password_hash: {user.password_hash[:50]}...")
            try:
                password_correct = user.check_password(password)
                print(f"Password check result: {password_correct}")
                
                if password_correct:
                    session.clear()
                    session['user_id'] = user.id
                    session['username'] = user.username
                    session['is_admin'] = user.is_admin

                            # === NOWY KOD ===
                    # Zapisz powiązane profile w sesji
                    session['therapist_id'] = user.therapist_id
                    session['driver_id'] = user.driver_id
            
                    print(f"Login successful for: {username}, is_admin: {user.is_admin}, therapist_id: {user.therapist_id}")
                    return jsonify({'redirect_url': url_for('main_index')})
                    
                else:
                    print(f"Invalid password for: {username}")
                    return jsonify({'error': 'Niepoprawna nazwa użytkownika lub hasło.'}), 401
                    
            except Exception as e:
                print(f"Password check error: {e}")
                return jsonify({'error': f'Błąd systemu uwierzytelniania: {str(e)}'}), 500
        else:
            print(f"User not found: {username}")
            return jsonify({'error': 'Niepoprawna nazwa użytkownika lub hasło.'}), 401

@auth_bp.route('/logout')
@login_required
def logout():
    session.clear()
    flash('Zostałeś pomyślnie wylogowany.')
    return redirect(url_for('auth.login_page'))

# === BLUEPRINT: Rejestracja tylko dla Admina ===


@admin_bp.route('/admin/register', methods=['GET'])
@admin_required
def admin_register_page():
    return render_template('admin_register.html')

@admin_bp.route('/api/admin/register', methods=['POST'])
@admin_required
def handle_admin_register():
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Nazwa użytkownika i hasło są wymagane'}), 400
    username = data['username'].strip(); password = data['password']; is_admin_flag = data.get('is_admin', False)
    if not username or not password: return jsonify({'error': 'Nazwa użytkownika i hasło nie mogą być puste'}), 400
    if len(password) < 4: return jsonify({'error': 'Hasło musi mieć co najmniej 4 znaki'}), 400
    with session_scope() as db_session:
        existing_user = db_session.query(User).filter_by(username=username).first()
        if existing_user: return jsonify({'error': 'Nazwa użytkownika jest już zajęta'}), 409
        new_user = User(username=username, is_admin=is_admin_flag); new_user.set_password(password); db_session.add(new_user)
        try: db_session.flush(); print(f"Admin '{session.get('username')}' zarejestrował: '{username}' (Admin: {is_admin_flag})"); return jsonify({'message': f'Użytkownik {username} zarejestrowany.'}), 201
        except IntegrityError: db_session.rollback(); return jsonify({'error': 'Błąd zapisu użytkownika.'}), 500
        except Exception as e: db_session.rollback(); print(f"Błąd rejestracji admina: {e}"); return jsonify({'error': f'Błąd serwera: {e}'}), 500

# === REJESTRACJA BLUEPRINTÓW ===
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)

# === GŁÓWNA STRONA APLIKACJI ===
@app.route('/')
@login_required
def main_index():
    is_admin = session.get('is_admin', False)
    therapist_id = session.get('therapist_id')
    driver_id = session.get('driver_id')
    return render_template('index.html', 
                         is_admin=is_admin,
                         therapist_id=therapist_id,
                         driver_id=driver_id)


@app.route('/klient-panel')
@login_required  # Zabezpiecz stronę, aby tylko zalogowani użytkownicy mogli ją widzieć
def klient_panel_page():
   is_admin = session.get('is_admin', False)
    therapist_id = session.get('therapist_id')
    driver_id = session.get('driver_id')
    return render_template('klient-panel.html',
                         is_admin=is_admin,
                         therapist_id=therapist_id,
                         driver_id=driver_id)

#nowe endpointy
# To samo dla innych stron
@app.route('/clients.html')
@therapist_required
def clients_page():
    is_admin = session.get('is_admin', False)
    therapist_id = session.get('therapist_id')
    driver_id = session.get('driver_id')
    return render_template('clients.html',
                         is_admin=is_admin,
                         therapist_id=therapist_id,
                         driver_id=driver_id)

@app.route('/tus.html')
@therapist_required
def clients_page():
    is_admin = session.get('is_admin', False)
    therapist_id = session.get('therapist_id')
    driver_id = session.get('driver_id')
    return render_template('clients.html',
                         is_admin=is_admin,
                         therapist_id=therapist_id,
                         driver_id=driver_id)

#koniec

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set!")
GOOGLE_MAPS_API_KEY = os.getenv("klucz")

# === DODAJ TĘ LINIĘ DIAGNOSTYCZNĄ ===
print(f"--- APLIKACJA ŁĄCZY SIĘ Z BAZĄ DANYCH: {DATABASE_URL} ---")
# ====================================

# === INICJALIZACJA BAZY DANYCH (ORM) ===
engine = create_engine(DATABASE_URL, future=True)


Base = declarative_base()
SessionLocal = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
)

# Konfiguracja PostgreSQL - DOSTOSUJ DO SWOICH DANYCH
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'odnowa_unwh',  # <-- ZMIEŃ
    'user': 'odnowa_unwh_user',        # <-- ZMIEŃ
    'password': 'hr5g2iWpbfxi8Z5ZKBT0PUVQqhuvPAnd'   # <-- ZMIEŃ
}


# Funkcja pomocnicza do walidacji daty
def validate_date(date_string, field_name):
    """Waliduje format daty"""
    try:
        datetime.fromisoformat(date_string)
        return None
    except (ValueError, TypeError):
        return f'Nieprawidłowy format daty w polu {field_name}'


# Funkcja pomocnicza do walidacji długości
def validate_length(value, field_name, max_length):
    """Waliduje długość tekstu"""
    if value and len(value) > max_length:
        return f'{field_name} zbyt długie (max {max_length} znaków)'
    return None


def calculate_distance(lat1, lon1, lat2, lon2):
    if lat1 and lon1 and lat2 and lon2:
        return geodesic((lat1, lon1), (lat2, lon2)).kilometers
    return 0


def get_db_connection():
    """Tworzy połączenie z bazą PostgreSQL"""
    try:
        if DATABASE_URL:
            # Wyłącz SSL dla połączenia lokalnego
            conn = psycopg2.connect(DATABASE_URL, sslmode='disable')
        else:
            # Fallback na lokalne połączenie
            conn = psycopg2.connect(
                host='localhost',
                port=5432,
                database='suo',
                user='postgres',
                password='EDUQ',
                sslmode='disable'  # Wyłącz SSL
            )

        conn.cursor_factory = RealDictCursor
        return conn
    except Exception as e:
        print(f"Błąd połączenia z bazą: {e}")
        raise

def init_journal_table():
    """Inicjalizacja tabeli dziennik"""
    with engine.begin() as conn:
        conn.execute(text('''
                CREATE TABLE IF NOT EXISTS dziennik (
                    id SERIAL PRIMARY KEY,
                    data DATE NOT NULL,
                    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
                    therapist_id INTEGER NOT NULL REFERENCES therapists(id) ON DELETE RESTRICT,
                    temat VARCHAR(255),
                    cele TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            '''))
    print("✓ Tabela dziennik zainicjalizowana")

def init_client_notes_table():
    """Inicjalizacja tabeli notatek klientów"""
    with engine.begin() as conn:
        conn.execute(text('''
                CREATE TABLE IF NOT EXISTS client_notes (
                    id SERIAL PRIMARY KEY,
                    client_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    category VARCHAR(50) NOT NULL DEFAULT 'general',
                    created_by_name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
                )
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_client_notes_client_id 
                ON client_notes(client_id)
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_client_notes_category 
                ON client_notes(category)
            '''))

    print("✓ Tabela client_notes zainicjalizowana")


# 1. Najpierw dodaj funkcję inicjalizacji tabeli (wywołaj przy starcie)
def init_waiting_clients_table():
    """Inicjalizacja tabeli klientów oczekujących"""
    with engine.begin() as conn:
        conn.execute(text('''
                CREATE TABLE IF NOT EXISTS waiting_clients (
                    id SERIAL PRIMARY KEY,
                    first_name VARCHAR(100) NOT NULL,
                    last_name VARCHAR(100) NOT NULL,
                    birth_date DATE NOT NULL,
                    diagnosis TEXT,
                    registration_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    notes TEXT,
                    status VARCHAR(50) DEFAULT 'oczekujący',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_waiting_clients_status 
                ON waiting_clients(status)
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_waiting_clients_registration 
                ON waiting_clients(registration_date)
            '''))

    print("✓ Tabela waiting_clients zainicjalizowana")


# DODAJ TEN ENDPOINT:
@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Serwuje uploadowane pliki"""
    uploads_dir = os.path.join(os.getcwd(), 'uploads')
    return send_from_directory(uploads_dir, filename)


def find_best_match(name_to_find, name_list):
    """
        Znajduje najlepsze dopasowanie dla skróconej nazwy na liście pełnych nazw.
        Obsługuje przypadki typu 'Jan M.' -> 'Jan Kowalski'
        """
    if not name_to_find or not name_list:
        return None

    # Normalizacja wejściowej nazwy - usuwa kropki i zbędne spacje
    name_to_find_clean = re.sub(r'[\.\s]+', ' ', name_to_find.strip())
    name_to_find_lower = name_to_find_clean.lower()

    if not name_to_find_lower:
        return None

    parts_to_find = name_to_find_lower.split()

    best_match = None
    highest_score = 0

    for full_name in name_list:
        current_score = 0
        full_name_clean = re.sub(r'[\.\s]+', ' ', full_name.strip())
        full_name_lower = full_name_clean.lower()
        parts_full = full_name_lower.split()

        # Debug: wypisz co porównujemy
        print(f"Porównuję: '{name_to_find_lower}' z '{full_name_lower}'")

        # 1. Dokładne dopasowanie (najwyższy priorytet)
        if full_name_lower == name_to_find_lower:
            current_score = 100
            print("  → Dokładne dopasowanie!")

        # 2. Dopasowanie skrótu z inicjałem "Jan M" -> "Jan Kowalski"
        elif len(parts_to_find) == 2 and len(parts_full) >= 2:
            first_name_find = parts_to_find[0]
            last_initial_find = parts_to_find[1]

            # Sprawdź czy pierwsze imię pasuje i inicjał nazwiska też
            if (parts_full[0] == first_name_find and
                    len(last_initial_find) == 1 and
                    parts_full[1][0] == last_initial_find[0]):
                current_score = 95
                print(
                    f"  → Dopasowanie inicjału: {first_name_find} {last_initial_find} -> {parts_full[0]} {parts_full[1]}")

        # 3. Dopasowanie tylko imienia "Jan" -> "Jan Kowalski"
        elif len(parts_to_find) == 1 and len(parts_full) >= 1:
            if parts_full[0] == parts_to_find[0]:
                current_score = 70
                print(f"  → Dopasowanie imienia: {parts_to_find[0]} -> {parts_full[0]}")

        # 4. Dopasowanie przez zawieranie
        elif name_to_find_lower in full_name_lower:
            current_score = 50
            print(f"  → Zawieranie: '{name_to_find_lower}' w '{full_name_lower}'")

        # 5. Dopasowanie pierwszego słowa
        elif parts_to_find and parts_full and parts_to_find[0] == parts_full[0]:
            current_score = 60
            print(f"  → Dopasowanie pierwszego słowa: {parts_to_find[0]}")

        # 6. Dopasowanie przez wspólne słowa
        else:
            matching_words = 0
            for word in parts_to_find:
                if any(part.startswith(word) for part in parts_full if len(word) > 1):
                    matching_words += 1

            if matching_words == len(parts_to_find):
                current_score = 80
                print(f"  → Wszystkie słowa pasują: {matching_words}")
            elif matching_words > 0:
                current_score = 40 + (matching_words * 10)
                print(f"  → Częściowe dopasowanie słów: {matching_words}")

        # Aktualizuj najlepsze dopasowanie
        if current_score > highest_score:
            highest_score = current_score
            best_match = full_name
            print(f"  → NOWE NAJLEPSZE DOPASOWANIE: {full_name} (wynik: {current_score})")

    # Zwróć wynik tylko jeśli osiągnięto minimalny próg dopasowania
    print(f"NAJLEPSZE DOPASOWANIE: {best_match} (wynik: {highest_score})")

    if highest_score >= 40:
        return best_match

    # Jeśli nie znaleziono dobrego dopasowania, zwróć None
    return None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_safe_filepath(client_id, filename):
    client_folder = os.path.join(UPLOAD_FOLDER, str(client_id))
    os.makedirs(client_folder, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = secure_filename(filename)
    name, ext = os.path.splitext(safe_name)
    unique_filename = f"{name}_{timestamp}{ext}"

    return os.path.join(client_folder, unique_filename)


class TUSSessionAttendance(Base):
    __tablename__ = 'tus_session_attendance'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('tus_sessions.id', ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default='obecny')  # np. obecny, nieobecny, spóźniony, usprawiedliwiony

    __table_args__ = (UniqueConstraint('session_id', 'client_id'),)


class IndividualSessionAttendance(Base):
    __tablename__ = 'individual_session_attendance'
    id = Column(Integer, primary_key=True)
    slot_id = Column(Integer, ForeignKey('schedule_slots.id', ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String, nullable=False, default='obecny')


class Client(Base):
    __tablename__ = 'clients'
    id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False, unique=True)
    phone = Column(String)
    address = Column(String)
    active = Column(Boolean, default=True, nullable=False)
    # Relacja zwrotna jest tworzona automatycznie przez `backref` w modelu TUSGroup
    # POPRAWKA: Definiujemy relację do obiektu pośredniczącego
    group_associations = relationship("TUSGroupMember", back_populates="client", cascade="all, delete-orphan")


class Therapist(Base):
    __tablename__ = 'therapists'
    id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False, unique=True)
    specialization = Column(String)
    phone = Column(String)
    active = Column(Boolean, default=True, nullable=False)
    tus_groups = relationship(
        "TUSGroup",
        foreign_keys="[TUSGroup.therapist_id]",  # <-- DODAJ TĘ LINIĘ
        back_populates="therapist",
        lazy="selectin"
    )


class Driver(Base):
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True)
    full_name = Column(String(255), nullable=False, unique=True)
    active = Column(Boolean, default=True)
    phone = Column(String(50))


class ScheduleSlot(Base):
    __tablename__ = 'schedule_slots'
    id = Column(Integer, primary_key=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey('event_groups.id', ondelete="CASCADE"))
    client_id = Column(Integer, ForeignKey('clients.id'))
    therapist_id = Column(Integer, ForeignKey('therapists.id'))
    driver_id = Column(Integer, ForeignKey('drivers.id'))
    kind = Column(Enum('therapy', 'pickup', 'dropoff', name='session_kind', create_type=False), nullable=False)
    starts_at = Column(DateTime(timezone=True))
    ends_at = Column(DateTime(timezone=True))
    status = Column(String, default='planned')
    distance_km = Column(Float)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    run_id = Column(UUID(as_uuid=True), nullable=True)
    attendance = relationship("IndividualSessionAttendance", uselist=False, cascade="all, delete-orphan")


class TUSGroupMember(Base):
    __tablename__ = "tus_group_members"
    group_id = Column(Integer, ForeignKey("tus_groups.id", ondelete="CASCADE"), primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relacje do modeli nadrzędnych
    client = relationship("Client", back_populates="group_associations")
    group = relationship("TUSGroup", back_populates="member_associations")


def _create_member_association(client):
    return TUSGroupMember(client=client)


class TUSGroup(Base):
    __tablename__ = "tus_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    therapist_id = Column(Integer, ForeignKey("therapists.id", ondelete="SET NULL"))
    assistant_therapist_id = Column(Integer, ForeignKey("therapists.id", ondelete="SET NULL"))

    # --- POPRAWIONE RELACJE ---
    therapist = relationship("Therapist", back_populates="tus_groups", lazy="selectin", foreign_keys=[therapist_id])
    sessions = relationship("TUSSession", back_populates="group", cascade="all, delete-orphan", lazy="selectin")
    assistant_therapist = relationship("Therapist", lazy="selectin", foreign_keys=[assistant_therapist_id])
    # POPRAWKA: Definiujemy relację do obiektu pośredniczącego
    member_associations = relationship("TUSGroupMember", back_populates="group", cascade="all, delete-orphan")
    # "Proxy" sprawia, że group.members jest wygodną listą klientów
    # Association proxy z dodanym creatorem
    members = association_proxy(
        'member_associations',  # <-- ZMIANA Z 'group_members' NA 'member_associations'
        'client',
        creator=_create_member_association
    )

    # Dodatkowe pola na cele punktowe
    halfyear_target_points = Column(Integer)
    halfyear_reward = Column(String)
    annual_target_points = Column(Integer)
    annual_reward = Column(String)
    schedule_days = Column(ARRAY(Date))


class TUSTopic(Base):
    __tablename__ = 'tus_topics'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False, unique=True)
    description = Column(String)


class TUSSession(Base):
    __tablename__ = "tus_sessions"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("tus_groups.id", ondelete="CASCADE"), nullable=False)
    session_date = Column(Date, nullable=False)
    session_time = Column(Time)
    topic_id = Column(Integer, ForeignKey("tus_topics.id", ondelete="SET NULL"))
    bonuses_awarded = Column(Integer, default=0)
    group = relationship("TUSGroup", back_populates="sessions", lazy="joined")
    topic = relationship("TUSTopic")

    scores = relationship("TUSSessionMemberScore", back_populates="session", cascade="all, delete-orphan")
    member_bonuses = relationship("TUSMemberBonus", back_populates="session", cascade="all, delete-orphan")
    attendance = relationship("TUSSessionAttendance", cascade="all, delete-orphan")
    # --- KONIEC ---


####

class TUSMemberBonus(Base):
    __tablename__ = 'tus_member_bonuses'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('tus_sessions.id', ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    points = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    session = relationship("TUSSession", back_populates="member_bonuses")
    client = relationship("Client")


class TUSBehavior(Base):
    __tablename__ = 'tus_behaviors'
    id = Column(Integer, primary_key=True)
    title = Column(String, unique=True, nullable=False)
    description = Column(String)
    default_max_points = Column(Integer, nullable=False, default=3)
    active = Column(Boolean, nullable=False, default=True)


class TUSGeneralBonus(Base):
    __tablename__ = 'tus_general_bonuses'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    group_id = Column(Integer, ForeignKey('tus_groups.id', ondelete="CASCADE"), nullable=False)
    points = Column(Integer, nullable=False, default=0)
    reason = Column(String)
    awarded_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client")
    group = relationship("TUSGroup")


class TUSSessionBehavior(Base):
    __tablename__ = 'tus_session_behaviors'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('tus_sessions.id', ondelete="CASCADE"), nullable=False)
    behavior_id = Column(Integer, ForeignKey('tus_behaviors.id'), nullable=False)
    max_points = Column(Integer, nullable=False, default=3)
    __table_args__ = (UniqueConstraint('session_id', 'behavior_id'),)


class TUSSessionMemberScore(Base):
    __tablename__ = 'tus_session_member_scores'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('tus_sessions.id', ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    behavior_id = Column(Integer, ForeignKey('tus_behaviors.id'), nullable=False)
    points = Column(Integer, nullable=False, default=0)
    __table_args__ = (UniqueConstraint('session_id', 'client_id', 'behavior_id'),)
    session = relationship("TUSSession", back_populates="scores")


class TUSSessionPartialReward(Base):
    __tablename__ = 'tus_session_partial_rewards'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('tus_sessions.id', ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    awarded = Column(Boolean, nullable=False, default=False)
    note = Column(String)
    awarded_at = Column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('session_id', 'client_id'),)


class TUSGroupTarget(Base):
    __tablename__ = 'tus_group_targets'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('tus_groups.id', ondelete="CASCADE"), nullable=False)
    school_year_start = Column(Integer, nullable=False)  # Np. 2025 dla roku 2025/2026
    semester = Column(Integer, nullable=False)  # 1 lub 2
    target_points = Column(Integer, nullable=False, default=0)
    reward = Column(String)

    __table_args__ = (UniqueConstraint('group_id', 'school_year_start', 'semester'),)


class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(String)
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(String(50), default='planowany')  # planowany, w_trakcie, zakończony
    budget = Column(Float)
    coordinator = Column(String(255))
    partners = Column(String)  # Lista partnerów (tekst)
    beneficiaries_count = Column(Integer)
    photo_url = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EventGroup(Base):
    __tablename__ = 'event_groups'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(Integer, ForeignKey('clients.id'))
    label = Column(String)
    slots = relationship("ScheduleSlot", cascade="all, delete-orphan")

# === MODEL: User ===
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False) 
    is_admin = Column(Boolean, default=False, nullable=False)

    # === NOWE POLA ===
    therapist_id = Column(Integer, ForeignKey('therapists.id'), nullable=True)
    driver_id = Column(Integer, ForeignKey('drivers.id'), nullable=True)

    # === NOWE RELACJE ===
    therapist_profile = relationship("Therapist", foreign_keys=[therapist_id])
    driver_profile = relationship("Driver", foreign_keys=[driver_id])

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# === MODELE DZIENNIKA ===
class JournalEntry(Base):
    __tablename__ = 'dziennik'
    id = Column(Integer, primary_key=True)
    data = Column(Date, nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="RESTRICT"), nullable=False)
    therapist_id = Column(Integer, ForeignKey('therapists.id', ondelete="RESTRICT"), nullable=False)
    temat = Column(String(255))
    cele = Column(TEXT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relacje ułatwiające pobieranie pełnych nazw
    client = relationship("Client", foreign_keys=[client_id], lazy="joined")
    therapist = relationship("Therapist", foreign_keys=[therapist_id], lazy="joined")


# === WCZYTANIE MODELI AI ===
CT_MODEL_PATH = "models/ct_recommender.pkl"
CD_MODEL_PATH = "models/cd_recommender.pkl"

ct_model, cd_model = None, None
try:
    if os.path.exists(CT_MODEL_PATH):
        ct_model = joblib.load(CT_MODEL_PATH)
        print("Model rekomendacji terapeutów wczytany.")
except Exception as e:
    print(f"BŁĄD: Nie można wczytać modelu terapeutów: {e}")

try:
    if os.path.exists(CD_MODEL_PATH):
        cd_model = joblib.load(CD_MODEL_PATH)
        print("Model rekomendacji kierowców wczytany.")
except Exception as e:
    print(f"BŁĄD: Nie można wczytać modelu kierowców: {e}")


# === FUNKCJE POMOCNICZE ===
@contextmanager
def session_scope():
    """Ujednolicony context manager dla sesji ORM."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


Session = sessionmaker(bind=engine)
with session_scope() as db_session:
    # Pobieramy pierwszego terapeutę z bazy
    pierwszy_terapeuta = db_session.query(Therapist).first()

    # if pierwszy_terapeuta:
    # print(f"Znaleziono terapeutę: {pierwszy_terapeuta.full_name}")


def get_route_distance(origin, destination):
    """Oblicza dystans między dwoma punktami za pomocą Google Maps API."""
    print(f"\n{'=' * 60}")
    print(f"FUNKCJA get_route_distance() WYWOŁANA")
    print(f"Origin: '{origin}'")
    print(f"Destination: '{destination}'")

    api_key = GOOGLE_MAPS_API_KEY
    print(f"Klucz API w funkcji: {api_key[:20]}..." if api_key else "❌ BRAK")

    if not api_key:
        print("⚠️ OSTRZEŻENIE: Brak klucza GOOGLE_MAPS_API_KEY. Obliczanie dystansu nie zadziała.")
        return None

    if not origin or not destination:
        print("⚠️ OSTRZEŻENIE: Brak origin lub destination")
        return None

    origin_safe = requests.utils.quote(origin)
    destination_safe = requests.utils.quote(destination)
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin_safe}&destination={destination_safe}&key={api_key}"

    print(f"📡 URL (bez klucza): ...{url[-50:]}")

    try:
        print("📤 Wysyłam zapytanie do Google Maps...")
        response = requests.get(url, timeout=10)  # Zwiększony timeout
        print(f"📥 Status code: {response.status_code}")

        response.raise_for_status()
        data = response.json()

        print(f"📊 Status API: {data.get('status')}")

        if data.get('status') == 'OK':
            distance_meters = data['routes'][0]['legs'][0]['distance']['value']
            distance_km = round(distance_meters / 1000, 2)
            print(f"✅ SUKCES! Dystans: {distance_km} km")
            print(f"{'=' * 60}\n")
            return distance_km
        else:
            print(f"❌ Błąd API: {data.get('status')}")
            print(f"   Komunikat: {data.get('error_message', 'Brak')}")
            print(f"   Pełna odpowiedź: {data}")
            print(f"{'=' * 60}\n")
            return None

    except requests.exceptions.Timeout:
        print(f"⏱️ TIMEOUT: Zapytanie przekroczyło limit czasu")
        print(f"{'=' * 60}\n")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Błąd połączenia z Google Maps API: {e}")
        print(f"{'=' * 60}\n")
        return None
    except (KeyError, IndexError) as e:
        print(f"❌ Błąd parsowania odpowiedzi: {e}")
        print(f"   Struktura danych: {data}")
        print(f"{'=' * 60}\n")
        return None
    except Exception as e:
        print(f"❌ Nieoczekiwany błąd: {type(e).__name__}: {e}")
        import traceback
        print(traceback.format_exc())
        print(f"{'=' * 60}\n")
        return None


def _time_bucket(hhmm: str) -> str:
    """Zaokrągla czas do najbliższych 30 minut w dół (np. 09:10 -> 09:00)."""
    h, m = map(int, hhmm.split(":"))
    m = 0 if m < 30 else 30
    return f"{h:02d}:{m:02d}"


def _date_str(dt):
    """Konwertuje obiekt daty na string w formacie YYYY-MM-DD."""
    return dt.strftime("%Y-%m-%d")


def _score(freq, maxfreq, recency_days):
    """Oblicza wynik na podstawie częstości i świeżości interakcji."""
    if maxfreq <= 0:
        base = 0.0
    else:
        base = (freq + 1.0) / (maxfreq + 2.0)
    rec_bonus = 0.3 * exp(-recency_days / 30.0) if recency_days is not None else 0.0
    return min(1.0, base + rec_bonus)


def _parse_time(s: str):
    """Parsuje string HH:MM na krotkę (godzina, minuta)."""
    h, m = map(int, s.split(":"))
    return h, m


def _to_tstz(date_yyyy_mm_dd: str, hhmm: str, tz=TZ):
    """Tworzy obiekt datetime ze strefą czasową na podstawie daty i czasu."""
    h, m = _parse_time(hhmm)
    d = datetime.fromisoformat(date_yyyy_mm_dd)
    return d.replace(hour=h, minute=m, second=0, microsecond=0, tzinfo=tz)


def _availability_conflicts(conn, therapist_id=None, driver_id=None, starts_at=None, ends_at=None):
    """Sprawdza konflikty w harmonogramie dla danej osoby i czasu."""
    return find_overlaps(conn,
                         therapist_id=therapist_id,
                         driver_id=driver_id,
                         starts_at=starts_at, ends_at=ends_at)


def _softmax(x):
    """Funkcja softmax do normalizacji wyników."""
    m = max(x) if x else 0.0
    exps = [math.exp(v - m) for v in x]
    s = sum(exps) or 1.0
    return [v / s for v in exps]


def _score_cd_row(r):
    """Heurystyka oceny dopasowania klient-kierowca (fallback dla AI)."""
    n = r.get("n_runs", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5 * rec + 0.3 * done + 0.2 * min(1.0, n / 10.0) + 0.1 * min(1.0, mins / 600.0)


# Poprawiona funkcja find_overlaps z wykluczeniem aktualnie edytowanego slotu
def find_overlaps(conn, *, driver_id=None, therapist_id=None, starts_at=None, ends_at=None, exclude_slot_id=None):
    """
    Zwraca listę kolidujących slotów z możliwością wykluczenia konkretnego slot_id
    """
    if starts_at is None or ends_at is None:
        return []

    if therapist_id is not None:
        sql = text("""
            -- Konflikty z kalendarza indywidualnego
            SELECT
                ss.id, 'individual' as schedule_type, ss.kind, ss.starts_at, ss.ends_at, ss.status,
                t.full_name AS therapist_name, c.full_name AS client_name
            FROM schedule_slots ss
            JOIN therapists t ON t.id = ss.therapist_id
            LEFT JOIN clients c ON c.id = ss.client_id
            WHERE ss.therapist_id = :person_id
                AND ss.status != 'cancelled'
                AND tstzrange(ss.starts_at, ss.ends_at, '[)') && tstzrange(:s, :e, '[)')
                AND (:exclude_id IS NULL OR ss.id != :exclude_id)

            UNION ALL

            -- Konflikty z kalendarza grupowego TUS
            SELECT
                s.id, 'tus_group' as schedule_type, 'therapy' as kind,
                (s.session_date + COALESCE(s.session_time, '00:00:00'::time)) AT TIME ZONE 'Europe/Warsaw' AS starts_at,
                (s.session_date + COALESCE(s.session_time, '00:00:00'::time) + INTERVAL '60 minutes') AT TIME ZONE 'Europe/Warsaw' AS ends_at,
                'planned' as status, t.full_name AS therapist_name, g.name AS client_name
            FROM tus_sessions s
            JOIN tus_groups g ON s.group_id = g.id
            JOIN therapists t ON t.id = :person_id
            WHERE (g.therapist_id = :person_id OR g.assistant_therapist_id = :person_id)
                AND tstzrange(
                    (s.session_date + COALESCE(s.session_time, '00:00:00'::time)) AT TIME ZONE 'Europe/Warsaw',
                    (s.session_date + COALESCE(s.session_time, '00:00:00'::time) + INTERVAL '60 minutes') AT TIME ZONE 'Europe/Warsaw',
                    '[)'
                ) && tstzrange(:s, :e, '[)')
        """)
        params = {"person_id": therapist_id, "s": starts_at, "e": ends_at, "exclude_id": exclude_slot_id}

    elif driver_id is not None:
        sql = text("""
            SELECT
                ss.id, 'individual' as schedule_type, ss.kind, ss.starts_at, ss.ends_at, ss.status,
                d.full_name AS driver_name, c.full_name AS client_name
            FROM schedule_slots ss
            JOIN drivers d ON d.id = ss.driver_id
            LEFT JOIN clients c ON c.id = ss.client_id
            WHERE ss.driver_id = :person_id
                AND ss.status != 'cancelled'
                AND tstzrange(ss.starts_at, ss.ends_at, '[)') && tstzrange(:s, :e, '[)')
                AND (:exclude_id IS NULL OR ss.id != :exclude_id)
        """)
        params = {"person_id": driver_id, "s": starts_at, "e": ends_at, "exclude_id": exclude_slot_id}
    else:
        return []

    return [dict(r) for r in conn.execute(sql, params).mappings().all()]

def ensure_shared_run_id_for_driver(conn, driver_id, starts_at, ends_at):
    """Znajduje lub tworzy wspólne ID dla kursów odbywających się w tym samym czasie."""
    q = text("""
          SELECT id, run_id FROM schedule_slots
          WHERE driver_id = :did AND starts_at = :s AND ends_at = :e
          LIMIT 1
        """)
    row = conn.execute(q, {"did": driver_id, "s": starts_at, "e": ends_at}).mappings().first()
    if not row:
        return None

    if row["run_id"] is None:
        new_run = str(uuid.uuid4())
        conn.execute(
            text("UPDATE schedule_slots SET run_id = :rid WHERE id = :id"),
            {"rid": new_run, "id": row["id"]}
        )
        return new_run
    return row["run_id"]


def ensure_shared_session_id_for_therapist(conn, therapist_id, starts_at, ends_at):
    """Znajduje lub tworzy wspólne ID dla sesji terapeutycznych w tym samym czasie."""
    q = text("""
          SELECT id, session_id FROM schedule_slots
          WHERE therapist_id = :tid AND starts_at = :s AND ends_at = :e
          LIMIT 1
        """)
    row = conn.execute(q, {"tid": therapist_id, "s": starts_at, "e": ends_at}).mappings().first()
    if not row:
        return None
    if row["session_id"] is None:
        new_sid = str(uuid.uuid4())
        conn.execute(
            text("UPDATE schedule_slots SET session_id = :sid WHERE id = :id"),
            {"sid": new_sid, "id": row["id"]}
        )
        return new_sid
    return row["session_id"]

# Endpoint do pobierania dostępnych terapeutów dla formularza dodawania
@app.route('/api/available-therapists', methods=['GET'])
def get_available_therapists():
    """Zwraca listę aktywnych terapeutów dla formularza dodawania wizyt"""
    try:
        with engine.begin() as conn:
            therapists = conn.execute(text("""
                SELECT id, full_name, specialization
                FROM therapists 
                WHERE active = true
                ORDER BY full_name
            """)).mappings().all()

            return jsonify([dict(t) for t in therapists]), 200
    except Exception as e:
        print(f"Błąd pobierania terapeutów: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Endpoint do sprawdzania dostępności terapeuty
@app.route('/api/check-availability', methods=['POST', 'GET'])  # Dodaj GET
def check_availability():
    """Sprawdza dostępność terapeuty w danym czasie"""
    
    # Dla metody GET zwróć informację o endpointie
    if request.method == 'GET':
        return jsonify({
            "message": "Endpoint check-availability jest aktywny",
            "usage": "Wymaga metody POST z danymi: therapist_id, starts_at, ends_at",
            "example_payload": {
                "therapist_id": 1,
                "starts_at": "2024-01-23T10:00:00",
                "ends_at": "2024-01-23T11:00:00"
            }
        }), 200
    
    # Dla metody POST - oryginalna logika
    data = request.get_json(silent=True) or {}
    
    therapist_id = data.get('therapist_id')
    starts_at = data.get('starts_at')
    ends_at = data.get('ends_at')
    exclude_slot_id = data.get('exclude_slot_id')

    if not all([therapist_id, starts_at, ends_at]):
        return jsonify({"error": "Brak wymaganych pól"}), 400

    try:
        starts_at_dt = datetime.fromisoformat(starts_at.replace('Z', '+00:00')).astimezone(TZ)
        ends_at_dt = datetime.fromisoformat(ends_at.replace('Z', '+00:00')).astimezone(TZ)

        with engine.begin() as conn:
            conflicts = find_overlaps(conn, therapist_id=therapist_id,
                                    starts_at=starts_at_dt, ends_at=ends_at_dt,
                                    exclude_slot_id=exclude_slot_id)

            return jsonify({
                "available": len(conflicts) == 0,
                "conflicts": conflicts
            }), 200

    except Exception as e:
        print(f"Błąd sprawdzania dostępności: {str(e)}")
        return jsonify({"error": str(e)}), 500

# === DEKORATORY I HOOKI FLASK ===
@app.before_request
def parse_json_only_when_needed():
    if request.method in ('POST', 'PUT', 'PATCH'):
        g.json = request.get_json(silent=True) or {}
    else:
        g.json = None


# === GŁÓWNE ENDPOINTY APLIKACJI ===

#@app.get("/")
#def index():
#    return app.send_static_file("index.html")


@app.get("/api/ai/gaps")
def ai_gaps():
    """
        ?month=YYYY-MM
        Zwraca listy:
          - clients_without_therapy_days: [ {client_id, full_name, date}, ... ]
          - therapists_idle_days: [ {therapist_id, full_name, date}, ... ]
          - drivers_idle_days: [ {driver_id, full_name, date}, ... ]
        """
    mk = request.args.get("month") or datetime.now(TZ).strftime("%Y-%m")
    first = datetime.fromisoformat(mk + "-01").date()
    # prosty zakres – do końca miesiąca
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    days = []
    d = first
    while d < nxt:
        days.append(d)
        d += timedelta(days=1)

    with engine.begin() as conn:
        # Klienci aktywni
        clients = conn.execute(text("SELECT id, full_name FROM clients WHERE active=true")).mappings().all()
        therapists = conn.execute(text("SELECT id, full_name FROM therapists WHERE active=true")).mappings().all()
        drivers = conn.execute(text("SELECT id, full_name FROM drivers WHERE active=true")).mappings().all()

        # sloty w miesiącu
        q = text("""
              SELECT kind, client_id, therapist_id, driver_id,
                     (starts_at AT TIME ZONE 'Europe/Warsaw')::date AS d
              FROM schedule_slots
              WHERE to_char(starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            """)
        rows = conn.execute(q, {"mk": mk}).mappings().all()

    # indeksy
    had_therapy = {(r["client_id"], r["d"]) for r in rows if r["kind"] == "therapy"}
    th_worked = {(r["therapist_id"], r["d"]) for r in rows if r["therapist_id"] and r["kind"] == 'therapy'}
    dr_worked = {(r["driver_id"], r["d"]) for r in rows if r["driver_id"] and r["kind"] in ('pickup', 'dropoff')}

    clients_without = []
    for c in clients:
        for d in days:
            if (c["id"], d) not in had_therapy:
                clients_without.append({"id": c["id"], "full_name": c["full_name"], "date": _date_str(d)})

    therapists_idle = []
    for t in therapists:
        for d in days:
            if (t["id"], d) not in th_worked:
                therapists_idle.append({"id": t["id"], "full_name": t["full_name"], "date": _date_str(d)})

    drivers_idle = []
    for dr in drivers:
        for d in days:
            if (dr["id"], d) not in dr_worked:
                drivers_idle.append({"id": dr["id"], "full_name": dr["full_name"], "date": _date_str(d)})

    return jsonify({
        "clients_without_therapy_days": clients_without,
        "therapists_idle_days": therapists_idle,
        "drivers_idle_days": drivers_idle
    }), 200


@app.post("/api/ai/suggest")
def ai_suggest():
    """
        JSON:
        {
          "client_id": 123,
          "date": "2025-08-22",          # dzień planowania
          "therapy_window": ["08:00","16:00"],   # opcjonalnie
          "pickup_offset_min": 30,       # ile przed terapią
          "dropoff_offset_min": 30       # ile po terapii
        }
        Zwraca:
        {
          "therapy": [ {therapist_id, full_name, score, suggested_start, suggested_end}, ... ],
          "drivers_pickup": [ {driver_id, full_name, score, suggested_start, suggested_end}, ... ],
          "drivers_dropoff": [ ... ]
        }
        """
    data = request.get_json(silent=True) or {}
    cid = int(data["client_id"])
    date_str = data["date"]  # YYYY-MM-DD
    window = data.get("therapy_window") or ["08:00", "16:00"]
    pk_off = int(data.get("pickup_offset_min", 30))
    dp_off = int(data.get("dropoff_offset_min", 30))

    start_bucket = _time_bucket(window[0])
    end_bucket = _time_bucket(window[1])

    # przygotuj wiadra półgodzinne w zakresie okna
    all_buckets = []
    sh, sm = _parse_time(start_bucket)
    eh, em = _parse_time(end_bucket)
    cur_h, cur_m = sh, sm
    while (cur_h, cur_m) <= (eh, em):
        all_buckets.append(f"{cur_h:02d}:{cur_m:02d}")
        if cur_m == 0:
            cur_h, cur_m = cur_h, 30
        else:
            cur_h, cur_m = cur_h + 1, 0

    with engine.begin() as conn:
        # --- TERAPEUCI: kto z tym klientem i o jakich godzinach pracuje
        q1 = text("""
                SELECT t.id, t.full_name, COALESCE(v.n,0) AS n, v.last_dt
                FROM therapists t
                LEFT JOIN v_hist_client_therapist v
                  ON v.therapist_id = t.id AND v.client_id = :cid
                WHERE t.active = true
            """)
        th_rows = conn.execute(q1, {"cid": cid}).mappings().all()
        if not th_rows:
            return jsonify({"therapy": [], "drivers_pickup": [], "drivers_dropoff": []}), 200

        # max freq do normalizacji
        max_n_th = max((r["n"] for r in th_rows), default=0)

        # preferencje godzinowe terapeuty
        q_thh = text("""
              SELECT therapist_id, hhmm, n FROM v_hist_therapist_hour
              WHERE hhmm = ANY(:buckets)
            """)
        thh = conn.execute(q_thh, {"buckets": all_buckets}).mappings().all()
        pref_map = {}  # (therapist_id -> {hhmm: n})
        for r in thh:
            pref_map.setdefault(r["therapist_id"], {})[r["hhmm"]] = r["n"]

        # policz kandydatów: TOP 5
        therapy_candidates = []
        today = datetime.now(TZ).date()
        for r in th_rows:
            last_dt = r["last_dt"]
            rec_days = (today - last_dt.date()).days if last_dt else None
            base_score = _score(r["n"], max_n_th, rec_days)

            # znajdź bucket z największą „zgodnością” godzinową
            hours_pref = pref_map.get(r["id"], {})
            # fallback: środek okna, jeśli brak historii godzinowej
            best_bucket = max(all_buckets, key=lambda b: hours_pref.get(b, 0)) if hours_pref else all_buckets[
                len(all_buckets) // 2]

            # sugerowany 60-min slot terapii (możesz zmienić)
            th_start = _to_tstz(date_str, best_bucket)
            th_end = th_start + timedelta(minutes=60)

            # sprawdź kolizje terapeuty
            col = _availability_conflicts(conn, therapist_id=r["id"], starts_at=th_start, ends_at=th_end)
            if col:
                # jeśli koliduje, spróbuj przesuwać po bucketach (do 4 prób)
                tried = set([best_bucket])
                ok = False
                for b in all_buckets:
                    if b in tried: continue
                    s2 = _to_tstz(date_str, b);
                    e2 = s2 + timedelta(minutes=60)
                    if not _availability_conflicts(conn, therapist_id=r["id"], starts_at=s2, ends_at=e2):
                        best_bucket, th_start, th_end = b, s2, e2
                        ok = True
                        break
                if not ok:
                    # pominąć niedostępnych
                    continue

            therapy_candidates.append({
                "therapist_id": r["id"],
                "full_name": r["full_name"],
                "score": round(base_score, 3),
                "suggested_start": th_start.isoformat(),
                "suggested_end": th_end.isoformat()
            })

        therapy_candidates.sort(key=lambda x: x["score"], reverse=True)
        therapy_candidates = therapy_candidates[:5]

        # --- DRIVERS: dla najlepszego czasu terapii (jeśli jest)
        drivers_pickup = []
        drivers_dropoff = []
        if therapy_candidates:
            # weź najwyżej punktowaną propozycję terapii
            best_th = therapy_candidates[0]
            th_s = datetime.fromisoformat(best_th["suggested_start"])
            th_e = datetime.fromisoformat(best_th["suggested_end"])

            # pick-up: slot kończący się o starcie terapii
            pk_end = th_s
            pk_start = pk_end - timedelta(minutes=pk_off)

            # drop-off: slot zaczynający się po terapii
            dp_start = th_e
            dp_end = dp_start + timedelta(minutes=dp_off)

            q2 = text("""
                    SELECT d.id, d.full_name, COALESCE(v.n,0) AS n, v.last_dt
                    FROM drivers d
                    LEFT JOIN v_hist_client_driver v
                      ON v.driver_id = d.id AND v.client_id = :cid
                    WHERE d.active = true
                """)
            dr_rows = conn.execute(q2, {"cid": cid}).mappings().all()
            max_n_dr = max((r["n"] for r in dr_rows), default=0)

            # godzinowe preferencje kierowców
            buckets_needed = list({_time_bucket(pk_start.strftime("%H:%M")),
                                   _time_bucket(dp_start.strftime("%H:%M"))})
            q_drh = text("""
                  SELECT driver_id, hhmm, n FROM v_hist_driver_hour
                  WHERE hhmm = ANY(:buckets)
                """)
            drh = conn.execute(q_drh, {"buckets": buckets_needed}).mappings().all()
            dr_pref = {}
            for r in drh:
                dr_pref.setdefault(r["driver_id"], {})[r["hhmm"]] = r["n"]

            for r in dr_rows:
                # pickup
                rec_days = (today - r["last_dt"].date()).days if r["last_dt"] else None
                base = _score(r["n"], max_n_dr, rec_days)
                bpk = _time_bucket(pk_start.strftime("%H:%M"))
                base_pk = base + (0.05 if dr_pref.get(r["id"], {}).get(bpk, 0) > 0 else 0.0)

                col = _availability_conflicts(conn, driver_id=r["id"], starts_at=pk_start, ends_at=pk_end)
                if not col:
                    drivers_pickup.append({
                        "driver_id": r["id"], "full_name": r["full_name"],
                        "score": round(base_pk, 3),
                        "suggested_start": pk_start.isoformat(),
                        "suggested_end": pk_end.isoformat()
                    })

                # dropoff
                bdp = _time_bucket(dp_start.strftime("%H:%M"))
                base_dp = base + (0.05 if dr_pref.get(r["id"], {}).get(bdp, 0) > 0 else 0.0)
                col2 = _availability_conflicts(conn, driver_id=r["id"], starts_at=dp_start, ends_at=dp_end)
                if not col2:
                    drivers_dropoff.append({
                        "driver_id": r["id"], "full_name": r["full_name"],
                        "score": round(base_dp, 3),
                        "suggested_start": dp_start.isoformat(),
                        "suggested_end": dp_end.isoformat()
                    })

            drivers_pickup.sort(key=lambda x: x["score"], reverse=True)
            drivers_dropoff.sort(key=lambda x: x["score"], reverse=True)
            drivers_pickup = drivers_pickup[:5]
            drivers_dropoff = drivers_dropoff[:5]

    return jsonify({
        "therapy": therapy_candidates,
        "drivers_pickup": drivers_pickup,
        "drivers_dropoff": drivers_dropoff
    }), 200


def _softmax(x):
    m = max(x) if x else 0.0
    exps = [math.exp(v - m) for v in x]
    s = sum(exps) or 1.0
    return [v / s for v in exps]


def _score_ct_row(r):
    # prosta, działająca od ręki heurystyka
    # wagi możesz potem zgrać z modelem ML
    n = r.get("n_sessions", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5 * rec + 0.3 * done + 0.2 * min(1.0, n / 10.0) + 0.1 * min(1.0, mins / 600.0)


@app.get("/api/ai/recommend")
def ai_recommend():
    """
        Zwraca TOP propozycje terapeuty i kierowcy dla klienta + preferowane godziny.
        Używa wytrenowanych modeli AI, jeśli są dostępne.
        """
    cid = request.args.get("client_id", type=int)
    if not cid:
        return jsonify({"error": "client_id is required"}), 400

    with engine.begin() as conn:
        # TERAPEUCI
        q_ct = text("""
              SELECT f.therapist_id, t.full_name,
                     f.n_sessions, f.minutes_sum, f.done_ratio, f.days_since_last, f.recency_weight
              FROM v_ct_features f
              JOIN therapists t ON t.id=f.therapist_id AND t.active=true
              WHERE f.client_id=:cid
            """)
        ct_rows = [dict(r) for r in conn.execute(q_ct, {"cid": cid}).mappings().all()]

        # KIEROWCY
        q_cd = text("""
              SELECT f.driver_id, d.full_name,
                     f.n_runs, f.minutes_sum, f.done_ratio, f.days_since_last, f.recency_weight
              FROM v_cd_features f
              JOIN drivers d ON d.id=f.driver_id AND d.active=true
              WHERE f.client_id=:cid
            """)
        cd_rows = [dict(r) for r in conn.execute(q_cd, {"cid": cid}).mappings().all()]

        # Preferencje czasu (bez zmian)
        qtp = text("SELECT dow, hour, cnt FROM v_client_time_prefs WHERE client_id=:cid ORDER BY cnt DESC LIMIT 6")
        time_prefs = [dict(r) for r in conn.execute(qtp, {"cid": cid}).mappings().all()]

    # Użyj modelu AI do oceny terapeutów, jeśli jest wczytany
    if ct_model and ct_rows:
        features = ["n_sessions", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
        X_ct = pd.DataFrame(ct_rows)[features]
        # predict_proba zwraca prawdopodobieństwo dla klasy "1" (dobre dopasowanie)
        scores = ct_model.predict_proba(X_ct)[:, 1]
        for r, score in zip(ct_rows, scores):
            r["score"] = round(score, 4)
    else:  # Fallback do starej logiki, jeśli model nie jest dostępny
        for r in ct_rows:
            r["score"] = round(_score_ct_row(r), 4)

    # Użyj modelu AI do oceny kierowców, jeśli jest wczytany
    if cd_model and cd_rows:
        features = ["n_runs", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
        X_cd = pd.DataFrame(cd_rows)[features]
        scores = cd_model.predict_proba(X_cd)[:, 1]
        for r, score in zip(cd_rows, scores):
            r["score"] = round(score, 4)
    else:  # Fallback
        for r in cd_rows:
            r["score"] = round(_score_cd_row(r), 4)

    # Sortuj wyniki i zwróć TOP 5
    ct_rows.sort(key=lambda x: x["score"], reverse=True)
    cd_rows.sort(key=lambda x: x["score"], reverse=True)

    return jsonify({
        "therapists": ct_rows[:5],
        "drivers": cd_rows[:5],
        "time_prefs": time_prefs
    }), 200


@app.get("/api/clients")
@therapist_required
def list_clients_with_suo():
    mk = request.args.get("month") or datetime.now(TZ).strftime("%Y-%m")
    q = (request.args.get("q") or "").strip()
    therapist_id = request.args.get("therapist_id", type=int)
    include_inactive = request.args.get("include_inactive") in ("1", "true", "yes")

    where = []
    params = {"mk": mk}

    if not include_inactive:
        where.append("c.active IS TRUE")
    if q:
        where.append("c.full_name ILIKE :q")
        params["q"] = f"%{q}%"
    if therapist_id:
        where.append("""
                EXISTS (
                  SELECT 1 FROM schedule_slots s
                  WHERE s.client_id = c.id AND s.therapist_id = :tid AND s.kind = 'therapy'
                    AND to_char(s.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
                )
            """)
        params["tid"] = therapist_id

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    sql = f"""
        WITH used AS (
          SELECT client_id, minutes_used
          FROM suo_usage
          WHERE month_key = :mk
        )
        SELECT
          c.id AS client_id, c.full_name, c.phone, c.address, c.active,
          c.photo_url,  -- DODAJ TĘ LINIĘ
          EXISTS (SELECT 1 FROM client_unavailability cu WHERE cu.client_id = c.id) AS has_unavailability_plan,
          :mk AS month_key, a.minutes_quota,
          COALESCE(u.minutes_used, 0) AS minutes_used,
          CASE WHEN a.minutes_quota IS NULL THEN NULL
               ELSE a.minutes_quota - COALESCE(u.minutes_used, 0)
          END AS minutes_left,
          (a.minutes_quota IS NULL) AS needs_allocation
        FROM clients c
        LEFT JOIN used u ON u.client_id = c.id
        LEFT JOIN suo_allocations a ON a.client_id = c.id AND a.month_key = :mk
        {where_sql}
        ORDER BY c.full_name;
        """
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        return jsonify([dict(r) for r in rows]), 200


@app.delete("/api/clients/<int:cid>")
def delete_client(cid):
    """Trwale usuwa klienta i wszystkie jego powiązania (kaskadowo)."""
    with engine.begin() as conn:
        # Zawsze wykonuj twarde usuwanie
        res = conn.execute(text("DELETE FROM clients WHERE id=:id"), {"id": cid})

    if res.rowcount == 0:
        return jsonify({"error": "Client not found"}), 404

    # 204 No Content to standardowa, pusta odpowiedź po pomyślnym usunięciu
    return "", 204


@app.post("/api/clients")
def create_client():
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    sql = """
        INSERT INTO clients (full_name, phone, address,active)
        VALUES (:full_name, :phone, :address, COALESCE(:active,true))
        RETURNING id, full_name, phone, address, active;
        """
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {
                "full_name": full_name,
                "phone": (data.get("phone") or None),
                "address": (data.get("address") or None),
                "active": bool(data.get("active", True)),
            }).mappings().first()
            return jsonify(dict(row)), 201
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki klient już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409


@app.put("/api/clients/<int:cid>")
def update_client(cid):
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    sql = """
        UPDATE clients
           SET full_name = :full_name,
               phone     = :phone,
               address   = :address,
               active    = COALESCE(:active, true),
               photo_url = :photo_url
         WHERE id = :id
        RETURNING id, full_name, phone, address, active, photo_url;
        """
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {
                "id": cid,
                "full_name": full_name,
                "phone": (data.get("phone") or None),
                "address": (data.get("address") or None),
                "active": data.get("active", True),
                "photo_url": data.get("photo_url"),  # DODAJ TĘ LINIĘ
            }).mappings().first()
            if not row:
                return jsonify({"error": "Klient nie istnieje."}), 404
            return jsonify(dict(row)), 200
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki klient już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409


@app.route('/api/groups/<group_id>', methods=['GET'])
def get_package_group(group_id):
    """Pobiera pakiet na podstawie UUID group_id"""
    conn = None
    cur = None

    try:
        conn = psycopg2.connect(
            host='localhost',
            port='5432',
            database='suo',  # ZMIEŃ
            user='postgres',  # ZMIEŃ
            password='EDUQ'  # ZMIEŃ
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Pobierz wszystkie sloty należące do grupy (UUID)
        cur.execute("""
                SELECT 
                    id as slot_id,
                    group_id::text as group_id,
                    client_id,
                    kind,
                    therapist_id,
                    driver_id,
                    vehicle_id,
                    starts_at,
                    ends_at,
                    place_from,
                    place_to,
                    status,
                    distance_km
                FROM schedule_slots
                WHERE group_id = %s::uuid
                ORDER BY 
                    CASE kind 
                        WHEN 'pickup' THEN 1
                        WHEN 'therapy' THEN 2
                        WHEN 'dropoff' THEN 3
                        ELSE 4
                    END
            """, (group_id,))

        slots = cur.fetchall()

        if not slots:
            return jsonify({"error": "Pakiet nie znaleziony"}), 404

        # Podstawowe info z pierwszego slotu
        first = slots[0]
        result = {
            "group_id": first["group_id"],
            "client_id": first["client_id"],
            "status": first["status"],
            "label": None  # Możesz dodać label jeśli masz w bazie
        }

        # Rozdziel sloty według typu
        for slot in slots:
            if slot["kind"] == "therapy":
                result["therapy"] = {
                    "slot_id": slot["slot_id"],
                    "therapist_id": slot["therapist_id"],
                    "starts_at": slot["starts_at"].isoformat() if slot["starts_at"] else None,
                    "ends_at": slot["ends_at"].isoformat() if slot["ends_at"] else None,
                    "place": slot["place_to"],
                    "status": slot["status"]
                }
            elif slot["kind"] == "pickup":
                result["pickup"] = {
                    "slot_id": slot["slot_id"],
                    "driver_id": slot["driver_id"],
                    "vehicle_id": slot["vehicle_id"],
                    "starts_at": slot["starts_at"].isoformat() if slot["starts_at"] else None,
                    "ends_at": slot["ends_at"].isoformat() if slot["ends_at"] else None,
                    "from": slot["place_from"],
                    "to": slot["place_to"],
                    "status": slot["status"]
                }
            elif slot["kind"] == "dropoff":
                result["dropoff"] = {
                    "slot_id": slot["slot_id"],
                    "driver_id": slot["driver_id"],
                    "vehicle_id": slot["vehicle_id"],
                    "starts_at": slot["starts_at"].isoformat() if slot["starts_at"] else None,
                    "ends_at": slot["ends_at"].isoformat() if slot["ends_at"] else None,
                    "from": slot["place_from"],
                    "to": slot["place_to"],
                    "status": slot["status"]
                }

        return jsonify(result)

    except Exception as e:
        print(f"BŁĄD w get_package_group: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# === THERAPISTS ===
@app.get("/api/therapists")
def list_therapists():
    with SessionLocal() as s:
        therapists = (
            s.query(Therapist)
            .filter(Therapist.active == True)
            .order_by(Therapist.full_name)
            .all()
        )
        return jsonify([{
            "id": t.id,
            "full_name": t.full_name,
            "specialization": t.specialization,
            "phone": t.phone,
            "active": bool(t.active),
        } for t in therapists])


@app.post("/api/therapists")
def create_therapist():
    data = request.get_json(force=True)
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    sql = text("""
            INSERT INTO therapists (full_name, specialization, phone, active)
            VALUES (:full_name, :specialization, :phone, COALESCE(:active,true))
            RETURNING id, full_name, specialization, phone, active;
        """)
    try:
        with engine.begin() as conn:
            row = conn.execute(sql, {
                "full_name": full_name,
                "specialization": (data.get("specialization") or None),
                "phone": (data.get("phone") or None),
                "active": bool(data.get("active", True)),
            }).mappings().first()
            return jsonify(dict(row)), 201
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki terapeuta już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409


@app.put("/api/therapists/<int:tid>")
def update_therapist(tid):
    """Aktualizuje dane terapeuty."""
    with session_scope() as db_session:
        therapist = db_session.query(Therapist).filter_by(id=tid).first()
        if not therapist:
            return jsonify({"error": "Terapeuta nie istnieje."}), 404

        data = request.get_json(silent=True) or {}
        therapist.full_name = data.get("full_name", therapist.full_name)
        therapist.specialization = data.get("specialization", therapist.specialization)
        therapist.phone = data.get("phone", therapist.phone)
        therapist.active = data.get("active", therapist.active)
        try:
            session.commit()
            return jsonify({"id": therapist.id, "full_name": therapist.full_name}), 200
        except IntegrityError:
            session.rollback()
            return jsonify({"error": "Taki terapeuta już istnieje (imię i nazwisko)."}), 409


@app.delete("/api/therapists/<int:tid>")
def delete_therapist(tid):
    """Usuwa terapeutę."""
    with session_scope() as db_session:
        therapist = db_session.query(Therapist).filter_by(id=tid).first()
        if not therapist:
            return jsonify({"error": "Therapist not found"}), 404
        db_session.delete(therapist)
        db_session.commit()
        return "", 204


# === DRIVERS ===
# --- LISTA KIEROWCÓW (odporna na brak pola phone itd.) ---
@app.get("/api/drivers")
def list_drivers():
    with session_scope() as s:
        q = s.query(Driver)

        active_param = request.args.get("active")
        if active_param is not None:
            val = str(active_param).strip().lower()
            if val in ("1", "true", "t", "yes", "y"):
                q = q.filter(Driver.active.is_(True))
            elif val in ("0", "false", "f", "no", "n"):
                q = q.filter(Driver.active.is_(False))
            else:
                pass

        drivers = q.order_by(Driver.full_name).all()

        out = []
        for d in drivers:
            out.append({
                "id": d.id,
                "full_name": d.full_name,
                # jeżeli model nie ma 'phone', to None
                "phone": getattr(d, "phone", None),
                "active": getattr(d, "active", True),
            })
        return jsonify(out)


@app.post("/api/drivers")
def create_driver():
    """Tworzy nowego kierowcę."""
    data = request.get_json(silent=True) or {}
    if not data or not data.get("full_name"):
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    with session_scope() as db_session:
        new_driver = Driver(
            full_name=data["full_name"],
            phone=data.get("phone"),
            active=data.get("active", True)
        )
        db_session.add(new_driver)
        try:
            db_session.commit()
            return jsonify({"id": new_driver.id, "full_name": new_driver.full_name}), 201
        except IntegrityError:
            db_session.rollback()
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409


@app.put("/api/drivers/<int:did>")
def update_driver(did):
    """Aktualizuje dane kierowcy."""
    with session_scope() as db_session:
        driver = db_session.query(Driver).filter_by(id=did).first()
        if not driver:
            return jsonify({"error": "Kierowca nie istnieje."}), 404

        data = request.get_json(silent=True) or {}
        driver.full_name = data.get("full_name", driver.full_name)
        driver.phone = data.get("phone", driver.phone)
        driver.active = data.get("active", driver.active)
        try:
            db_session.commit()
            return jsonify({"id": driver.id, "full_name": driver.full_name}), 200
        except IntegrityError:
            db_session.rollback()
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409


@app.delete("/api/drivers/<int:did>")
def delete_driver(did):
    """Usuwa kierowcę."""
    with session_scope() as db_session:
        driver = db_session.query(Driver).filter_by(id=did).first()
        if not driver:
            return jsonify({"error": "Driver not found"}), 404
        db_session.delete(driver)
        db_session.commit()
        return "", 204


# === CLIENT UNAVAILABILITY ===

@app.get("/api/clients/<int:client_id>/unavailability")
def get_client_unavailability(client_id):
    """Pobiera wszystkie wpisy o niedostępności dla danego klienta."""
    sql = text("""
            SELECT id, day_of_week, start_time, end_time, notes 
            FROM client_unavailability 
            WHERE client_id = :cid 
            ORDER BY day_of_week, start_time
        """)
    with engine.begin() as conn:
        rows = conn.execute(sql, {"cid": client_id}).mappings().all()
        # Konwertuj obiekty czasu na stringi dla łatwiejszej obsługi w JSON
        results = [
            {**row, 'start_time': row['start_time'].strftime('%H:%M'), 'end_time': row['end_time'].strftime('%H:%M')}
            for row in rows
        ]
        return jsonify(results)


@app.post("/api/clients/<int:client_id>/unavailability")
def add_client_unavailability(client_id):
    """Dodaje nowy wpis o niedostępności."""
    data = request.get_json(silent=True) or {}
    required = ['day_of_week', 'start_time', 'end_time']
    if not all(k in data for k in required):
        return jsonify({"error": "Brak wymaganych pól (dzień, start, koniec)."}), 400

    sql = text("""
            INSERT INTO client_unavailability (client_id, day_of_week, start_time, end_time, notes)
            VALUES (:cid, :dow, :start, :end, :notes)
            RETURNING id
        """)
    with engine.begin() as conn:
        new_id = conn.execute(sql, {
            "cid": client_id,
            "dow": data['day_of_week'],
            "start": data['start_time'],
            "end": data['end_time'],
            "notes": data.get('notes')
        }).scalar_one()
    return jsonify({"id": new_id, **data}), 201


@app.delete("/api/unavailability/<int:entry_id>")
def delete_unavailability(entry_id):
    """Usuwa konkretny wpis o niedostępności."""
    sql = text("DELETE FROM client_unavailability WHERE id = :id")
    with engine.begin() as conn:
        result = conn.execute(sql, {"id": entry_id})
    if result.rowcount == 0:
        return jsonify({"error": "Nie znaleziono wpisu."}), 404
    return "", 204


@app.post("/api/ai/plan-day")
def ai_plan_day():
    """
        Body:
        {
          "date": "2025-08-21",
          "clients": [1,2,3],
          "slot_template": {"start":"09:00","end":"10:00"}  # opcjonalnie
        }
        """
    data = request.get_json(silent=True) or {}
    date = data.get("date")
    clients = data.get("clients") or []
    if not date or not clients:
        return jsonify({"error": "date and clients[] required"}), 400

    # dla każdego klienta: TOP1 terapeuta i TOP1 kierowca z /api/ai/recommend
    # + szybka kontrola kolizji godzinowej (tu: ta sama godzina)
    plans = []
    hour_start = 9
    for cid in clients:
        rec = app.test_client().get(f"/api/ai/recommend?client_id={cid}&date={date}").get_json()
        th = (rec.get("therapists") or [{}])[0]
        dr = (rec.get("drivers") or [{}])[0]
        start = f"{date}T{str(hour_start).zfill(2)}:00:00"
        end = f"{date}T{str(hour_start + 1).zfill(2)}:00:00"
        plans.append({
            "client_id": cid,
            "therapist_id": th.get("therapist_id"),
            "driver_id_pickup": dr.get("driver_id"),
            "driver_id_dropoff": dr.get("driver_id"),
            "starts_at": start, "ends_at": end,
            "score_therapist": th.get("score"), "score_driver": dr.get("score")
        })
        hour_start += 1  # prosta sekwencja – zamienisz na CP-SAT
    return jsonify({"date": date, "proposals": plans}), 200


@app.get("/api/groups/<string:gid>")
def get_group(gid):
    """Pobiera dane pojedynczego pakietu indywidualnego do edycji."""

    # --- POCZĄTEK POPRAWKI ---
    # Używamy standardowej funkcji CAST() zamiast składni ::uuid przy parametrze
    sql = text("""
            SELECT
                eg.client_id, eg.label, ss.kind, ss.therapist_id, ss.driver_id,
                ss.vehicle_id, ss.starts_at, ss.ends_at, ss.place_from,
                ss.place_to, ss.status
            FROM event_groups eg
            JOIN schedule_slots ss ON eg.id = ss.group_id::uuid
            WHERE ss.id = %(slot_id)s
        """)
    # --- KONIEC POPRAWKI ---

    with engine.begin() as conn:
        rows = conn.execute(sql, {"gid": gid}).mappings().all()

    if not rows:
        return jsonify({"error": "Pakiet nie został znaleziony."}), 404

    result = {
        "group_id": gid,
        "client_id": rows[0]['client_id'],
        "label": rows[0]['label'],
        "status": rows[0]['status'],
        "therapy": None, "pickup": None, "dropoff": None
    }

    for row in rows:
        slot_data = {
            "starts_at": row['starts_at'].isoformat() if row['starts_at'] else None,
            "ends_at": row['ends_at'].isoformat() if row['ends_at'] else None,
            "from": row['place_from'],
            "to": row['place_to']
        }
        if row['kind'] == 'therapy':
            result['therapy'] = {**slot_data, "therapist_id": row['therapist_id'], "place": row['place_to']}
        elif row['kind'] == 'pickup':
            result['pickup'] = {**slot_data, "driver_id": row['driver_id'], "vehicle_id": row['vehicle_id']}
        elif row['kind'] == 'dropoff':
            result['dropoff'] = {**slot_data, "driver_id": row['driver_id'], "vehicle_id": row['vehicle_id']}

    return jsonify(result)


@app.delete("/api/groups/<string:gid>")
def delete_group(gid):
    """Usuwa cały pakiet indywidualny (rekord z event_groups i kaskadowo sloty)."""
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM event_groups WHERE id = CAST(:gid AS UUID)"), {"gid": gid})

    if result.rowcount == 0:
        return jsonify({"error": "Pakiet nie został znaleziony lub już został usunięty."}), 404

    return jsonify({"message": "Pakiet został pomyślnie usunięty."}), 200


@app.put("/api/groups/<string:gid>")
def update_group(gid):
    data = request.get_json(silent=True) or {}
    label = data.get("label")
    status = data.get("status", "planned")
    therapy = data.get("therapy")
    pickup = data.get("pickup")
    dropoff = data.get("dropoff")

    # NOWA, LEPSZA WALIDACJA DANYCH
    if not all(k in (therapy or {}) for k in ["therapist_id", "starts_at", "ends_at"]):
        return jsonify({"error": "Brak kompletnych danych terapii (terapeuta, start, koniec)."}), 400
    # KONIEC NOWEJ WALIDACJI

    try:
        with engine.begin() as conn:
            ok = conn.execute(text("SELECT 1 FROM event_groups WHERE id=:gid"), {"gid": gid}).scalar()
            if not ok: return jsonify({"error": "Nie znaleziono grupy."}), 404

            conn.execute(text("UPDATE event_groups SET label=:label WHERE id=:gid"), {"label": label, "gid": gid})

            ts = datetime.fromisoformat(therapy["starts_at"]).replace(tzinfo=TZ)
            te = datetime.fromisoformat(therapy["ends_at"]).replace(tzinfo=TZ)
            session_id = ensure_shared_session_id_for_therapist(conn, int(therapy["therapist_id"]), ts, te)

            ex = conn.execute(text("SELECT id FROM schedule_slots WHERE group_id=:gid AND kind='therapy' LIMIT 1"),
                              {"gid": gid}).mappings().first()
            if ex:
                conn.execute(text("""
                        UPDATE schedule_slots SET therapist_id=:tid, starts_at=:s, ends_at=:e, place_to=:place, status=:status, session_id=:sid WHERE id=:id
                    """), {"tid": therapy["therapist_id"], "s": ts, "e": te, "place": therapy.get("place"),
                           "status": status, "sid": session_id, "id": ex["id"]})
            else:
                conn.execute(text("""
                        INSERT INTO schedule_slots (group_id, client_id, therapist_id, kind, starts_at, ends_at, place_to, status, session_id)
                        SELECT :gid, client_id, :tid, 'therapy', :s, :e, :place, :status, :sid FROM schedule_slots WHERE group_id=:gid LIMIT 1
                    """), {"gid": gid, "tid": therapy["therapist_id"], "s": ts, "e": te, "place": therapy.get("place"),
                           "status": status, "sid": session_id})

            # POPRAWKA: Definicja funkcji przeniesiona na właściwy poziom
            def upsert_run(kind, block):
                ex = conn.execute(text("SELECT id FROM schedule_slots WHERE group_id=:gid AND kind=:kind LIMIT 1"),
                                  {"gid": gid, "kind": kind}).mappings().first()

                if block is None:
                    if ex: conn.execute(text("DELETE FROM schedule_slots WHERE id=:id"), {"id": ex["id"]})
                    return

                # POPRAWKA: Oblicz dystans PRZED tworzeniem payload
                distance = get_route_distance(block.get("from"), block.get("to"))

                s = datetime.fromisoformat(block["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(block["ends_at"]).replace(tzinfo=TZ)

                payload = {
                    "did": block["driver_id"],
                    "veh": block.get("vehicle_id"),
                    "s": s,
                    "e": e,
                    "from": block.get("from"),
                    "to": block.get("to"),
                    "status": status,
                    "gid": gid,
                    "kind": kind,
                    "distance": distance
                }

                if ex:
                    conn.execute(text("""
                            UPDATE schedule_slots 
                            SET driver_id=:did, vehicle_id=:veh, starts_at=:s, ends_at=:e, 
                                place_from=:from, place_to=:to, status=:status, 
                                distance_km=:distance
                            WHERE id=:id
                        """), {**payload, "id": ex["id"]})
                else:
                    conn.execute(text("""
                            INSERT INTO schedule_slots 
                            (group_id, client_id, driver_id, vehicle_id, kind, starts_at, ends_at, 
                             place_from, place_to, status, distance_km)
                            SELECT :gid, client_id, :did, :veh, :kind, :s, :e, 
                                   :from, :to, :status, :distance 
                            FROM schedule_slots 
                            WHERE group_id=:gid AND kind='therapy' LIMIT 1
                        """), payload)

            upsert_run("pickup", pickup)
            upsert_run("dropoff", dropoff)

        return jsonify({"ok": True, "group_id": gid}), 200
    except IntegrityError as e:
        if getattr(e.orig, "pgcode", None) == errorcodes.FOREIGN_KEY_VIOLATION:
            return jsonify({"error": "Naruszenie klucza obcego – sprawdź ID osób/pojazdu."}), 400
        return jsonify({"error": "Błąd bazy", "details": str(e.orig)}), 400


# === TUS API ENDPOINTS ===

def get_semester_dates(school_year_start, semester):
    """Zwraca datę początkową i końcową dla danego semestru roku szkolnego."""
    if semester == 1:  # I Półrocze (Wrzesień - Styczeń)
        start_date = date(school_year_start, 9, 1)
        end_date = date(school_year_start + 1, 2, 1)  # Kończy się przed 1 lutego
    elif semester == 2:  # II Półrocze (Luty - Czerwiec)
        start_date = date(school_year_start + 1, 2, 1)
        end_date = date(school_year_start + 1, 7, 1)  # Kończy się przed 1 lipca
    else:
        raise ValueError("Semester must be 1 or 2")
    return start_date, end_date


@app.get("/tus")
def tus_page():
    return app.send_static_file("tus.html")


@app.get("/api/tus/groups")
@therapist_required
def get_tus_groups():
    with session_scope() as db_session:
        groups = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.therapist),
            joinedload(TUSGroup.members),
            joinedload(TUSGroup.sessions)
        ).order_by(TUSGroup.name).all()

        result = [{
            "id": group.id,
            "name": group.name,
            "therapist_id": group.therapist.id if group.therapist else None,
            "therapist_name": group.therapist.full_name if group.therapist else "Brak",
            "member_count": len(group.members),
            "total_bonuses": sum(s.bonuses_awarded for s in group.sessions if s.bonuses_awarded)
        } for group in groups]
        return jsonify(result)


@app.post("/api/tus/groups")
def create_tus_group():
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("therapist_id"):
        return jsonify({"error": "Nazwa grupy i terapeuta są wymagani."}), 400

    with session_scope() as db_session:
        if db_session.query(TUSGroup).filter_by(name=data["name"]).first():
            return jsonify({"error": f"Grupa o nazwie '{data['name']}' już istnieje."}), 409

        client_ids = [int(cid) for cid in data.get("client_ids", []) if cid is not None]
        members = []
        if client_ids:
            members = db_session.query(Client).filter(Client.id.in_(client_ids)).all()

        new_group = TUSGroup(
            name=data["name"],
            therapist_id=data["therapist_id"],
            assistant_therapist_id=data.get("assistant_therapist_id"),
            members=members  # POPRAWKA: To zadziała dzięki poprawionej relacji w modelu
        )
        db_session.add(new_group)
        db_session.flush()  # Aby uzyskać ID nowej grupy
        return jsonify({"id": new_group.id, "name": new_group.name}), 201


@app.put("/api/tus/groups/<int:group_id>")
def update_tus_group(group_id):
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("therapist_id"):
        return jsonify({"error": "Nazwa grupy i terapeuta są wymagani."}), 400

    with session_scope() as db_session:
        group = db_session.get(TUSGroup, group_id)
        if not group:
            return jsonify({"error": "Nie znaleziono grupy."}), 404

        # Sprawdzenie unikalności nowej nazwy
        if db_session.query(TUSGroup).filter(TUSGroup.name == data["name"], TUSGroup.id != group_id).first():
            return jsonify({"error": f"Grupa o nazwie '{data['name']}' już istnieje."}), 409

        group.name = data["name"]
        group.therapist_id = data["therapist_id"]
        group.assistant_therapist_id = data.get("assistant_therapist_id")

        client_ids = [int(cid) for cid in data.get("client_ids", []) if cid is not None]
        if client_ids:
            group.members = db_session.query(Client).filter(Client.id.in_(client_ids)).all()
        else:
            group.members = []

        return jsonify({"id": group.id, "name": group.name}), 200


@app.post("/api/tus/sessions")
def create_tus_session():
    data = request.get_json(silent=True) or {}
    print(f"=== ROZPOCZĘCIE TWORZENIA SESJI (NOWA LOGIKA TEMATU I OBECNOŚCI) ===")
    print(f"Otrzymane dane: {data}")

    try:
        group_id = int(data["group_id"])

        # Pobieramy tytuł tematu zamiast ID
        topic_title = (data.get("topic_title") or "").strip()
        if not topic_title:
            return jsonify({"error": "Pole 'topic_title' jest wymagane."}), 400

        session_date_str = data["session_date"]  # Oczekiwany format: "YYYY-MM-DDTHH:MM:SS"

        # Bezpieczne parsowanie daty i czasu
        try:
            dt_obj = datetime.fromisoformat(session_date_str)
            sess_date = dt_obj.date()
            sess_time = dt_obj.time()
        except (ValueError, TypeError):
            return jsonify({"error": f"Nieprawidłowy format daty/godziny: {session_date_str}"}), 400

        behavior_ids = [int(bid) for bid in data.get("behavior_ids", []) if bid]
        if len(behavior_ids) > 4:
            return jsonify({"error": "Można wybrać maksymalnie 4 zachowania."}), 400
            
        # --- NOWA SEKCJA 1: Pobranie listy obecności ---
        # Tworzymy zbiór (set) dla szybszego sprawdzania
        present_client_ids_list = [int(cid) for cid in data.get("present_client_ids", []) if cid]
        present_client_ids_set = set(present_client_ids_list)
        print(f"Otrzymano ID {len(present_client_ids_set)} obecnych uczestników.")
        # --- KONIEC NOWEJ SEKCJI 1 ---

        with session_scope() as db_session:
            # Logika znajdowania lub tworzenia tematu
            topic = db_session.query(TUSTopic).filter(func.lower(TUSTopic.title) == func.lower(topic_title)).first()

            if not topic:
                print(f"Temat '{topic_title}' nie istnieje. Tworzę nowy wpis.")
                topic = TUSTopic(title=topic_title)
                db_session.add(topic)
                db_session.flush()  
            else:
                print(f"Znaleziono istniejący temat: ID={topic.id}, Tytuł='{topic.title}'")

            topic_id_for_session = topic.id

            # Tworzymy główny obiekt sesji
            new_session = TUSSession(
                group_id=group_id,
                topic_id=topic_id_for_session,
                session_date=sess_date,
                session_time=sess_time,
            )
            db_session.add(new_session)
            db_session.flush()

            # Zapisz powiązane zachowania (bez zmian)
            if behavior_ids:
                behaviors_map = {b.id: b.default_max_points for b in
                                 db_session.query(TUSBehavior).filter(TUSBehavior.id.in_(behavior_ids)).all()}

                for b_id in behavior_ids:
                    session_behavior = TUSSessionBehavior(
                        session_id=new_session.id,
                        behavior_id=b_id,
                        max_points=behaviors_map.get(b_id, 3)
                    )
                    db_session.add(session_behavior)
                    
            # --- NOWA SEKCJA 2: Zapisywanie obecności ---
            # Pobieramy wszystkich członków, którzy SĄ przypisani do tej grupy
            all_group_members = db_session.query(TUSGroupMember).filter(TUSGroupMember.group_id == group_id).all()
            
            if not all_group_members:
                print(f"Ostrzeżenie: Grupa ID={group_id} nie ma żadnych członków. Nie można zapisać obecności.")
            else:
                print(f"Znaleziono {len(all_group_members)} członków w grupie. Zapisuję obecność...")
                
            attendance_records = []
            # Tworzymy wpis obecności dla KAŻDEGO członka grupy
            for member_link in all_group_members:
                is_present = member_link.client_id in present_client_ids_set
                
                new_attendance_record = TUSSessionAttendance(
                    session_id=new_session.id,
                    client_id=member_link.client_id,
                    is_present=is_present  # Zapisz True lub False
                )
                attendance_records.append(new_attendance_record)
                
                if is_present:
                    print(f"  -> Uczestnik ID={member_link.client_id} OBECNY")
                else:
                    print(f"  -> Uczestnik ID={member_link.client_id} NIEOBECNY")

            if attendance_records:
                db_session.add_all(attendance_records)
                print("Zapisano obecność dla wszystkich członków grupy.")
            # --- KONIEC NOWEJ SEKCJI 2 ---

            print(
                f"UTWORZONO SESJĘ: ID={new_session.id}, Data={new_session.session_date}, Czas={new_session.session_time}, TopicID={topic_id_for_session}")
            return jsonify({"id": new_session.id}), 201

    except (KeyError, ValueError, TypeError) as e:
        print(f"BŁĄD: Nieprawidłowe lub brakujące dane w zapytaniu. Szczegóły: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Nieprawidłowe lub brakujące dane w zapytaniu.", "details": str(e)}), 400
    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Wewnętrzny błąd serwera."}), 500

@app.put("/api/tus/sessions/<int:session_id>")
def update_tus_session(session_id):
    data = request.get_json(silent=True) or {}
    with session_scope() as db_session:
        s = db_session.get(TUSSession, session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404

        if "topic_id" in data: s.topic_id = data["topic_id"]
        if "bonuses_awarded" in data: s.bonuses_awarded = int(data["bonuses_awarded"])

        # POPRAWKA: Poprawiona logika obsługi daty i czasu
        if "session_date" in data:  # Oczekuje formatu "YYYY-MM-DDTHH:MM:SS"
            try:
                dt = datetime.fromisoformat(data["session_date"])
                s.session_date = dt.date()
                s.session_time = dt.time()
            except (ValueError, TypeError):
                return jsonify({"error": "Nieprawidłowy format daty."}), 400

        return jsonify({"ok": True}), 200


@app.delete("/api/tus/sessions/<int:session_id>")
def delete_tus_session(session_id):
    # Odczytujemy decyzję użytkownika z parametrów URL
    delete_all_bonuses = request.args.get('delete_all_bonuses', 'false').lower() == 'true'

    with session_scope() as db_session:
        # Znajdź sesję, którą chcemy usunąć
        session_to_delete = db_session.get(TUSSession, session_id)
        if not session_to_delete:
            return jsonify({"error": "Session not found"}), 404

        group_id = session_to_delete.group_id

        # --- NOWA LOGIKA DECYZYJNA ---
        if delete_all_bonuses:
            # Użytkownik wybrał "TAK": usuń WSZYSTKIE bonusy w tej grupie
            print(f"DIAGNOSTYKA: Usuwanie wszystkich bonusów dla grupy ID: {group_id}")

            # 1. Usuń bonusy ogólne
            db_session.query(TUSGeneralBonus).filter(TUSGeneralBonus.group_id == group_id).delete()

            # 2. Usuń bonusy sesyjne (ze wszystkich sesji w tej grupie)
            session_ids_in_group = db_session.query(TUSSession.id).filter(TUSSession.group_id == group_id)
            db_session.query(TUSMemberBonus).filter(TUSMemberBonus.session_id.in_(session_ids_in_group)).delete()

        # Niezależnie od decyzji, ZAWSZE usuwamy sesję.
        # Jeśli użytkownik wybrał "NIE", kaskada w bazie danych usunie
        # bonusy i punkty TYLKO dla tej jednej usuwanej sesji.
        db_session.delete(session_to_delete)

    return jsonify({"ok": True}), 200


@app.put("/api/tus/groups/<int:gid>/target")
def tus_update_targets(gid):
    data = request.get_json(silent=True) or {}
    try:
        school_year_start = int(data["school_year_start"])
        semester = int(data["semester"])
        points = int(data["points"])
        reward = (data.get("reward") or "").strip()
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "Brakujące lub nieprawidłowe dane."}), 400

    with session_scope() as db_session:
        target = db_session.query(TUSGroupTarget).filter_by(
            group_id=gid,
            school_year_start=school_year_start,
            semester=semester
        ).first()

        if target:  # Aktualizuj istniejący
            target.target_points = points
            target.reward = reward
        else:  # Stwórz nowy
            # --- POCZĄTEK POPRAWKI ---
            target = TUSGroupTarget()  # Stwórz pusty obiekt
            # Ustaw wartości jako atrybuty
            target.group_id = gid
            target.school_year_start = school_year_start
            target.semester = semester
            target.target_points = points
            target.reward = reward
            db_session.add(target)
            # --- KONIEC POPRAWKI ---

    return jsonify({"ok": True})


@app.get("/api/tus/groups/<int:group_id>")
def get_tus_group_details(group_id: int):
    with session_scope() as db_session:
        group = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.therapist),
            joinedload(TUSGroup.assistant_therapist),
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client),
            # Use 'selectinload' for efficient and correct loading of the session list
            selectinload(TUSGroup.sessions).joinedload(TUSSession.topic)
        ).filter(TUSGroup.id == group_id).first()

        if not group:
            return jsonify({"error": "Group not found"}), 404

        # Manually build the JSON response to guarantee correct date format
        sessions_json = sorted([
            {
                "id": s.id,
                "session_date": s.session_date.isoformat() if s.session_date else None,
                "session_time": s.session_time.strftime('%H:%M:%S') if s.session_time else None,
                "topic_title": s.topic.title if s.topic else "bez tematu",
                "bonuses_awarded": s.bonuses_awarded or 0
            } for s in group.sessions
        ], key=lambda x: (x.get('session_date') or "", x.get('session_time') or ""), reverse=True)

        members_json = [{"id": m.id, "full_name": m.full_name} for m in group.members]

        group_data = {
            "id": group.id,
            "name": group.name,
            "therapist_id": group.therapist_id,
            "therapist_name": group.therapist.full_name if group.therapist else "Brak",
            "assistant_therapist_id": group.assistant_therapist_id,
            "assistant_therapist_name": group.assistant_therapist.full_name if group.assistant_therapist else None,
            "members": members_json,
            "sessions": sessions_json,
            "schedule_days": [d.isoformat() for d in group.schedule_days] if group.schedule_days else []
        }

        return jsonify(group_data)


@app.get("/api/tus/groups/<int:gid>/bonuses")
def tus_group_bonuses(gid):
    """Zwraca podsumowanie punktów dla obu semestrów danego roku szkolnego."""
    try:
        school_year_start = int(request.args.get("school_year_start", datetime.now(TZ).year))
    except ValueError:
        return jsonify({"error": "Nieprawidłowy rok szkolny"}), 400

    results = {}
    with session_scope() as db_session:
        group = db_session.get(TUSGroup, gid)
        if not group: return jsonify({"error": "Not found"}), 404

        for semester in [1, 2]:
            start_date, end_date = get_semester_dates(school_year_start, semester)

            # Pobierz cel dla tego semestru
            target_obj = db_session.query(TUSGroupTarget).filter_by(
                group_id=gid, school_year_start=school_year_start, semester=semester
            ).first()

            # Zlicz punkty bonusowe w zakresie dat
            session_bonus_q = select(func.sum(TUSMemberBonus.points)).join(TUSSession).where(
                TUSSession.group_id == gid, TUSSession.session_date.between(start_date, end_date)
            )
            general_bonus_q = select(func.sum(TUSGeneralBonus.points)).where(
                TUSGeneralBonus.group_id == gid, TUSGeneralBonus.awarded_at.between(start_date, end_date)
            )
            session_pts = db_session.execute(session_bonus_q).scalar() or 0
            general_pts = db_session.execute(general_bonus_q).scalar() or 0
            total_collected = int(session_pts) + int(general_pts)

            results[f"semester_{semester}"] = {
                "target_points": target_obj.target_points if target_obj else 0,
                "reward": target_obj.reward if target_obj else "Brak",
                "points_collected": total_collected,
                "points_remaining": max(0, (target_obj.target_points if target_obj else 0) - total_collected)
            }

    return jsonify({
        "school_year_start": school_year_start,
        "school_year_label": f"{school_year_start}/{school_year_start + 1}",
        **results
    })


@app.post("/api/tus/member-bonuses")
def add_member_bonus():
    data = request.get_json(silent=True) or {}
    try:
        session_id = int(data.get("session_id"))
        client_id = int(data.get("client_id"))
        points = int(data.get("points"))
    except (TypeError, ValueError):
        return jsonify({"error": "session_id, client_id, points (int) są wymagane"}), 400
    if points < 0:
        return jsonify({"error": "points >= 0"}), 400

    with engine.begin() as conn:
        # 1) sprawdź sesję i ustal group_id
        row = conn.execute(text("SELECT id, group_id FROM tus_sessions WHERE id=:sid"),
                           {"sid": session_id}).mappings().first()
        if not row:
            return jsonify({"error": "Sesja nie istnieje"}), 404
        gid = row["group_id"]

        # 2) sprawdź członkostwo klienta w grupie
        member = conn.execute(text("""
                SELECT 1 FROM tus_group_members
                WHERE group_id=:gid AND client_id=:cid
            """), {"gid": gid, "cid": client_id}).scalar()
        if not member:
            return jsonify({"error": "Klient nie należy do tej grupy"}), 400

        # 3) wstaw bonus
        new_id = conn.execute(text("""
                INSERT INTO tus_member_bonuses (session_id, client_id, points)
                VALUES (:sid, :cid, :pts)
                RETURNING id
            """), {"sid": session_id, "cid": client_id, "pts": points}).scalar_one()

    return jsonify({"id": new_id, "ok": True}), 201


def _half_bounds(year: int, half: int):
    if half == 1:
        a = datetime(year, 1, 1, tzinfo=TZ);
        b = datetime(year, 7, 1, tzinfo=TZ)
    else:
        a = datetime(year, 7, 1, tzinfo=TZ);
        b = datetime(year + 1, 1, 1, tzinfo=TZ)
    return a, b


# CRUD dla tematów (prosty przykład)
@app.get("/api/tus/topics")
def get_tus_topics():
    with session_scope() as db_session:
        topics = db_session.query(TUSTopic).all()
        result = [{"id": t.id, "title": t.title} for t in topics]
        return jsonify(result)


@app.post("/api/tus/topics")
def create_tus_topic():
    data = request.get_json(silent=True) or {}

    with session_scope() as db_session:
        try:
            new_topic = TUSTopic(title=data["title"])
            db_session.add(new_topic)
            db_session.flush()  # To jest potrzebne, aby uzyskać ID przed końcem transakcji

            result = {"id": new_topic.id, "title": new_topic.title}
            return jsonify(result), 201

        except IntegrityError:
            # Rollback i close są obsługiwane automatycznie przez session_scope
            return jsonify({"error": "Topic with this title already exists"}), 409


@app.get("/api/tus/behaviors")
def get_behaviors():
    with Session() as s:
        rows = s.query(TUSBehavior).filter_by(active=True).order_by(TUSBehavior.title).all()
        return jsonify([{"id": b.id, "title": b.title, "default_max_points": b.default_max_points} for b in rows])


@app.post("/api/tus/behaviors")
def create_behavior():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    dmp = int(data.get("default_max_points") or 3)
    if not title:
        return jsonify({"error": "title required"}), 400
    with Session() as s:
        b = TUSBehavior(title=title, default_max_points=dmp)
        s.add(b)
        try:
            s.commit()
            return jsonify({"id": b.id, "title": b.title, "default_max_points": b.default_max_points}), 201
        except IntegrityError:
            s.rollback()
            return jsonify({"error": "behavior already exists"}), 409


@app.delete("/api/tus/behaviors/<int:bid>")
def delete_behavior(bid):
    with Session() as s:
        b = s.query(TUSBehavior).filter_by(id=bid).first()
        if not b: return "", 204
        b.active = False
        s.commit()
        return "", 204


@app.get("/api/tus/sessions/<int:sid>/behaviors")
def session_behaviors(sid):
    with engine.begin() as conn:
        q = text("""
              SELECT sb.id, sb.behavior_id, b.title, sb.max_points
              FROM tus_session_behaviors sb
              JOIN tus_behaviors b ON b.id=sb.behavior_id
              WHERE sb.session_id=:sid
              ORDER BY b.title
            """)
        rows = conn.execute(q, {"sid": sid}).mappings().all()
        return jsonify([dict(r) for r in rows])


@app.post("/api/tus/sessions/<int:sid>/behaviors")
def set_session_behaviors(sid):
    """
        Body: { behaviors: [ {behavior_id, max_points?}, ... ] }  # max 4
        """
    data = request.get_json(silent=True) or {}
    items = data.get("behaviors") or []
    if len(items) > 4:
        return jsonify({"error": "max 4 behaviors per session"}), 400
    with engine.begin() as conn:
        # wyczyść i wstaw
        conn.execute(text("DELETE FROM tus_session_behaviors WHERE session_id=:sid"), {"sid": sid})
        for it in items:
            bid = int(it["behavior_id"])
            mp = int(it.get("max_points", 3))
            conn.execute(text("""
                  INSERT INTO tus_session_behaviors(session_id, behavior_id, max_points)
                  VALUES (:sid, :bid, :mp)
                """), {"sid": sid, "bid": bid, "mp": mp})
    return jsonify({"ok": True}), 200


@app.get("/api/tus/sessions/<int:sid>/scores")
def get_session_scores(sid):
    with engine.begin() as conn:
        # behaviors
        beh = conn.execute(text("""
              SELECT sb.behavior_id, b.title, sb.max_points
              FROM tus_session_behaviors sb
              JOIN tus_behaviors b ON b.id=sb.behavior_id
              WHERE sb.session_id=:sid
              ORDER BY b.title
            """), {"sid": sid}).mappings().all()

        # members of group owning this session
        grp = conn.execute(text("""
              SELECT group_id FROM tus_sessions WHERE id=:sid
            """), {"sid": sid}).scalar()
        members = conn.execute(text("""
              SELECT c.id, c.full_name
              FROM tus_groups g
              JOIN tus_group_members gm ON gm.group_id=g.id
              JOIN clients c ON c.id=gm.client_id
              WHERE g.id=:gid
              ORDER BY c.full_name
            """), {"gid": grp}).mappings().all()

        # scores
        sc_rows = conn.execute(text("""
              SELECT client_id, behavior_id, points
              FROM tus_session_member_scores
              WHERE session_id=:sid
            """), {"sid": sid}).mappings().all()
        scores = {}
        for r in sc_rows:
            scores.setdefault(r["client_id"], {})[r["behavior_id"]] = r["points"]

        # partial rewards
        rw = conn.execute(text("""
              SELECT client_id, awarded, note, points FROM tus_session_partial_rewards
              WHERE session_id=:sid
            """), {"sid": sid}).mappings().all()
        rewards = {r["client_id"]: {"awarded": r["awarded"], "note": r["note"], "points": r["points"]} for r in rw}

        return jsonify({
            "behaviors": [dict(b) for b in beh],
            "members": [dict(m) for m in members],
            "scores": scores,
            "rewards": rewards
        })


@app.post("/api/tus/sessions/<int:sid>/scores")
def save_session_scores(sid):
    """
        Body:
        {
          "scores":[
            {"client_id":1, "items":[{"behavior_id":11,"points":2}, ...], "partial_reward":{"awarded":true,"note":"..." }},
            ...
          ]
        }
        """
    data = request.get_json(silent=True) or {}
    items = data.get("scores") or []
    # pobierz limity max_points
    with engine.begin() as conn:
        limits = {r["behavior_id"]: r["max_points"] for r in conn.execute(text("""
                SELECT behavior_id, max_points FROM tus_session_behaviors WHERE session_id=:sid
            """), {"sid": sid}).mappings().all()}
        for row in items:
            cid = int(row["client_id"])
            for it in (row.get("items") or []):
                bid = int(it["behavior_id"])
                pts = int(it.get("points", 0))
                if bid not in limits:
                    return jsonify({"error": f"behavior {bid} not attached to session"}), 400
                if pts < 0 or pts > limits[bid]:
                    return jsonify({"error": f"points {pts} out of range for behavior {bid} (max {limits[bid]})"}), 400
                # UPSERT
                conn.execute(text("""
                      INSERT INTO tus_session_member_scores(session_id, client_id, behavior_id, points)
                      VALUES (:sid,:cid,:bid,:pts)
                      ON CONFLICT (session_id, client_id, behavior_id)
                      DO UPDATE SET points = EXCLUDED.points
                    """), {"sid": sid, "cid": cid, "bid": bid, "pts": pts})

            # partial reward
            pr = row.get("partial_reward") or {}
            if pr:
                conn.execute(text("""
                      INSERT INTO tus_session_partial_rewards(session_id, client_id, awarded, note, points, awarded_at)
                      VALUES (:sid, :cid, :aw, :note, :pts, CASE WHEN :aw THEN NOW() ELSE NULL END)
                      ON CONFLICT (session_id, client_id)
                      DO UPDATE SET awarded = EXCLUDED.awarded,
                                    note = EXCLUDED.note,
                                    points = EXCLUDED.points,
                                    awarded_at = CASE WHEN EXCLUDED.awarded THEN NOW() ELSE NULL END
                    """), {"sid": sid, "cid": cid,
                           "aw": bool(pr.get("awarded")),
                           "note": pr.get("note"),
                           "pts": int(pr.get("points", 0))  # <-- NOWA WARTOŚĆ
                           })

    return jsonify({"ok": True}), 200


# def _half_bounds(year:int, half:int):
#    if half == 1:
#        a = datetime(year,1,1,tzinfo=TZ); b = datetime(year,7,1,tzinfo=TZ)
#    else:
#        a = datetime(year,7,1,tzinfo=TZ); b = datetime(year+1,1,1,tzinfo=TZ)
#    return a,b

@app.get("/api/gaps/day")
def gaps_day():
    """
        Zwraca listy aktywnych klientów/terapeutów/kierowców,
        którzy NIE mają żadnego slotu w danym dniu.
        Param: ?date=YYYY-MM-DD (domyślnie dzisiaj w Europe/Warsaw)
        """
    qd = (request.args.get("date") or "").strip()
    if not qd:
        d = datetime.now(TZ).date()
    else:
        try:
            d = datetime.fromisoformat(qd).date()
        except ValueError:
            return jsonify({"error": "Invalid date. Use YYYY-MM-DD"}), 400

    sql_clients = """
          SELECT c.id, c.full_name
          FROM clients c
          LEFT JOIN schedule_slots ss
            ON ss.client_id = c.id
           AND ss.starts_at::date = :d
          WHERE c.active = true
            AND ss.id IS NULL
          ORDER BY c.full_name;
        """

    # terapeuta: brak żadnej TERAPII tego dnia
    sql_therapists = """
          SELECT t.id, t.full_name
          FROM therapists t
          LEFT JOIN schedule_slots ss
            ON ss.therapist_id = t.id
           AND ss.kind = 'therapy'
           AND ss.starts_at::date = :d
          WHERE t.active = true
            AND ss.id IS NULL
          ORDER BY t.full_name;
        """

    # kierowca: brak żadnego kursu (pickup/dropoff) tego dnia
    sql_drivers = """
          SELECT d.id, d.full_name
          FROM drivers d
          LEFT JOIN schedule_slots ss
            ON ss.driver_id = d.id
           AND ss.kind IN ('pickup','dropoff')
           AND ss.starts_at::date = :d
          WHERE d.active = true
            AND ss.id IS NULL
          ORDER BY d.full_name;
        """

    with engine.begin() as conn:
        clients = [dict(r) for r in conn.execute(text(sql_clients), {"d": d}).mappings().all()]
        therapists = [dict(r) for r in conn.execute(text(sql_therapists), {"d": d}).mappings().all()]
        drivers = [dict(r) for r in conn.execute(text(sql_drivers), {"d": d}).mappings().all()]

    return jsonify({
        "date": d.isoformat(),
        "clients": clients,
        "therapists": therapists,
        "drivers": drivers,
        "counts": {
            "clients": len(clients),
            "therapists": len(therapists),
            "drivers": len(drivers),
        }
    }), 200


@app.get("/api/gaps/month")
def gaps_month():
    """
        Zwraca aktywnych klientów / terapeutów / kierowców,
        którzy w danym miesiącu NIE mają żadnego slotu.
        Dodatkowo zwraca informacje o nieobecnościach.
        """
    mk = (request.args.get("month") or "").strip()
    if not mk:
        mk = datetime.now(TZ).strftime("%Y-%m")

    # Klient: brak JAKIEGOKOLWIEK slotu w miesiącu
    sql_clients = """
          SELECT c.id, c.full_name
          FROM clients c
          WHERE c.active = true
            AND NOT EXISTS (
              SELECT 1 FROM schedule_slots ss
              WHERE ss.client_id = c.id
                AND ss.starts_at IS NOT NULL
                AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            )
          ORDER BY c.full_name;
        """

    # Terapeuta: brak TERAPII w miesiącu
    sql_therapists = """
          SELECT t.id, t.full_name
          FROM therapists t
          WHERE t.active = true
            AND NOT EXISTS (
              SELECT 1 FROM schedule_slots ss
              WHERE ss.therapist_id = t.id
                AND ss.kind = 'therapy'
                AND ss.starts_at IS NOT NULL
                AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            )
          ORDER BY t.full_name;
        """

    # Kierowca: brak kursów (pickup/dropoff) w miesiącu
    sql_drivers = """
          SELECT d.id, d.full_name
          FROM drivers d
          WHERE d.active = true
            AND NOT EXISTS (
              SELECT 1 FROM schedule_slots ss
              WHERE ss.driver_id = d.id
                AND ss.kind IN ('pickup','dropoff')
                AND ss.starts_at IS NOT NULL
                AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            )
          ORDER BY d.full_name;
        """

    # NOWOŚĆ: Pobieranie nieobecności
    sql_absences = text("""
            SELECT person_type, person_id, status 
            FROM absences
            WHERE to_char(start_date, 'YYYY-MM') <= :mk AND to_char(end_date, 'YYYY-MM') >= :mk
        """)

    with engine.begin() as conn:
        clients = [dict(r) for r in conn.execute(text(sql_clients), {"mk": mk}).mappings().all()]
        therapists = [dict(r) for r in conn.execute(text(sql_therapists), {"mk": mk}).mappings().all()]
        drivers = [dict(r) for r in conn.execute(text(sql_drivers), {"mk": mk}).mappings().all()]
        absences_rows = conn.execute(sql_absences, {"mk": mk}).mappings().all()

    # Przetwórz nieobecności w słownik dla łatwego dostępu
    absences_map = {}
    for ab in absences_rows:
        key = (ab['person_type'], ab['person_id'])
        absences_map[key] = ab['status']

    # Dodaj informacje o nieobecnościach do wyników
    for t in therapists:
        if ('therapist', t['id']) in absences_map:
            t['absence_status'] = absences_map[('therapist', t['id'])]

    for d in drivers:
        if ('driver', d['id']) in absences_map:
            d['absence_status'] = absences_map[('driver', d['id'])]

    return jsonify({
        "month": mk,
        "clients": clients,
        "therapists": therapists,
        "drivers": drivers,
        "counts": {
            "clients": len(clients),
            "therapists": len(therapists),
            "drivers": len(drivers),
        }
    }), 200


@app.get("/api/client/<int:cid>/packages")
def client_packages(cid):
    mk = request.args.get("month")
    # POPRAWKA: Usunięto CAST, ponieważ oba pola są typu UUID
    sql = text("""
            WITH all_events AS (
                SELECT
                    'individual' as type, eg.id::text AS group_id, eg.label, ss.id AS slot_id,
                    ss.kind, ss.starts_at, ss.ends_at, ss.status, ss.therapist_id, t.full_name AS therapist_name,
                    ss.driver_id, d.full_name AS driver_name, ss.place_from, ss.place_to, ss.distance_km
                FROM event_groups eg
                JOIN schedule_slots ss ON eg.id = ss.group_id
                LEFT JOIN therapists t ON t.id = ss.therapist_id
                LEFT JOIN drivers d ON d.id = ss.driver_id
                WHERE eg.client_id = :cid
                UNION ALL
                SELECT
                    'tus' as type, g.id::text AS group_id, g.name AS label, s.id AS slot_id, 'therapy' as kind,
                    (s.session_date::timestamp + COALESCE(s.session_time, '00:00:00')::interval) AT TIME ZONE 'Europe/Warsaw' AS starts_at,
                    (s.session_date::timestamp + COALESCE(s.session_time, '00:00:00')::interval + INTERVAL '60 minutes') AT TIME ZONE 'Europe/Warsaw' AS ends_at,
                    'planned' as status, g.therapist_id, th.full_name AS therapist_name,
                    NULL AS driver_id, NULL AS driver_name, 'Poradnia' AS place_from, 'Poradnia' AS place_to, NULL as distance_km
                FROM tus_sessions s
                JOIN tus_groups g ON s.group_id = g.id
                JOIN tus_group_members gm ON gm.group_id = g.id
                LEFT JOIN therapists th ON g.therapist_id = th.id
                WHERE gm.client_id = :cid
            )
            SELECT * FROM all_events
            WHERE (:mk IS NULL OR to_char(starts_at AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM') = :mk)
            ORDER BY starts_at;
        """)

    with engine.begin() as conn:
        rows = conn.execute(sql, {"cid": cid, "mk": mk}).mappings().all()
        results = []
        for r in rows:
            row_dict = dict(r)
            if starts_at_aware := r.get('starts_at'):
                row_dict['starts_at'] = starts_at_aware.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
            if ends_at_aware := r.get('ends_at'):
                row_dict['ends_at'] = ends_at_aware.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
            results.append(row_dict)
        return jsonify(results)


# === DRIVER SCHEDULE (kursy kierowcy z klientami) ===
@app.get("/api/drivers/<int:did>/schedule")
@driver_required
def driver_schedule(did):
    mk = request.args.get("month")
    sql = """
        SELECT
          ss.id AS slot_id,
          ss.kind,
          to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM-DD"T"HH24:MI:SS') AS starts_at,
          to_char(ss.ends_at   AT TIME ZONE 'Europe/Warsaw','YYYY-MM-DD"T"HH24:MI:SS') AS ends_at,
          ss.status,
          c.id AS client_id,
          c.full_name AS client_name,
          ss.place_from,
          ss.place_to,
          ss.vehicle_id,
          ss.group_id,
          ss.distance_km
        FROM schedule_slots ss
        JOIN clients c ON c.id = ss.client_id
        WHERE ss.driver_id = :did
          AND (
            :mk IS NULL OR
            (ss.starts_at IS NOT NULL AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk)
          )
        ORDER BY ss.starts_at;
        """
    with engine.begin() as conn:
        rows = conn.execute(text(sql), {"did": did, "mk": mk}).mappings().all()
        return jsonify([dict(r) for r in rows]), 200


# BACKEND (Flask)
@app.patch("/api/slots/<int:sid>")
def update_slot(sid):
    data = request.get_json(silent=True) or {}
    fields = []
    params = {"sid": sid}
    if "status" in data:
        fields.append("status=:status")
        params["status"] = data["status"]
    if "starts_at" in data:
        fields.append("starts_at=:starts_at")
        params["starts_at"] = datetime.fromisoformat(data["starts_at"]).replace(tzinfo=TZ)
    if "ends_at" in data:
        fields.append("ends_at=:ends_at")
        params["ends_at"] = datetime.fromisoformat(data["ends_at"]).replace(tzinfo=TZ)
    if not fields:
        return jsonify({"error": "No fields"}), 400
    sql = f"UPDATE schedule_slots SET {', '.join(fields)} WHERE id=:sid RETURNING id;"
    with engine.begin() as conn:
        row = conn.execute(text(sql), params).mappings().first()
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify({"ok": True, "id": row["id"]}), 200


@app.route('/api/slots/<int:slot_id>/status', methods=['PATCH'])
def update_slot_status(slot_id):
    """Aktualizuje status pojedynczego slotu"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Brak danych JSON"}), 400

    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "Brak parametru 'status'"}), 400

    # Walidacja statusu
    valid_statuses = ['planned', 'confirmed', 'done', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({"error": f"Nieprawidłowy status. Dozwolone: {', '.join(valid_statuses)}"}), 400

    try:
        with engine.begin() as conn:
            # Sprawdź czy slot istnieje
            slot_exists = conn.execute(
                text("SELECT id FROM schedule_slots WHERE id = :id"),
                {"id": slot_id}
            ).scalar()

            if not slot_exists:
                return jsonify({"error": "Slot nie znaleziony"}), 404

            # Aktualizuj status
            conn.execute(
                text("UPDATE schedule_slots SET status = :status WHERE id = :id"),
                {"status": new_status, "id": slot_id}
            )

            return jsonify({
                "status": "ok",
                "slot_id": slot_id,
                "new_status": new_status,
                "message": "Status zaktualizowany"
            })

    except Exception as e:
        print(f"BŁĄD w update_slot_status: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Wewnętrzny błąd serwera: {str(e)}"}), 500


# zmiana widkou kart grup
@app.get("/api/tus/groups-summary")
def get_tus_groups_summary():
    """Zwraca podsumowanie dla kart grup, bazując na bieżącym roku szkolnym."""
    with SessionLocal() as session:
        now = datetime.now(TZ).date()

        # Określ bieżący rok szkolny i semestr
        current_school_year_start = now.year if now.month >= 9 else now.year - 1
        current_semester = 1 if now.month >= 9 or now.month <= 1 else 2
        start_date, end_date = get_semester_dates(current_school_year_start, current_semester)

        # Subzapytania z nową logiką dat
        session_bonuses_subq = select(TUSSession.group_id, func.sum(TUSMemberBonus.points).label("total_s")).join(
            TUSSession).where(TUSSession.session_date.between(start_date, end_date)).group_by(
            TUSSession.group_id).subquery()
        general_bonuses_subq = select(TUSGeneralBonus.group_id,
                                      func.sum(TUSGeneralBonus.points).label("total_g")).where(
            TUSGeneralBonus.awarded_at.between(start_date, end_date)).group_by(TUSGeneralBonus.group_id).subquery()
        last_session_subq = select(TUSSession.group_id, func.max(TUSSession.session_date).label("max_date")).group_by(
            TUSSession.group_id).subquery()
        targets_subq = select(TUSGroupTarget).where(TUSGroupTarget.school_year_start == current_school_year_start,
                                                    TUSGroupTarget.semester == current_semester).subquery()

        groups_data = (
            session.query(
                TUSGroup, TUSTopic.title.label("last_topic_title"),
                func.coalesce(session_bonuses_subq.c.total_s, 0).label("session_points"),
                func.coalesce(general_bonuses_subq.c.total_g, 0).label("general_points"),
                targets_subq.c.target_points, targets_subq.c.reward
            )
            .outerjoin(session_bonuses_subq, TUSGroup.id == session_bonuses_subq.c.group_id)
            .outerjoin(general_bonuses_subq, TUSGroup.id == general_bonuses_subq.c.group_id)
            .outerjoin(targets_subq, TUSGroup.id == targets_subq.c.group_id)
            .outerjoin(last_session_subq, TUSGroup.id == last_session_subq.c.group_id)
            .outerjoin(TUSSession,
                       (TUSGroup.id == TUSSession.group_id) & (TUSSession.session_date == last_session_subq.c.max_date))
            .outerjoin(TUSTopic, TUSSession.topic_id == TUSTopic.id)
            .options(joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client),
                     joinedload(TUSGroup.therapist))
            .order_by(TUSGroup.name).all()
        )

        result = []
        for group, last_topic, session_points, general_points, target_points, reward in groups_data:
            total_points_collected = int(session_points) + int(general_points)
            target = target_points or 0
            reward_str = reward or "Brak"
            remaining = max(0, target - total_points_collected)
            result.append({
                "id": group.id, "name": group.name,
                "therapist_name": group.therapist.full_name if group.therapist else "Brak",
                "member_count": len(group.members), "last_topic": last_topic,
                "total_points_collected": total_points_collected, "target_points": target,
                "points_remaining": remaining, "reward": reward_str
            })

        return jsonify(result)


@app.get("/api/tus/groups/<int:group_id>/topic-history")
def get_group_topic_history(group_id: int):
    with SessionLocal() as session:
        # Krok 1: Znajdź ID aktualnych członków grupy
        current_member_ids = session.execute(
            select(TUSGroupMember.client_id).where(TUSGroupMember.group_id == group_id)
        ).scalars().all()

        if not current_member_ids:
            return jsonify({})

        # Krok 2: Pobierz PEŁNĄ historię dla tych członków ze wszystkich grup
        history_query = (
            select(
                TUSGroupMember.client_id,
                Client.full_name,
                TUSTopic.title,
                TUSSession.session_date,
                TUSGroup.name
            )
            .distinct()
            .join(Client, Client.id == TUSGroupMember.client_id)
            .join(TUSGroup, TUSGroup.id == TUSGroupMember.group_id)
            .join(TUSSession, TUSSession.group_id == TUSGroup.id)
            .join(TUSTopic, TUSTopic.id == TUSSession.topic_id)
            .where(TUSGroupMember.client_id.in_(current_member_ids))
            .order_by(Client.full_name, TUSSession.session_date.desc())
        )

        history_results = session.execute(history_query).all()

        # Krok 3: Przetwarzanie wyników (bez zmian)
        history_by_client = {}
        for row in history_results:
            client_id, client_name, topic_title, session_date, group_name = row
            if client_id not in history_by_client:
                history_by_client[client_id] = {
                    "client_name": client_name,
                    "history": []
                }
            history_by_client[client_id]["history"].append({
                "topic": topic_title,
                "date": session_date.isoformat(),
                "group_name": group_name
            })

        return jsonify(history_by_client)


@app.get("/api/clients/<int:client_id>/history")
def get_client_history(client_id: int):
    try:
        with engine.begin() as conn:
            # 1. Spotkania indywidualne
            individual_sql = text('''
                    SELECT 
                        ss.id as slot_id,
                        ss.starts_at,
                        ss.ends_at,
                        ss.status,
                        th.full_name as therapist_name,
                        eg.label as topic,
                        ss.place_to as place,
                        EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes
                    FROM schedule_slots ss
                    LEFT JOIN therapists th ON th.id = ss.therapist_id
                    LEFT JOIN event_groups eg ON eg.id = ss.group_id
                    WHERE ss.client_id = :cid
                        AND ss.kind = 'therapy'
                    ORDER BY ss.starts_at DESC
                ''')

            individual_rows = conn.execute(individual_sql, {"cid": client_id}).mappings().all()

            # 2. ZMIENIONE: Pobierz NAJNOWSZĄ notatkę dla każdej daty
            notes_sql = text('''
                    SELECT DISTINCT ON (DATE(created_at))
                        id,
                        content,
                        created_at,
                        category
                    FROM client_notes
                    WHERE client_id = :cid
                        AND category = 'session'
                    ORDER BY DATE(created_at) DESC, created_at DESC
                ''')

            notes_rows = conn.execute(notes_sql, {"cid": client_id}).mappings().all()

            # Mapuj notatki po dacie wraz z ID
            notes_map = {}
            note_ids_map = {}
            for note in notes_rows:
                note_date = note['created_at'].date()
                notes_map[note_date] = note['content']
                note_ids_map[note_date] = note['id']
                print(f"  → Mapuję notatkę ID {note['id']} dla daty {note_date}")

            # 3. Spotkania TUS
            tus_sql = text('''
                    SELECT 
                        ts.session_date,
                        ts.session_time,
                        tt.title as topic_title,
                        tg.name as group_name
                    FROM tus_sessions ts
                    JOIN tus_groups tg ON tg.id = ts.group_id
                    JOIN tus_group_members tgm ON tgm.group_id = tg.id
                    LEFT JOIN tus_topics tt ON tt.id = ts.topic_id
                    WHERE tgm.client_id = :cid
                    ORDER BY ts.session_date DESC
                ''')

            tus_rows = conn.execute(tus_sql, {"cid": client_id}).mappings().all()

            # 4. Formatowanie z dopasowaniem notatek
            history = {
                "individual": [
                    {
                        "date": row['starts_at'].isoformat() if row['starts_at'] else None,
                        "status": row['status'] or "unknown",
                        "therapist": row['therapist_name'] or "Nieznany",
                        "topic": row['topic'] or "Bez tematu",
                        "notes": notes_map.get(row['starts_at'].date(), "") if row['starts_at'] else "",
                        "note_id": note_ids_map.get(row['starts_at'].date()) if row['starts_at'] else None,
                        "place": row['place'] or "",
                        "duration": int(row['duration_minutes']) if row['duration_minutes'] else 60,
                    } for row in individual_rows
                ],
                "tus_group": [
                    {
                        "date": row['session_date'].isoformat() if row['session_date'] else None,
                        "time": row['session_time'].strftime('%H:%M') if row['session_time'] else None,
                        "topic": row['topic_title'] or "Brak tematu",
                        "group": row['group_name'] or "Nieznana grupa"
                    } for row in tus_rows
                ]
            }

            print(f"✅ Zwracam: {len(history['individual'])} indywidualnych, {len(history['tus_group'])} TUS")
            return jsonify(history), 200

    except Exception as e:
        print(f"❌ BŁĄD w get_client_history: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/tus/schedule")
def get_tus_schedule():
    """Zwraca wszystkie sesje TUS w danym miesiącu wraz z uczestnikami."""
    month_key = request.args.get("month")
    if not month_key:
        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

    sql = text("""
            SELECT
                s.id AS session_id,
                s.session_date,
                s.session_time,
                g.id AS group_id,
                g.name AS group_name,
                COALESCE(t.title, 'Brak tematu') AS topic_title,
                COALESCE(th.full_name, 'Brak terapeuty') AS therapist_name,
                (SELECT json_agg(json_build_object('id', c.id, 'name', c.full_name))
                 FROM tus_group_members gm
                 JOIN clients c ON c.id = gm.client_id
                 WHERE gm.group_id = g.id) AS members
            FROM 
                tus_sessions s
            JOIN 
                tus_groups g ON s.group_id = g.id
            LEFT JOIN 
                tus_topics t ON s.topic_id = t.id
            LEFT JOIN 
                therapists th ON g.therapist_id = th.id
            WHERE 
                to_char(s.session_date, 'YYYY-MM') = :month
            ORDER BY 
                s.session_date, s.session_time;
        """)

    # --- NOWE LINIE DIAGNOSTYCZNE ---
    print("--- DIAGNOSTYKA ZAPYTANIA TUS SCHEDULE ---")
    print(str(sql))
    print(f"--- UŻYTE PARAMETRY: {{'month': '{month_key}'}} ---")
    # --- KONIEC LINII DIAGNOSTYCZNYCH ---

    with engine.begin() as conn:
        rows = conn.execute(sql, {"month": month_key}).mappings().all()
        results = [
            {**row,
             'session_date': row['session_date'].isoformat(),
             'session_time': row['session_time'].strftime('%H:%M:%S') if row['session_time'] else None
             }
            for row in rows
        ]
        return jsonify(results)


# @app.get("/api/therapists/<int:tid>/schedule")
# def therapist_schedule(tid):
#    mk = request.args.get("month")
#    if not mk:
#        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

#    all_results = []

#    with engine.begin() as conn:
#        # Query 1: Individual sessions
#        # FIX: Explicitly convert timestamp to UTC
#        sql_individual = text("""
#            SELECT
#                ss.id AS slot_id, 'individual' as type, ss.kind,
#                ss.starts_at AT TIME ZONE 'UTC' as starts_at,
#                ss.ends_at AT TIME ZONE 'UTC' as ends_at,
#                ss.status, c.full_name AS client_name,
#                ss.place_to, g.label AS group_name
#            FROM schedule_slots ss
#            JOIN clients c ON c.id = ss.client_id
#            LEFT JOIN event_groups g ON g.id = ss.group_id
#            WHERE ss.therapist_id = :tid
#              AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM') = :mk
#        """)
#        individual_rows = conn.execute(sql_individual, {"tid": tid, "mk": mk}).mappings().all()
#        all_results.extend(individual_rows)

# Query 2: TUS group sessions
# FIX: Explicitly create and convert timestamp to UTC
#        sql_tus = text("""
#            SELECT
#                s.id AS slot_id, 'tus' as type, 'therapy' as kind,
#                ((s.session_date + COALESCE(s.session_time, '00:00:00'::time)) AT TIME ZONE 'Europe/Warsaw') AT TIME ZONE 'UTC' AS starts_at,
#                ((s.session_date + COALESCE(s.session_time, '00:00:00'::time) + INTERVAL '60 minutes') AT TIME ZONE 'Europe/Warsaw') AT TIME ZONE 'UTC' AS ends_at,
#                'planned' as status, g.name AS client_name,
#                'Poradnia' as place_to, g.name AS group_name
#            FROM tus_sessions s
#            JOIN tus_groups g ON s.group_id = g.id
#            WHERE (g.therapist_id = :tid OR g.assistant_therapist_id = :tid)
#              AND to_char(s.session_date, 'YYYY-MM') = :mk
#        """)
#        tus_rows = conn.execute(sql_tus, {"tid": tid, "mk": mk}).mappings().all()
#        all_results.extend(tus_rows)

# Sorting will now work correctly
#    all_results.sort(key=lambda r: r.get('starts_at') or datetime.max.replace(tzinfo=ZoneInfo("UTC")))

# Formatting the dates to strings for the frontend
#    results = [
#        {**r,
#         'starts_at': r['starts_at'].isoformat() if r.get('starts_at') else None,
#         'ends_at': r['ends_at'].isoformat() if r.get('ends_at') else None
#         } for r in all_results
#    ]
#    return jsonify(results)

# POPRAWIONE SORTOWANIE - konwertuj wszystkie daty do tej samej strefy czasowej


@app.get("/api/therapists/<int:tid>/schedule")
def therapist_schedule(tid):
    mk = request.args.get("month")
    if not mk:
        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

    all_results = []
    with engine.begin() as conn:
        # Zapytanie 1: Zajęcia indywidualne
        sql_individual = text("""
                SELECT
                    ss.id AS slot_id, 'individual' as type, ss.kind,
                    ss.starts_at, ss.ends_at, ss.status, c.full_name AS client_name,
                    ss.place_to, g.label AS group_name, g.id::text as group_id
                FROM schedule_slots ss
                JOIN clients c ON c.id = ss.client_id
                LEFT JOIN event_groups g ON g.id = CAST(ss.group_id AS UUID)
                WHERE ss.therapist_id = :tid
                  AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM') = :mk
            """)
        all_results.extend(conn.execute(sql_individual, {"tid": tid, "mk": mk}).mappings().all())

        # Zapytanie 2: Zajęcia grupowe TUS
        sql_tus = text("""
                SELECT
                    s.id AS slot_id, 'tus' as type, 'therapy' as kind,
                    (s.session_date::timestamp + COALESCE(s.session_time, '00:00:00')::interval) AT TIME ZONE 'Europe/Warsaw' AS starts_at,
                    (s.session_date::timestamp + COALESCE(s.session_time, '00:00:00')::interval + INTERVAL '60 minutes') AT TIME ZONE 'Europe/Warsaw' AS ends_at,
                    'planned' as status, g.name AS client_name,
                    'Poradnia' as place_to, g.name AS group_name, g.id::text as group_id
                FROM tus_sessions s
                JOIN tus_groups g ON s.group_id = g.id
                JOIN tus_group_members gm on g.id = gm.group_id
                WHERE (g.therapist_id = :tid OR g.assistant_therapist_id = :tid)
                  AND gm.client_id IS NOT NULL 
                  AND to_char(s.session_date, 'YYYY-MM') = :mk
            """)
        all_results.extend(conn.execute(sql_tus, {"tid": tid, "mk": mk}).mappings().all())

    # --- POCZĄTEK OSTATECZNEJ POPRAWKI ---
    # Normalizujemy wszystkie daty PRZED sortowaniem, aby mieć pewność, że są świadome strefy czasowej
    for r in all_results:
        # Używamy dict(r), aby móc modyfikować słownik w miejscu
        row_dict = dict(r)
        if starts_at := row_dict.get('starts_at'):
            if starts_at.tzinfo is None:
                # Jeśli data jest "naiwna", zakładamy, że jest w naszej lokalnej strefie czasowej i oznaczamy ją
                row_dict['starts_at'] = starts_at.replace(tzinfo=TZ)
    # --- KONIEC OSTATECZNEJ POPRAWKI ---

    # Sortowanie będzie teraz działać poprawnie
    all_results.sort(key=lambda r: r.get('starts_at') or datetime.max.replace(tzinfo=ZoneInfo("UTC")))

    # Formatowanie dat na stringi w lokalnej strefie czasowej
    results = []
    for r in all_results:
        row_dict = dict(r)
        if starts_at_aware := row_dict.get('starts_at'):
            row_dict['starts_at'] = starts_at_aware.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
        if ends_at_aware := row_dict.get('ends_at'):
            row_dict['ends_at'] = ends_at_aware.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
        results.append(row_dict)

    return jsonify(results)


@app.post("/api/schedule/group")
def create_group_with_slots():
    """
        JSON:
        {
          "client_id": 1,
          "label": "Wtorek poranny",
          "therapy":  {"therapist_id":2, "starts_at":"2025-08-19T09:00:00", "ends_at":"2025-08-19T10:00:00", "place":"Poradnia"},
          "pickup":   {"driver_id":3, "vehicle_id":1, "starts_at":"2025-08-19T08:30:00", "ends_at":"2025-08-19T09:00:00", "from":"Dom", "to":"Poradnia"},
          "dropoff":  {"driver_id":3, "vehicle_id":1, "starts_at":"2025-08-19T10:05:00", "ends_at":"2025-08-19T10:35:00", "from":"Poradnia", "to":"Dom"},
          "status": "planned"
        }
        """
    data = request.get_json(silent=True) or {}
    gid = uuid.uuid4()
    status = data.get("status", "planned")

    # === POPRAWIONY BLOK DIAGNOSTYCZNY ===
    print("\n" + "=" * 80)
    print("🔥 TWORZENIE NOWEGO PAKIETU")
    print("=" * 80)
    print(f"Group ID: {gid}")
    print(f"Client ID: {data.get('client_id')}")
    print(f"Status: {status}")

    if data.get('pickup'):  # POPRAWKA: Sprawdź czy istnieje
        print(f"\nPICKUP:")
        print(f"  Od: {data['pickup'].get('from')}")
        print(f"  Do: {data['pickup'].get('to')}")
    else:
        print(f"\nPICKUP: BRAK")

    if data.get('dropoff'):  # POPRAWKA: Sprawdź czy istnieje
        print(f"\nDROPOFF:")
        print(f"  Od: {data['dropoff'].get('from')}")
        print(f"  Do: {data['dropoff'].get('to')}")
    else:
        print(f"\nDROPOFF: BRAK")

    print(f"\nKlucz Google Maps: {'✓ USTAWIONY' if GOOGLE_MAPS_API_KEY else '✗ BRAK'}")
    print("=" * 80)
    # === KONIEC BLOKU DIAGNOSTYCZNEGO ===

    try:
        with engine.begin() as conn:
            # 1) Utwórz nadrzędny pakiet w event_groups
            conn.execute(text("""
                        INSERT INTO event_groups (id, client_id, label)
                        VALUES (:id, :client_id, :label)
                    """), {
                "id": gid,
                "client_id": data["client_id"],
                "label": data.get("label")
            })

            # 2) Utwórz slot terapii
            t = data["therapy"]
            ts = datetime.fromisoformat(t["starts_at"]).replace(tzinfo=TZ)
            te = datetime.fromisoformat(t["ends_at"]).replace(tzinfo=TZ)
            session_id = ensure_shared_session_id_for_therapist(conn, int(t["therapist_id"]), ts, te)

            therapy_slot_id = conn.execute(text("""
                        INSERT INTO schedule_slots (
                            group_id, client_id, therapist_id, kind, 
                            starts_at, ends_at, place_to, status, session_id
                        ) VALUES (
                            :group_id, :client_id, :therapist_id, 'therapy', 
                            :starts_at, :ends_at, :place, :status, :session_id
                        ) RETURNING id
                    """), {
                "group_id": str(gid),
                "client_id": data["client_id"],
                "therapist_id": t["therapist_id"],
                "starts_at": ts,
                "ends_at": te,
                "place": t.get("place"),
                "status": status,
                "session_id": session_id
            }).scalar_one()

            # 3) Utwórz wpis o obecności
            if therapy_slot_id:
                conn.execute(text("""
                            INSERT INTO individual_session_attendance (slot_id, status)
                            VALUES (:slot_id, 'obecny')
                        """), {"slot_id": therapy_slot_id})

            # POPRAWIONA FUNKCJA insert_run
            def insert_run(run_data, kind):
                if not run_data:
                    print(f"⚠️  Brak danych dla {kind}")
                    return

                print(f"\n--- Przetwarzam {kind.upper()} ---")
                print(f"Driver ID: {run_data.get('driver_id')}")
                print(f"Od: {run_data.get('from')}")
                print(f"Do: {run_data.get('to')}")

                s = datetime.fromisoformat(run_data["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(run_data["ends_at"]).replace(tzinfo=TZ)
                run_id = ensure_shared_run_id_for_driver(conn, int(run_data["driver_id"]), s, e)

                # KLUCZOWA CZĘŚĆ - OBLICZ DYSTANS
                place_from = run_data.get("from")
                place_to = run_data.get("to")

                print(f"🔍 Obliczam dystans: '{place_from}' -> '{place_to}'")
                print(f"🔑 Klucz API: {GOOGLE_MAPS_API_KEY[:20]}..." if GOOGLE_MAPS_API_KEY else "❌ BRAK KLUCZA")

                if place_from and place_to:
                    distance = get_route_distance(place_from, place_to)
                    print(f"{'✓' if distance else '✗'} Dystans: {distance} km")
                else:
                    distance = None
                    print(f"⚠️  Brak adresów - pomijam obliczanie dystansu")

                # ZAPISZ DO BAZY
                print(f"💾 Zapisuję slot z distance_km = {distance}")

                result = conn.execute(text("""
                            INSERT INTO schedule_slots (
                                group_id, client_id, driver_id, vehicle_id, kind, 
                                starts_at, ends_at, place_from, place_to, status, run_id,
                                distance_km
                            ) VALUES (
                                :group_id, :client_id, :driver_id, :vehicle_id, :kind, 
                                :starts_at, :ends_at, :from, :to, :status, :run_id,
                                :distance
                            )
                            RETURNING id
                        """), {
                    "group_id": str(gid),
                    "client_id": data["client_id"],
                    "driver_id": run_data["driver_id"],
                    "vehicle_id": run_data.get("vehicle_id"),
                    "kind": kind,
                    "starts_at": s,
                    "ends_at": e,
                    "from": place_from,
                    "to": place_to,
                    "status": status,
                    "run_id": run_id,
                    "distance": distance
                })

                new_id = result.scalar_one()
                print(f"✓ Slot {kind} utworzony (ID: {new_id}, dystans: {distance} km)")

            # 4) Utwórz sloty dowozu i odwozu
            insert_run(data.get("pickup"), "pickup")
            insert_run(data.get("dropoff"), "dropoff")

            print(f"\n✅ PAKIET UTWORZONY: {gid}")
            print("=" * 80 + "\n")

            return jsonify({"group_id": str(gid), "ok": True}), 201

    except IntegrityError as e:
        print(f"\n❌ BŁĄD INTEGRALNOŚCI: {e}")
        if getattr(e.orig, "pgcode", None) == errorcodes.FOREIGN_KEY_VIOLATION:
            return jsonify({"error": "Naruszenie klucza obcego."}), 400
        if getattr(e.orig, "pgcode", None) == errorcodes.EXCLUSION_VIOLATION:
            return jsonify({"error": "Konflikt czasowy."}), 409
        return jsonify({"error": "Błąd bazy danych"}), 400
    except Exception as e:
        print(f"\n❌ BŁĄD KRYTYCZNY: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/schedule', methods=['POST'])
def create_schedule_slot():
    """Tworzy nową wizytę w harmonogramie (indywidualną lub TUS)"""
    data = request.get_json(silent=True) or {}

    print(f"=== CREATE SCHEDULE SLOT ===")
    print(f"Otrzymane dane: {data}")

    # --- POPRAWIONA WALIDACJA ---
    kind = data.get('kind') # Powinno być 'therapy' lub 'tus'
    therapist_id = data.get('therapist_id')
    starts_at_str = data.get('starts_at')
    ends_at_str = data.get('ends_at')

    # Sprawdzenie podstawowych pól
    base_required = {'therapist_id': therapist_id, 'starts_at': starts_at_str, 'ends_at': ends_at_str, 'kind': kind}
    missing_base = [k for k, v in base_required.items() if not v]
    if missing_base:
        return jsonify({"error": f"Brak podstawowych pól: {', '.join(missing_base)}"}), 400

    # Sprawdzenie pól zależnych od 'kind'
    if kind == 'therapy':
        client_id = data.get('client_id')
        if not client_id:
            return jsonify({"error": "Brak wymaganego pola: client_id dla terapii indywidualnej"}), 400
        group_id_db = None # Dla terapii indywidualnej używamy group_id z event_groups
        client_or_group_id = client_id # ID klienta do dalszego użytku
        target_name_field = 'client_name' # Do komunikatu błędu
    elif kind == 'tus':
        group_id = data.get('group_id')
        if not group_id:
            return jsonify({"error": "Brak wymaganego pola: group_id dla grupy TUS"}), 400
        client_id = None # W slocie nie ma ID klienta dla TUS
        group_id_db = group_id # ID grupy TUS do zapisu w schedule_slots (jeśli chcesz)
        client_or_group_id = group_id # ID grupy do dalszego użytku
        target_name_field = 'group_name' # Do komunikatu błędu
    else:
        return jsonify({"error": f"Nieznany typ wizyty (kind): {kind}. Oczekiwano 'therapy' lub 'tus'."}), 400
    # --- KONIEC POPRAWIONEJ WALIDACJI ---

    try:
        # Konwersja dat
        starts_at = datetime.fromisoformat(starts_at_str.replace(' ', 'T')).replace(tzinfo=TZ)
        ends_at = datetime.fromisoformat(ends_at_str.replace(' ', 'T')).replace(tzinfo=TZ)

        with engine.begin() as conn:
            # Sprawdź czy terapeuta istnieje
            therapist_exists = conn.execute(
                text("SELECT 1 FROM therapists WHERE id = :id AND active = true"),
                {"id": therapist_id}
            ).scalar()
            if not therapist_exists:
                return jsonify({"error": "Terapeuta nie istnieje lub jest nieaktywny"}), 404

            # Sprawdź czy klient lub grupa TUS istnieje (zależnie od 'kind')
            if kind == 'therapy':
                target_exists = conn.execute(
                    text("SELECT 1 FROM clients WHERE id = :id AND active = true"),
                    {"id": client_or_group_id}
                ).scalar()
                target_type = "Klient"
            else: # kind == 'tus'
                target_exists = conn.execute(
                    text("SELECT 1 FROM tus_groups WHERE id = :id"),
                    {"id": client_or_group_id}
                ).scalar()
                target_type = "Grupa TUS"

            if not target_exists:
                return jsonify({"error": f"{target_type} nie istnieje lub jest nieaktywny"}), 404

            # Sprawdź kolizje czasowe dla terapeuty
            conflicts = find_overlaps(conn, therapist_id=therapist_id,
                                      starts_at=starts_at, ends_at=ends_at)
            if conflicts:
                return jsonify({
                    "error": "Konflikt czasowy z istniejącymi zajęciami",
                    "conflicts": conflicts
                }), 409

            # --- ZAPIS DO BAZY (z uwzględnieniem 'kind') ---
            session_id = ensure_shared_session_id_for_therapist(conn, therapist_id, starts_at, ends_at)

            # Utwórz event_group tylko dla terapii indywidualnej
            event_group_uuid = None
            if kind == 'therapy':
                event_group_uuid = uuid.uuid4()
                conn.execute(text("""
                    INSERT INTO event_groups (id, client_id, label)
                    VALUES (:id, :client_id, :label)
                """), {
                    "id": event_group_uuid,
                    "client_id": client_id,
                    "label": f"Terapia {client_id} - {starts_at.strftime('%Y-%m-%d %H:%M')}"
                })
                group_id_for_slot = str(event_group_uuid) # Używamy UUID z event_groups
            else:
                 group_id_for_slot = None # Dla TUS nie tworzymy event_group, group_id może być puste w slocie

            # Wstaw nowy slot
            result = conn.execute(text("""
                INSERT INTO schedule_slots (
                    group_id, client_id, therapist_id, kind, group_tus_id, -- Dodano group_tus_id
                    starts_at, ends_at, place_to, status, session_id
                ) VALUES (
                    :group_id, :client_id, :therapist_id, :kind, :group_tus_id,
                    :starts_at, :ends_at, :place_to, :status, :session_id
                ) RETURNING id
            """), {
                "group_id": group_id_for_slot, # UUID event_groups lub None
                "client_id": client_id, # ID klienta lub None dla TUS
                "therapist_id": therapist_id,
                "kind": kind,
                "group_tus_id": group_id if kind == 'tus' else None, # ID grupy TUS lub None
                "starts_at": starts_at,
                "ends_at": ends_at,
                "place_to": data.get('place_to'),
                "status": data.get('status', 'planned'),
                "session_id": session_id
            })

            new_slot_id = result.scalar_one()

            # Utwórz wpis o obecności tylko dla terapii indywidualnej
            if kind == 'therapy':
                conn.execute(text("""
                    INSERT INTO individual_session_attendance (slot_id, status)
                    VALUES (:slot_id, 'obecny')
                """), {"slot_id": new_slot_id})

            print(f"✅ Utworzono nową wizytę ({kind}) ID: {new_slot_id}")

            return jsonify({
                "success": True,
                "slot_id": new_slot_id,
                "group_id": group_id_for_slot, # Zwracamy UUID dla indywidualnych
                "group_tus_id": group_id if kind == 'tus' else None, # Zwracamy ID grupy TUS
                "kind": kind,
                "message": "Wizyta została utworzona"
            }), 201

    except Exception as e:
        print(f"❌ Błąd tworzenia wizyty: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Błąd tworzenia wizyty: {str(e)}"}), 500



@app.route('/api/schedule/<int:slot_id>', methods=['PUT'])
def update_schedule_slot(slot_id):
    """Aktualizuje istniejącą wizytę w harmonogramie"""
    data = request.get_json(silent=True) or {}
    
    print(f"=== UPDATE SCHEDULE SLOT {slot_id} ===")
    print(f"Otrzymane dane: {data}")

    try:
        with engine.begin() as conn:
            # Sprawdź czy slot istnieje
            slot = conn.execute(
                text("""
                    SELECT id, therapist_id, client_id, group_id, starts_at, ends_at
                    FROM schedule_slots 
                    WHERE id = :id
                """),
                {"id": slot_id}
            ).mappings().first()

            if not slot:
                return jsonify({"error": "Wizyta nie znaleziona"}), 404

            # Przygotuj pola do aktualizacji
            update_fields = []
            params = {"id": slot_id}

            if 'starts_at' in data:
                starts_at = datetime.fromisoformat(data['starts_at'].replace('Z', '+00:00')).astimezone(TZ)
                update_fields.append("starts_at = :starts_at")
                params["starts_at"] = starts_at

            if 'ends_at' in data:
                ends_at = datetime.fromisoformat(data['ends_at'].replace('Z', '+00:00')).astimezone(TZ)
                update_fields.append("ends_at = :ends_at")
                params["ends_at"] = ends_at

            if 'place_to' in data:
                update_fields.append("place_to = :place_to")
                params["place_to"] = data['place_to']

            if 'status' in data:
                update_fields.append("status = :status")
                params["status"] = data['status']

            if not update_fields:
                return jsonify({"error": "Brak danych do aktualizacji"}), 400

            # Sprawdź kolizje jeśli zmieniany jest czas
            if 'starts_at' in data or 'ends_at' in data:
                final_starts_at = params.get("starts_at") or slot['starts_at']
                final_ends_at = params.get("ends_at") or slot['ends_at']
                
                conflicts = find_overlaps(conn, therapist_id=slot['therapist_id'],
                                        starts_at=final_starts_at, ends_at=final_ends_at,
                                        exclude_slot_id=slot_id)
                
                if conflicts:
                    return jsonify({
                        "error": "Konflikt czasowy z istniejącymi zajęciami",
                        "conflicts": conflicts
                    }), 409

            # Wykonaj aktualizację
            set_clause = ", ".join(update_fields)
            conn.execute(text(f"""
                UPDATE schedule_slots 
                SET {set_clause}
                WHERE id = :id
            """), params)

            print(f"✅ Zaktualizowano wizytę ID: {slot_id}")

            return jsonify({
                "success": True,
                "slot_id": slot_id,
                "message": "Wizyta została zaktualizowana"
            }), 200

    except Exception as e:
        print(f"❌ Błąd aktualizacji wizyty: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Błąd aktualizacji wizyty: {str(e)}"}), 500

@app.route('/api/schedule/<int:slot_id>', methods=['DELETE'])
def delete_schedule_slot(slot_id):
    """Usuwa wizytę z harmonogramu"""
    print(f"=== DELETE SCHEDULE SLOT {slot_id} ===")

    try:
        with engine.begin() as conn:
            # Sprawdź czy slot istnieje
            slot = conn.execute(
                text("SELECT id, group_id FROM schedule_slots WHERE id = :id"),
                {"id": slot_id}
            ).mappings().first()

            if not slot:
                return jsonify({"error": "Wizyta nie znaleziona"}), 404

            # Usuń wpis o obecności
            conn.execute(
                text("DELETE FROM individual_session_attendance WHERE slot_id = :slot_id"),
                {"slot_id": slot_id}
            )

            # Usuń slot
            conn.execute(
                text("DELETE FROM schedule_slots WHERE id = :id"),
                {"id": slot_id}
            )

            # Sprawdź czy grupa ma jeszcze jakieś sloty, jeśli nie - usuń grupę
            remaining_slots = conn.execute(
                text("SELECT 1 FROM schedule_slots WHERE group_id = :group_id"),
                {"group_id": slot['group_id']}
            ).scalar()

            if not remaining_slots:
                conn.execute(
                    text("DELETE FROM event_groups WHERE id = :group_id"),
                    {"group_id": slot['group_id']}
                )

            print(f"✅ Usunięto wizytę ID: {slot_id}")

            return jsonify({
                "success": True,
                "message": "Wizyta została usunięta"
            }), 200

    except Exception as e:
        print(f"❌ Błąd usuwania wizyty: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Błąd usuwania wizyty: {str(e)}"}), 500

# NOWY ENDPOINT W odnowa.py
@app.get("/api/clients/<int:client_id>/tus-groups")
def get_client_tus_groups(client_id):
    """Zwraca listę grup TUS, do których należy dany klient."""
    with session_scope() as db_session:
        groups = db_session.query(TUSGroup) \
            .join(TUSGroup.member_associations) \
            .filter(TUSGroupMember.client_id == client_id) \
            .all()

        if not groups:
            return jsonify([])

        result = [{"id": group.id, "name": group.name} for group in groups]
        return jsonify(result)


# NOWE ENDPOINTY DO DODANIA W odnowa.py

@app.get("/api/tus/sessions/<int:session_id>/bonuses")
def get_session_bonuses(session_id):
    """Pobiera listę bonusów indywidualnych przyznanych w danej sesji."""
    with session_scope() as db_session:
        bonuses = db_session.query(TUSMemberBonus) \
            .filter(TUSMemberBonus.session_id == session_id).all()

        result = {b.client_id: b.points for b in bonuses}
        return jsonify(result)


@app.post("/api/tus/sessions/<int:session_id>/bonuses")
def save_session_bonuses(session_id):
    """Zapisuje 'hurtowo' bonusy indywidualne dla uczestników sesji."""
    data = request.get_json(silent=True) or {}
    bonuses_data = data.get("bonuses", [])  # Oczekujemy listy: [{"client_id": 1, "points": 5}, ...]

    with session_scope() as db_session:
        # 1. Usuń stare bonusy dla tej sesji, aby uniknąć duplikatów
        db_session.query(TUSMemberBonus).filter(TUSMemberBonus.session_id == session_id).delete()

        # 2. Dodaj nowe bonusy
        for bonus in bonuses_data:
            if bonus.get("points", 0) > 0:  # Zapisuj tylko, jeśli punkty są większe od 0
                new_bonus = TUSMemberBonus(
                    session_id=session_id,
                    client_id=bonus["client_id"],
                    points=bonus["points"]
                )
                db_session.add(new_bonus)

    return jsonify({"ok": True}), 200


# NOWY ENDPOINT DO WKLEJENIA W odnowa.py

@app.get("/api/tus/sessions/<int:session_id>")
def get_tus_session_details(session_id: int):
    """Zwraca szczegóły pojedynczej sesji TUS, w tym listę jej uczestników."""
    with session_scope() as db_session:
        # Krok 1: Pobierz sesję i od razu jej temat (prosta relacja)
        session_obj = db_session.query(TUSSession).options(
            joinedload(TUSSession.topic)
        ).filter(TUSSession.id == session_id).first()

        if not session_obj:
            return jsonify({"error": "Session not found"}), 404

        # Krok 2: Pobierz grupę tej sesji i jej członków
        # To zapytanie jest bezpieczniejsze i korzysta z poprawnie skonfigurowanej relacji
        group = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client)
        ).filter(TUSGroup.id == session_obj.group_id).first()

        members_json = []
        if group and group.members:
            members_json = [
                {"id": member.id, "full_name": member.full_name}
                for member in group.members
            ]

        # Krok 3: Zbuduj i zwróć odpowiedź
        session_data = {
            "id": session_obj.id,
            "session_date": session_obj.session_date.isoformat(),
            "topic_title": session_obj.topic.title if session_obj.topic else "Brak tematu",
            "members": members_json
        }

        return jsonify(session_data)


@app.get("/api/tus/groups/<int:group_id>/bonus-details")
def get_bonus_details(group_id: int):
    print("\n--- URUCHOMIONO get_bonus_details ---")
    print(f"--- Grupa ID: {group_id} ---")

    # POPRAWKA: Zmiana nazwy zmiennej na 'db_session' dla spójności
    with session_scope() as db_session:
        group = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client)
        ).filter(TUSGroup.id == group_id).first()

        if not group:
            # ...
            return jsonify({"error": "Group not found"}), 404

        member_ids = [member.id for member in group.members]
        if not member_ids:
            return jsonify([])

        # POPRAWKA: Użycie 'db_session' we wszystkich zapytaniach
        behavior_scores_sq = db_session.query(
            TUSSessionMemberScore.client_id,
            func.sum(TUSSessionMemberScore.points).label("total_behavior")
        ).join(TUSSession, TUSSession.id == TUSSessionMemberScore.session_id) \
            .filter(TUSSession.group_id == group_id) \
            .group_by(TUSSessionMemberScore.client_id).subquery()

        session_bonuses_sq = db_session.query(
            TUSMemberBonus.client_id,
            func.sum(TUSMemberBonus.points).label("total_session_bonus")
        ).join(TUSSession, TUSSession.id == TUSMemberBonus.session_id) \
            .filter(TUSSession.group_id == group_id) \
            .group_by(TUSMemberBonus.client_id).subquery()

        general_bonuses_sq = db_session.query(
            TUSGeneralBonus.client_id,
            func.sum(TUSGeneralBonus.points).label("total_general_bonus")
        ).filter(TUSGeneralBonus.group_id == group_id) \
            .group_by(TUSGeneralBonus.client_id).subquery()

        results_query = db_session.query(
            Client.id, Client.full_name,
            func.coalesce(behavior_scores_sq.c.total_behavior, 0),
            func.coalesce(session_bonuses_sq.c.total_session_bonus, 0),
            func.coalesce(general_bonuses_sq.c.total_general_bonus, 0)
        ).outerjoin(behavior_scores_sq, Client.id == behavior_scores_sq.c.client_id) \
            .outerjoin(session_bonuses_sq, Client.id == session_bonuses_sq.c.client_id) \
            .outerjoin(general_bonuses_sq, Client.id == general_bonuses_sq.c.client_id) \
            .filter(Client.id.in_(member_ids)).order_by(Client.full_name)

        final_results = []
        for client_id, full_name, behavior_pts, session_pts, general_pts in results_query.all():
            # --- POCZĄTEK POPRAWKI ---
            # Dodaj 'behavior_pts' do sumy
            total_points = int(behavior_pts) + int(session_pts) + int(general_pts)
            # --- KONIEC POPRAWKI ---

            final_results.append({
                "client_id": client_id, "full_name": full_name,
                "behavior_points": int(behavior_pts),
                "session_bonus_points": int(session_pts),
                "general_bonus_points": int(general_pts),
                "total_points": total_points
            })

        return jsonify(final_results)


@app.post("/api/tus/groups/<int:group_id>/award-general-bonus")
def award_general_bonus(group_id: int):
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    points = data.get("points")
    reason = data.get("reason")

    if not all([client_id, points]):
        return jsonify({"error": "client_id and points are required"}), 400

    try:
        points = int(points)
        if points <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"error": "Points must be a positive integer"}), 400
        # Mnożymy przyznane punkty razy 10
    points *= 10
    # POPRAWKA: Użycie 'db_session' z 'session_scope'
    with session_scope() as db_session:
        is_member = db_session.query(TUSGroupMember).filter_by(
            group_id=group_id, client_id=client_id
        ).first()

        if not is_member:
            return jsonify({"error": "Client is not a member of this group"}), 403

        new_bonus = TUSGeneralBonus(
            client_id=client_id,
            group_id=group_id,
            points=points,
            reason=reason
        )
        db_session.add(new_bonus)

    return jsonify({"ok": True}), 201


@app.get("/api/tus/groups/<int:group_id>/general-bonus-history")
def get_general_bonus_history(group_id: int):
    """Zwraca historię przyznanych bonusów ogólnych dla grupy."""
    with session_scope() as db_session:
        history = db_session.query(
            TUSGeneralBonus.awarded_at,
            TUSGeneralBonus.points,
            TUSGeneralBonus.reason,
            Client.full_name
        ).join(Client, Client.id == TUSGeneralBonus.client_id) \
            .filter(TUSGeneralBonus.group_id == group_id) \
            .order_by(TUSGeneralBonus.awarded_at.desc()).all()

        results = [
            {
                "awarded_at": h.awarded_at.isoformat(),
                "points": h.points,
                "reason": h.reason,
                "client_name": h.full_name
            } for h in history
        ]
        return jsonify(results)


@app.put('/api/tus/groups/<int:group_id>/schedule')
def save_group_schedule(group_id):
    data = request.get_json(silent=True) or {}
    schedule_days_str = data.get('schedule_days', [])

    if not isinstance(schedule_days_str, list):
        return jsonify({"error": "Oczekiwano tablicy 'schedule_days'."}), 400

    with session_scope() as session:
        group = session.get(TUSGroup, group_id)
        if not group:
            return jsonify({"error": "Nie znaleziono grupy."}), 404

        # Konwertuj stringi na obiekty dat
        group.schedule_days = sorted([date.fromisoformat(d) for d in set(schedule_days_str)])
        session.commit()

    return jsonify({"ok": True})


@app.get("/api/tus/sessions-for-day")
def get_sessions_for_day():
    """Zwraca listę sesji TUS dla podanej daty."""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Parametr 'date' jest wymagany."}), 400

    try:
        query_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Nieprawidłowy format daty."}), 400

    with session_scope() as db_session:
        sessions = db_session.query(
            TUSSession.id,
            TUSSession.session_time,
            TUSGroup.name,
            TUSTopic.title
        ).join(TUSGroup).join(TUSTopic).filter(TUSSession.session_date == query_date).order_by(
            TUSSession.session_time).all()

        result = [
            {
                "session_id": s.id,
                "session_time": s.session_time.strftime('%H:%M:%S') if s.session_time else None,
                "group_name": s.name,
                "topic_title": s.title
            } for s in sessions
        ]
        return jsonify(result)


@app.get("/api/tus/sessions/<int:session_id>/attendance")
def get_attendance(session_id):
    """Pobiera listę uczestników i ich status obecności dla danej sesji."""
    with session_scope() as db_session:
        session = db_session.query(TUSSession).filter_by(id=session_id).first()
        if not session:
            return jsonify({"error": "Sesja nie znaleziona"}), 404

        members = db_session.query(Client.id, Client.full_name) \
            .join(TUSGroupMember) \
            .filter(TUSGroupMember.group_id == session.group_id).order_by(Client.full_name).all()

        attendance_records = db_session.query(TUSSessionAttendance) \
            .filter_by(session_id=session_id).all()

        attendance_map = {rec.client_id: rec.status for rec in attendance_records}

        return jsonify({
            "group_name": session.group.name,
            "members": [{"id": m.id, "full_name": m.full_name} for m in members],
            "attendance": attendance_map
        })


@app.post("/api/tus/sessions/<int:session_id>/attendance")
def save_attendance(session_id):
    """Zapisuje listę obecności dla sesji."""
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "Oczekiwano listy obiektów."}), 400

    with session_scope() as db_session:
        # Usuń stare wpisy, aby uniknąć konfliktów
        db_session.query(TUSSessionAttendance).filter_by(session_id=session_id).delete()

        # Dodaj nowe wpisy
        for item in data:
            new_attendance = TUSSessionAttendance(
                session_id=session_id,
                client_id=item['client_id'],
                status=item['status']
            )
            db_session.add(new_attendance)

    return jsonify({"message": "Obecność zapisana pomyślnie."}), 200


@app.route('/api/daily-attendance', methods=['GET'])
def get_daily_attendance():
    try:
        date = request.args.get('date')
        if not date:
            return jsonify({'error': 'Date parameter is required'}), 400

        with session_scope() as db_session:
            # Pobierz obecność z tabeli individual_session_attendance
            attendance_data = db_session.query(
                IndividualSessionAttendance,
                ScheduleSlot,
                Client
            ).join(
                ScheduleSlot, IndividualSessionAttendance.slot_id == ScheduleSlot.id
            ).join(
                Client, ScheduleSlot.client_id == Client.id
            ).filter(
                func.date(ScheduleSlot.starts_at) == date
            ).all()

            result = []
            for attendance, slot, client in attendance_data:
                result.append({
                    'client_id': client.id,
                    'status': attendance.status,
                    'notes': '',
                    'session_time': slot.starts_at.strftime('%H:%M') if slot.starts_at else '09:00',
                    'service_type': slot.kind,
                    'therapist_id': slot.therapist_id
                })

            return jsonify(result)

    except Exception as e:
        print(f"Błąd w /api/daily-attendance: {str(e)}")
        return jsonify([])


@app.get("/api/clients/<int:client_id>/all-attendance")
def get_client_all_attendance(client_id):
    """Zwraca kompletny miesięczny raport obecności (TUS + indywidualne) dla klienta."""
    month_str = request.args.get('month')
    if not month_str:
        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        return jsonify({"error": "Nieprawidłowy format miesiąca."}), 400

    with session_scope() as db_session:
        # 1. Pobierz obecności z sesji TUS
        tus_records = db_session.query(
            TUSSession.session_date.label("date"),
            TUSSessionAttendance.status,
            TUSGroup.name.label('group_name'),
            TUSTopic.title.label('topic_title')
        ).join(TUSSessionAttendance).join(TUSGroup).join(TUSTopic) \
            .filter(
            TUSSessionAttendance.client_id == client_id,
            func.extract('year', TUSSession.session_date) == year,
            func.extract('month', TUSSession.session_date) == month
        ).all()

        # 2. Pobierz obecności ze spotkań indywidualnych
        individual_records = db_session.query(
            ScheduleSlot.starts_at.label("date"),
            IndividualSessionAttendance.status,
            Therapist.full_name.label('therapist_name')
        ).join(IndividualSessionAttendance) \
            .join(Therapist, Therapist.id == ScheduleSlot.therapist_id) \
            .filter(
            ScheduleSlot.client_id == client_id,
            ScheduleSlot.kind == 'therapy',
            func.extract('year', ScheduleSlot.starts_at) == year,
            func.extract('month', ScheduleSlot.starts_at) == month
        ).all()

        # 3. Połącz i sformatuj wyniki
        all_records = []
        for record in tus_records:
            all_records.append({
                "date": record.date.isoformat(),
                "description": f"Grupa: {record.group_name}",
                "details": f"Temat: {record.topic_title}",
                "status": record.status
            })

        for record in individual_records:
            all_records.append({
                "date": record.date.isoformat(),
                "description": "Spotkanie indywidualne",
                "details": f"Terapeuta: {record.therapist_name}",
                "status": record.status
            })

        # Sortuj po dacie
        all_records.sort(key=lambda x: x['date'])

        return jsonify(all_records)


@app.get("/api/individual-sessions-for-day")
def get_individual_sessions_for_day():
    """Zwraca listę indywidualnych sesji terapeutycznych dla podanej daty wraz z ich statusem obecności."""
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Parametr 'date' jest wymagany."}), 400

    try:
        query_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Nieprawidłowy format daty."}), 400

    with session_scope() as db_session:
        sessions = db_session.query(
            ScheduleSlot.id.label("slot_id"),
            ScheduleSlot.starts_at,
            Client.full_name.label("client_name"),
            Therapist.full_name.label("therapist_name"),
            IndividualSessionAttendance.status.label("attendance_status")
        ).join(Client, Client.id == ScheduleSlot.client_id) \
            .join(Therapist, Therapist.id == ScheduleSlot.therapist_id) \
            .outerjoin(IndividualSessionAttendance, ScheduleSlot.id == IndividualSessionAttendance.slot_id) \
            .filter(
            func.date(ScheduleSlot.starts_at) == query_date,
            ScheduleSlot.kind == 'therapy'
        ).order_by(ScheduleSlot.starts_at).all()

        result = [
            {
                "slot_id": s.slot_id,
                "starts_at": s.starts_at.isoformat(),
                "client_name": s.client_name,
                "therapist_name": s.therapist_name,
                "attendance_status": s.attendance_status or 'obecny'  # Domyślnie 'obecny', jeśli brak wpisu
            } for s in sessions
        ]
        return jsonify(result)


@app.patch("/api/individual-attendance/<int:slot_id>")
def update_individual_attendance(slot_id):
    """Aktualizuje lub tworzy (UPSERT) status obecności dla pojedynczego slotu."""
    data = request.get_json()
    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "Status jest wymagany."}), 400

    with session_scope() as db_session:
        # Spróbuj znaleźć istniejący wpis
        attendance_record = db_session.query(IndividualSessionAttendance).filter_by(slot_id=slot_id).first()

        if attendance_record:
            # Jeśli istnieje, zaktualizuj
            attendance_record.status = new_status
        else:
            # Jeśli nie istnieje, stwórz nowy
            new_attendance = IndividualSessionAttendance(slot_id=slot_id, status=new_status)
            db_session.add(new_attendance)

    return jsonify({"message": "Status obecności zaktualizowany."})


@app.get("/individual_attendance.html")
def individual_attendance_page():
    # Tutaj można dodać @login_required, jeśli strona ma być chroniona
    return app.send_static_file("individual_attendance.html")


def find_best_match(name_to_find, name_list):
    """Prosta funkcja do znajdowania najlepszego dopasowania na liście nazw."""
    if not name_to_find or not name_list:
        return None

    name_to_find_lower = name_to_find.lower()

    for name in name_list:
        if name.lower() == name_to_find_lower:
            return name
    for name in name_list:
        if name.lower().startswith(name_to_find_lower) or name_to_find_lower.startswith(name.lower()):
            return name

    return None


@app.post("/api/parse-schedule-image")
def parse_schedule_image():
    """Parsuje obraz harmonogramu i dopasowuje skrócone nazwy do pełnych z bazy"""
    if 'schedule_image' not in request.files:
        return jsonify({"error": "Brak pliku obrazu w zapytaniu."}), 400

    # Pobierz kontekst z formularza
    scope = request.form.get('scope')
    therapist_from_form = request.form.get('therapist_name')
    date_from_form = request.form.get('date') if scope == 'day' else None
    month_from_form = request.form.get('month') if scope == 'month' else None

    if not therapist_from_form or (scope == 'day' and not date_from_form) or (scope == 'month' and not month_from_form):
        return jsonify({"error": "Zakres, data/miesiąc i terapeuta są wymagani."}), 400

    file = request.files['schedule_image']

    try:
        image = Image.open(file.stream).convert("RGB")
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        return jsonify({"error": f"Błąd przetwarzania obrazu: {e}"}), 500

    # Pobierz dane z bazy
    with session_scope() as db_session:
        all_clients = [c.full_name for c in db_session.query(Client).all()]
        all_groups = [g.name for g in db_session.query(TUSGroup).all()]

    # Przygotuj prompt dla AI
    if scope == 'month':
        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "date": {"type": "STRING", "description": "Data w formacie RRRR-MM-DD"},
                    "start_time": {"type": "STRING"},
                    "end_time": {"type": "STRING"},
                    "client_name": {"type": "STRING"},
                    "type": {"type": "STRING"}
                },
                "required": ["date", "start_time", "end_time", "client_name", "type"]
            }
        }
        prompt = f"""
            Przeanalizuj obraz harmonogramu dla miesiąca {month_from_form}, terapeuta: {therapist_from_form}.

            Dostępni klienci: {', '.join(all_clients[:10])}... (łącznie {len(all_clients)})
            Dostępne grupy: {', '.join(all_groups)}

            Dla każdego wpisu podaj: datę, godziny, nazwę klienta/grupy, typ zajęć (indywidualne/tus).
            Dopasuj skrócone nazwy do pełnych z listy.
            """
    else:
        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start_time": {"type": "STRING"},
                    "end_time": {"type": "STRING"},
                    "client_name": {"type": "STRING"},
                    "type": {"type": "STRING"}
                },
                "required": ["start_time", "end_time", "client_name", "type"]
            }
        }
        prompt = f"""
            Przeanalizuj obraz harmonogramu dla dnia {date_from_form}, terapeuta: {therapist_from_form}.

            Dostępni klienci: {', '.join(all_clients[:10])}... (łącznie {len(all_clients)})
            Dostępne grupy: {', '.join(all_groups)}

            Wyodrębnij godziny, nazwy klientów/grup, typ zajęć.
            Dopasuj skrócone nazwy do pełnych z listy.
            """

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/png", "data": img_str}}
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    # Użyj swojego klucza API
    api_key = "AIzaSyDbkt_jhBU9LNd40MAJm1GazLUPeywYo1E"
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"
    current_timeout = 90

    # Pętla do obsługi timeout'ów i ponownych prób
    while True:
        try:
            # PRÓBA WYSŁANIA ZAPYTANIA
            response = requests.post(
                api_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=current_timeout  # Używamy bieżącej wartości timeout
            )
            # Jeśli żądanie się powiodło, sprawdź status HTTP (np. 200)
            response.raise_for_status()

            # Sukces - przejdź do przetwarzania odpowiedzi
            result = response.json()

            # === LOGIKA PRZETWARZANIA WYNIKU API ===

            # 1. Sprawdzenie, czy AI zwróciło kandydatów
            if 'candidates' not in result or not result['candidates']:
                # Zgłaszamy wyjątek, aby przejść do ogólnej obsługi błędu na dole
                raise Exception("AI nie zwróciło wyników w 'candidates'.")

            # 2. Parsowanie JSON-a z odpowiedzi tekstowej
            json_text = result['candidates'][0]['content']['parts'][0]['text']
            # Uwaga: używamy 'json.loads' z zaimportowanego modułu 'json'
            parsed_data = json.loads(json_text)

            # 3. Dopasowanie nazw (zakładając, że te zmienne/funkcje są dostępne w kontekście funkcji)
            processed_data = []
            for item in parsed_data:
                original_name = item.get('client_name', '')

                if item.get('type', '').lower() == 'tus':
                    matched_name = find_best_match(original_name, all_groups)
                else:
                    matched_name = find_best_match(original_name, all_clients)

                processed_item = {
                    'date': item.get('date', date_from_form),
                    'start_time': item.get('start_time'),
                    'end_time': item.get('end_time'),
                    'client_name': matched_name or original_name,
                    'type': item.get('type', 'indywidualne'),
                    'therapist_name': therapist_from_form,
                    'original_name': original_name,
                    'matched': matched_name is not None
                }
                processed_data.append(processed_item)

            # 4. Zakończenie sukcesem i zwrócenie wyniku (zakładając użycie Flask/Django 'jsonify')
            return jsonify({
                "success": True,
                "data": processed_data,
                "matched_count": len([d for d in processed_data if d['matched']]),
                "total_count": len(processed_data)
            })

        except ReadTimeout as e:
            # === OBSŁUGA BŁĘDU TIMEOUT I PŁYTANIE O KONTYNUACJĘ ===
            print(f"Błąd w parse_schedule_image: ReadTimeout po {current_timeout} sekundach.")
            print("Serwer API zbyt długo przetwarzał obraz (prawdopodobnie skomplikowany rękopis).")

            user_input = input("Czy chcesz spróbować ponownie z wydłużonym limitem czasu (np. +90 sekund)? (T/N): ")

            if user_input.lower() == 't':
                current_timeout += 90
                print(f"Ponowna próba z limitem czasu: {current_timeout} sekund.")
                continue  # Kontynuuje pętlę while True
            else:
                print("Anulowano przez użytkownika.")
                # Przekazanie błędu do ogólnej obsługi błędu na końcu funkcji
                raise e

        except requests.exceptions.RequestException as e:
            # Obsługa innych błędów requests (np. ConnectionError, błędy HTTP z raise_for_status)
            print(f"Wystąpił błąd podczas komunikacji z API: {e}")
            # Przekazanie błędu do ogólnej obsługi błędu na końcu funkcji
            raise e

    # Obsługa wszystkich innych błędów, które nie są ReadTimeout lub RequestException,
    # albo tych, które zostały zgłoszone wewnątrz bloków 'except' (za pomocą 'raise e')
    # Ta sekcja powinna znajdować się POZA pętlą 'while True' i obsługiwać wszystkie wyjątki w funkcji
    try:
        # Ten fragment jest tylko demonstracyjny.
        # W rzeczywistym kodzie funkcji 'parse_schedule_image' powinna to być ostatnia sekcja.
        pass
    except Exception as e:
        # Wystąpił błąd poza pętlą (lub został do niej przekazany przez 'raise e')
        print(f"Błąd w parse_schedule_image: {traceback.format_exc()}")
        return jsonify({"error": f"Wystąpił błąd: {str(e)}"}), 500




@app.get("/api/test-name-matching")
def test_name_matching():
    """Endpoint do testowania dopasowywania nazw - dla diagnostyki"""
    name_to_match = request.args.get('name')

    with session_scope() as db_session:
        all_clients = [c.full_name for c in db_session.query(Client).all()]
        all_groups = [g.name for g in db_session.query(TUSGroup).all()]

    print(f"\n=== TEST DOPASOWYWANIA DLA: '{name_to_match}' ===")

    client_match = find_best_match(name_to_match, all_clients)
    group_match = find_best_match(name_to_match, all_groups)

    # Znajdź wszystkich klientów którzy mogą pasować
    potential_client_matches = []
    for client in all_clients:
        if name_to_match.lower() in client.lower():
            potential_client_matches.append(client)

    return jsonify({
        'input': name_to_match,
        'client_match': client_match,
        'group_match': group_match,
        'potential_matches': potential_client_matches,
        'available_clients': all_clients,
        'available_groups': all_groups
    })


@app.before_request
def list_routes():
    if request.endpoint:
        print(f"Endpoint: {request.endpoint}, Method: {request.method}")


# Lub dodaj specjalny endpoint do wyświetlenia wszystkich routes:
@app.route("/api/routes")
def list_all_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'path': str(rule)
        })
    return jsonify(routes)


@app.before_request
def check_file_size():
    if request.method == 'POST' and request.path == '/api/parse-schedule-image':
        # Sprawdź rozmiar content-length
        content_length = request.content_length or 0
        max_size = 10 * 1024 * 1024  # 10MB

        if content_length > max_size:
            return jsonify({'error': 'File too large'}), 413


@app.route('/api/health')
def health_check():
    memory_info = psutil.Process(os.getpid()).memory_info()
    return jsonify({
        'status': 'healthy',
        'memory_usage_mb': memory_info.rss / 1024 / 1024,
        'memory_percent': psutil.virtual_memory().percent
    })


# ===== DODAJ TEN ENDPOINT PRZED OSTATNIĄ LINIĄ =====

@app.post("/api/save-parsed-schedule")
def save_parsed_schedule():
    """Zapisuje przetworzone dane harmonogramu do bazy"""
    print("=== ENDPOINT save_parsed_schedule WYWOŁANY ===")

    try:
        data = request.get_json()
        print(f"Otrzymane dane: {data}")

        if not isinstance(data, list):
            return jsonify({
                "success": False,
                "error": "Oczekiwano tablicy obiektów.",
                "saved_count": 0,
                "total_count": 0,
                "errors": []
            }), 400

        saved_count = 0
        errors = []

        with session_scope() as db_session:
            # Pobierz mapowania nazw do ID
            therapists = db_session.query(Therapist).all()
            clients = db_session.query(Client).all()
            groups = db_session.query(TUSGroup).all()

            therapists_map = {t.full_name.lower(): t.id for t in therapists}
            clients_map = {c.full_name.lower(): c.id for c in clients}
            groups_map = {g.name.lower(): g.id for g in groups}

            print(f"Dostępni terapeuci: {list(therapists_map.keys())}")
            print(f"Dostępni klienci: {list(clients_map.keys())[:5]}...")
            print(f"Dostępne grupy: {list(groups_map.keys())}")

            # KROK 1: Najpierw sprawdź wszystkie konflikty
            conflicts_found = []
            valid_items = []

            for i, item in enumerate(data):
                try:
                    print(f"Sprawdzanie wiersza {i + 1}: {item}")

                    # Walidacja wymaganych pól
                    required_fields = ['date', 'start_time', 'end_time', 'client_name', 'therapist_name', 'type']
                    missing_fields = [field for field in required_fields if not item.get(field)]
                    if missing_fields:
                        errors.append(f"Wiersz {i + 1}: Brak pól: {', '.join(missing_fields)}")
                        continue

                    # Znajdź ID terapeuty
                    therapist_name = item['therapist_name'].lower()
                    if therapist_name not in therapists_map:
                        errors.append(f"Wiersz {i + 1}: Nieznany terapeuta '{item['therapist_name']}'")
                        continue
                    therapist_id = therapists_map[therapist_name]

                    # Przygotuj daty
                    try:
                        starts_at = datetime.fromisoformat(f"{item['date']}T{item['start_time']}:00").replace(tzinfo=TZ)
                        ends_at = datetime.fromisoformat(f"{item['date']}T{item['end_time']}:00").replace(tzinfo=TZ)
                    except ValueError as e:
                        errors.append(f"Wiersz {i + 1}: Nieprawidłowy format daty/czasu - {e}")
                        continue

                    # Sprawdź czy klient/grupa istnieje
                    client_name = item['client_name'].lower()
                    item_type = item.get('type', '').lower()

                    if item_type == 'tus':
                        if client_name not in groups_map:
                            errors.append(f"Wiersz {i + 1}: Nieznana grupa TUS '{item['client_name']}'")
                            continue
                    else:
                        if client_name not in clients_map:
                            errors.append(f"Wiersz {i + 1}: Nieznany klient '{item['client_name']}'")
                            continue

                    # Sprawdź konflikty czasowe
                    try:
                        conflicts = find_overlaps(db_session.connection(), therapist_id=therapist_id,
                                                  starts_at=starts_at, ends_at=ends_at)
                        if conflicts:
                            conflict_msg = f"Wiersz {i + 1}: Konflikt czasowy {item['start_time']}-{item['end_time']} z istniejącymi zajęciami"
                            conflicts_found.append(conflict_msg)
                            errors.append(conflict_msg)
                            print(f"  → KONFLIKT: {conflict_msg}")
                            continue
                    except Exception as e:
                        print(f"Ostrzeżenie: Błąd sprawdzania konfliktów: {e}")
                        # Kontynuuj mimo błędu sprawdzania konfliktów

                    # Jeśli wszystko OK, dodaj do listy poprawnych
                    valid_items.append({
                        'index': i,
                        'item': item,
                        'therapist_id': therapist_id,
                        'starts_at': starts_at,
                        'ends_at': ends_at,
                        'item_type': item_type,
                        'client_name': client_name
                    })

                    print(f"  → Wiersz {i + 1} OK")

                except Exception as e:
                    error_msg = f"Wiersz {i + 1}: Błąd walidacji - {str(e)}"
                    errors.append(error_msg)
                    print(f"  → BŁĄD: {error_msg}")
                    continue

            print(f"Znaleziono {len(valid_items)} poprawnych wpisów do zapisania")
            print(f"Znaleziono {len(conflicts_found)} konfliktów")

            # KROK 2: Zapisz tylko poprawne wpisy bez konfliktów
            for valid in valid_items:
                i = valid['index']
                item = valid['item']
                therapist_id = valid['therapist_id']
                starts_at = valid['starts_at']
                ends_at = valid['ends_at']
                item_type = valid['item_type']
                client_name = valid['client_name']

                try:
                    if item_type == 'tus':
                        # Zapisz sesję TUS
                        group_id = groups_map[client_name]
                        new_session = TUSSession(
                            group_id=group_id,
                            topic_id=1,  # domyślny temat
                            session_date=starts_at.date(),
                            session_time=starts_at.time()
                        )
                        db_session.add(new_session)
                        print(f"  → Zapisano sesję TUS: {item['client_name']}")

                    else:
                        # Zapisz sesję indywidualną
                        client_id = clients_map[client_name]

                        # Utwórz grupę wydarzeń
                        new_group_id = uuid.uuid4()
                        new_event_group = EventGroup(
                            id=new_group_id,
                            client_id=client_id,
                            label=f"Import {item['date']} {item['client_name']}"
                        )

                        # Utwórz slot terapii z session_id aby uniknąć konfliktów
                        session_id = str(uuid.uuid4())
                        new_slot = ScheduleSlot(
                            group_id=new_group_id,
                            client_id=client_id,
                            therapist_id=therapist_id,
                            kind='therapy',
                            starts_at=starts_at,
                            ends_at=ends_at,
                            status='planned',
                            session_id=session_id  # Ważne: ustaw session_id
                        )

                        db_session.add(new_event_group)
                        db_session.add(new_slot)
                        print(f"  → Zapisano sesję indywidualną: {item['client_name']}")

                    saved_count += 1

                except Exception as e:
                    error_msg = f"Wiersz {i + 1}: Błąd zapisu - {str(e)}"
                    errors.append(error_msg)
                    print(f"  → BŁĄD ZAPISU: {error_msg}")

        print(f"=== ZAPIS ZAKOŃCZONY: {saved_count}/{len(data)} ===")

        return jsonify({
            "success": True,
            "saved_count": saved_count,
            "total_count": len(data),
            "errors": errors,
            "conflicts_count": len(conflicts_found),
            "message": f"Zapisano {saved_count} z {len(data)} wpisów. Znaleziono {len(conflicts_found)} konfliktów."
        })

    except Exception as e:
        print(f"BŁĄD KRYTYCZNY w save_parsed_schedule: {traceback.format_exc()}")
        return jsonify({
            "success": False,
            "error": f"Wewnętrzny błąd serwera: {str(e)}",
            "saved_count": 0,
            "total_count": 0,
            "errors": []
        }), 500


@app.route('/api/scheduled-clients', methods=['GET'])
def get_scheduled_clients():
    try:
        date = request.args.get('date')
        if not date:
            return jsonify({'error': 'Date parameter is required'}), 400

        with session_scope() as db_session:
            # Sprawdź czy tabela schedule istnieje
            try:
                # Pobierz klientów z zaplanowanymi zajęciami na daną datę
                scheduled_clients = db_session.query(Client).join(
                    ScheduleSlot, Client.id == ScheduleSlot.client_id
                ).filter(
                    func.date(ScheduleSlot.starts_at) == date,
                    Client.active == True
                ).order_by(Client.full_name).all()

                result = []
                for client in scheduled_clients:
                    # Znajdź slot dla tego klienta w wybranej dacie
                    slot = db_session.query(ScheduleSlot).filter(
                        ScheduleSlot.client_id == client.id,
                        func.date(ScheduleSlot.starts_at) == date
                    ).first()

                    result.append({
                        'client_id': client.id,
                        'full_name': client.full_name,
                        'phone': client.phone,
                        'session_time': slot.starts_at.strftime('%H:%M') if slot else '09:00',
                        'service_type': slot.kind if slot else 'therapy',
                        'therapist_id': slot.therapist_id if slot else 1,
                        'therapist_name': 'Do ustalenia',  # Możesz dodać join do therapists
                        'service_name': 'Zajęcia terapeutyczne'
                    })

                return jsonify(result)

            except Exception as table_error:
                print(f"Tabela schedule nie istnieje, używam wszystkich klientów: {table_error}")

                # Fallback: wszyscy aktywni klienci
                clients = db_session.query(Client).filter(Client.active == True).order_by(Client.full_name).all()

                scheduled_clients = []
                for i, client in enumerate(clients):
                    scheduled_clients.append({
                        'client_id': client.id,
                        'full_name': client.full_name,
                        'phone': client.phone,
                        'session_time': f"{(9 + i % 6):02d}:00",
                        'service_type': 'therapy',
                        'therapist_id': (i % 3) + 1,
                        'therapist_name': ['Anna Kowalska', 'Piotr Nowak', 'Maria Wiśniewska'][i % 3],
                        'service_name': 'Terapia indywidualna'
                    })

                return jsonify(scheduled_clients)

    except Exception as e:
        print(f"Błąd w scheduled-clients: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance/bulk', methods=['POST'])
def save_bulk_attendance():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Brak danych JSON'}), 400

        date = data.get('date')
        attendance_list = data.get('attendance', [])

        if not date:
            return jsonify({'error': 'Date is required'}), 400

        print(f"Zapisuję obecność dla daty {date}, liczba wpisów: {len(attendance_list)}")

        saved_count = 0
        with session_scope() as db_session:
            for attendance_data in attendance_list:
                client_id = attendance_data.get('client_id')
                status = attendance_data.get('status')
                session_time = attendance_data.get('session_time', '09:00')
                service_type = attendance_data.get('service_type', 'therapy')
                therapist_id = attendance_data.get('therapist_id', 1)
                notes = attendance_data.get('notes', '')

                if not client_id or not status:
                    continue

                # Znajdź lub utwórz slot dla tego klienta i daty
                slot = db_session.query(ScheduleSlot).filter(
                    ScheduleSlot.client_id == client_id,
                    func.date(ScheduleSlot.starts_at) == date,
                    ScheduleSlot.kind == 'therapy'
                ).first()

                if not slot:
                    # Utwórz nowy slot jeśli nie istnieje
                    starts_at = datetime.strptime(f"{date} {session_time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                    ends_at = starts_at + timedelta(hours=1)

                    slot = ScheduleSlot(
                        client_id=client_id,
                        therapist_id=therapist_id,
                        kind='therapy',
                        starts_at=starts_at,
                        ends_at=ends_at,
                        status='planned'
                    )
                    db_session.add(slot)
                    db_session.flush()  # Aby uzyskać ID

                # Znajdź lub utwórz wpis obecności
                attendance_record = db_session.query(IndividualSessionAttendance).filter_by(
                    slot_id=slot.id
                ).first()

                if attendance_record:
                    # Aktualizuj istniejący wpis
                    attendance_record.status = status
                else:
                    # Utwórz nowy wpis
                    new_attendance = IndividualSessionAttendance(
                        slot_id=slot.id,
                        status=status
                    )
                    db_session.add(new_attendance)

                saved_count += 1

        return jsonify({
            'message': f'Obecność zapisana pomyślnie',
            'count': saved_count,
            'date': date
        })

    except Exception as e:
        print(f"Błąd w /api/attendance/bulk: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily-attendance/bulk', methods=['POST'])
def save_daily_attendance_bulk():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Brak danych JSON'}), 400

        date = data.get('date')
        attendance_list = data.get('attendance', [])

        if not date:
            return jsonify({'error': 'Date is required'}), 400

        print(f"Zapisuję obecność dla daty {date}, liczba wpisów: {len(attendance_list)}")

        saved_count = 0
        with session_scope() as db_session:
            for attendance_data in attendance_list:
                client_id = attendance_data.get('client_id')
                status = attendance_data.get('status')
                session_time = attendance_data.get('session_time', '09:00')
                service_type = attendance_data.get('service_type', 'therapy')
                therapist_id = attendance_data.get('therapist_id', 1)
                notes = attendance_data.get('notes', '')

                if not client_id or not status:
                    continue

                # Znajdź lub utwórz slot dla tego klienta i daty
                slot = db_session.query(ScheduleSlot).filter(
                    ScheduleSlot.client_id == client_id,
                    func.date(ScheduleSlot.starts_at) == date,
                    ScheduleSlot.kind == 'therapy'
                ).first()

                if not slot:
                    # Utwórz nowy slot jeśli nie istnieje
                    starts_at = datetime.strptime(f"{date} {session_time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                    ends_at = starts_at + timedelta(hours=1)

                    slot = ScheduleSlot(
                        client_id=client_id,
                        therapist_id=therapist_id,
                        kind='therapy',
                        starts_at=starts_at,
                        ends_at=ends_at,
                        status='planned'
                    )
                    db_session.add(slot)
                    db_session.flush()

                # Znajdź lub utwórz wpis obecności
                attendance_record = db_session.query(IndividualSessionAttendance).filter_by(
                    slot_id=slot.id
                ).first()

                if attendance_record:
                    attendance_record.status = status
                else:
                    new_attendance = IndividualSessionAttendance(
                        slot_id=slot.id,
                        status=status
                    )
                    db_session.add(new_attendance)

                saved_count += 1

        return jsonify({
            'message': f'Obecność zapisana pomyślnie',
            'count': saved_count,
            'date': date
        })

    except Exception as e:
        print(f"Błąd w /api/daily-attendance/bulk: {str(e)}")
        return jsonify({'error': str(e)}), 500


# Funkcja do znalezienia duplikatów endpointów
def find_duplicate_endpoints():
    endpoints = {}
    duplicates = []

    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            duplicates.append(rule.endpoint)
        endpoints[rule.endpoint] = str(rule)

    return duplicates

    # Sprawdź duplikaty przy starcie
    duplicates = find_duplicate_endpoints()
    if duplicates:
        print(f"ZNALEZIONO DUPLIKATY ENDPOINTÓW: {duplicates}")
        # Możesz automatycznie wyjść jeśli chcesz
        # sys.exit


# ===== DODAJ TE ENDPOINTY =====

@app.route('/api/attendance', methods=['GET'])
def get_attendance_by_date():
    """Pobiera obecność dla konkretnej daty"""
    try:
        date = request.args.get('date')
        client_id = request.args.get('client_id', type=int)  # opcjonalny filtr

        if not date:
            return jsonify({'error': 'Date parameter is required'}), 400

        with session_scope() as db_session:
            # Pobierz obecność z połączeniem do slot i klienta
            query = db_session.query(
                IndividualSessionAttendance.status,
                ScheduleSlot.client_id,
                ScheduleSlot.starts_at,
                ScheduleSlot.therapist_id,
                ScheduleSlot.kind
            ).join(
                ScheduleSlot, IndividualSessionAttendance.slot_id == ScheduleSlot.id
            ).filter(
                func.date(ScheduleSlot.starts_at) == date
            )

            # Opcjonalny filtr na klienta
            if client_id:
                query = query.filter(ScheduleSlot.client_id == client_id)

            attendance_data = query.all()

            result = []
            for attendance in attendance_data:
                result.append({
                    'client_id': attendance.client_id,
                    'status': attendance.status,
                    'session_time': attendance.starts_at.strftime('%H:%M') if attendance.starts_at else '09:00',
                    'service_type': attendance.kind,
                    'therapist_id': attendance.therapist_id,
                    'notes': ''  # Dodaj jeśli masz kolumnę notes
                })

            return jsonify(result), 200

    except Exception as e:
        print(f"Błąd w /api/attendance: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload/client-photo', methods=['POST'])
def upload_client_photo():
    if 'photo' not in request.files:
        return jsonify({'error': 'Brak pliku'}), 400

    file = request.files['photo']
    client_name = request.form.get('client_name', 'client')

    # Walidacja
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
    if not file.filename.lower().endswith(tuple(allowed_extensions)):
        return jsonify({'error': 'Niedozwolony format pliku'}), 400

    # Zapisz plik
    import os
    import uuid
    filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
    filepath = os.path.join('uploads', 'clients', filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file.save(filepath)

    # Zwróć URL
    photo_url = f"/uploads/clients/{filename}"
    return jsonify({'photo_url': photo_url}), 200


def init_foundation_table():
    """Inicjalizacja tabeli foundation w PostgreSQL"""
    with engine.begin() as conn:
        conn.execute(text('''
                CREATE TABLE IF NOT EXISTS foundation (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    krs TEXT UNIQUE,
                    nip TEXT,
                    regon TEXT,
                    city TEXT,
                    voivodeship TEXT,
                    street TEXT,
                    building_number TEXT,
                    postal_code TEXT,
                    email TEXT,
                    phone TEXT,
                    board_members TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_foundation_krs 
                ON foundation(krs)
            '''))

    print("✓ Tabela foundation zainicjalizowana")


def init_projects_table():
    """Inicjalizacja tabeli projects w PostgreSQL (jeśli nie istnieje)"""
    with engine.begin() as conn:
        conn.execute(text('''
                CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    start_date DATE,
                    end_date DATE,
                    status VARCHAR(50) DEFAULT 'planowany',
                    budget FLOAT,
                    coordinator VARCHAR(255),
                    partners TEXT,
                    beneficiaries_count INTEGER,
                    photo_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_projects_status 
                ON projects(status)
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_projects_dates 
                ON projects(start_date, end_date)
            '''))

    print("✓ Tabela projects zainicjalizowana")


def init_all_tables():
    """Inicjalizacja wszystkich tabel aplikacji"""
    print("\n" + "=" * 60)
    print("INICJALIZACJA TABEL BAZY DANYCH")
    print("=" * 60)

    try:
        # Sprawdź połączenie z bazą
        with engine.begin() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✓ Połączono z PostgreSQL")
            print(f"  {version[:60]}...")

        # Automatyczne tworzenie tabel z modeli SQLAlchemy (w tym 'users')
        Base.metadata.create_all(bind=engine)
        print("✓ Tabele z modeli SQLAlchemy (Base.metadata) zainicjalizowane.")

        # Inicjalizuj dodatkowe tabele/indeksy (jeśli potrzebne)
        init_documents_table()  # Dokumenty klientów
        init_foundation_table()  # Dane fundacji
        init_projects_table()  # Projekty
        init_client_notes_table()
        init_journal_table()      # Dodano brakujące wywołanie
        init_waiting_clients_table() # Dodano brakujące wywołanie
        #init_absences_table()    # Dodano brakujące wywołanie

        print("=" * 60)
        print("✓ WSZYSTKIE TABELE GOTOWE")
        print("=" * 60 + "\n")

        return True

    except Exception as e:
        print("\n" + "=" * 60)
        print("✗ BŁĄD INICJALIZACJI")
        print("=" * 60)
        print(f"Błąd: {str(e)}")
        import traceback
        print(traceback.format_exc())
        print("=" * 60 + "\n")
        return False


def init_documents_table():
    """Inicjalizacja tabeli dokumentów w PostgreSQL"""
    with engine.begin() as conn:
        conn.execute(text('''
                CREATE TABLE IF NOT EXISTS client_documents (
                    id SERIAL PRIMARY KEY,
                    client_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    document_type TEXT,
                    notes TEXT,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    uploaded_by TEXT,
                    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
                )
            '''))

        conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_client_documents_client_id 
                ON client_documents(client_id)
            '''))

    print("✓ Tabela client_documents zainicjalizowana")


@app.route('/api/clients/<int:client_id>/documents', methods=['POST'])
def upload_client_documents(client_id):
    print(f"\n=== UPLOAD DOCUMENTS START dla klienta {client_id} ===")
    try:
        # Sprawdź czy klient istnieje
        with engine.begin() as conn:
            exists = conn.execute(
                text('SELECT 1 FROM clients WHERE id = :cid'),
                {"cid": client_id}
            ).scalar()
            print(f"Klient istnieje: {exists}")

            if not exists:
                return jsonify({'error': 'Klient nie istnieje'}), 404

        if 'files' not in request.files:
            print("Brak klucza 'files' w request.files")
            return jsonify({'error': 'Brak plików'}), 400

        files = request.files.getlist('files')
        print(f"Liczba plików: {len(files)}")

        if not files or files[0].filename == '':
            return jsonify({'error': 'Nie wybrano plików'}), 400

        document_type = request.form.get('document_type', 'Inne')
        notes = request.form.get('notes', '')
        uploaded_by = request.form.get('uploaded_by', 'system')

        uploaded_files = []
        errors = []

        for idx, file in enumerate(files):
            print(f"\n--- Przetwarzanie pliku {idx + 1}/{len(files)} ---")
            print(f"Nazwa: {file.filename}")

            if file and allowed_file(file.filename):
                try:
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0)
                    print(f"Rozmiar: {file_size} bajtów")

                    if file_size > MAX_FILE_SIZE:
                        errors.append(f'{file.filename}: Plik za duży')
                        continue

                    # Zapisz plik fizycznie
                    filepath = get_safe_filepath(client_id, file.filename)
                    file.save(filepath)
                    print(f"Plik zapisany: {filepath}")

                    file_type = mimetypes.guess_type(file.filename)[0] or 'application/octet-stream'
                    print(f"Typ MIME: {file_type}")

                    # KLUCZOWY MOMENT - zapis do bazy
                    print("Rozpoczynam zapis do bazy...")
                    with engine.begin() as conn:
                        result = conn.execute(text('''
                                INSERT INTO client_documents 
                                (client_id, file_name, file_path, file_type, file_size, 
                                 document_type, notes, uploaded_by)
                                VALUES (:cid, :fname, :fpath, :ftype, :fsize, :dtype, :notes, :uby)
                                RETURNING id
                            '''), {
                            "cid": client_id,
                            "fname": file.filename,
                            "fpath": filepath,
                            "ftype": file_type,
                            "fsize": file_size,
                            "dtype": document_type,
                            "notes": notes,
                            "uby": uploaded_by
                        })

                        doc_id = result.scalar()
                        print(f"SUKCES! Dokument zapisany w bazie, ID: {doc_id}")

                        uploaded_files.append({
                            'id': doc_id,
                            'file_name': file.filename,
                            'file_size': file_size
                        })

                except Exception as e:
                    print(f"BŁĄD dla pliku {file.filename}: {str(e)}")
                    import traceback
                    print(traceback.format_exc())
                    errors.append(f'{file.filename}: {str(e)}')

                    # Usuń plik fizyczny jeśli baza zawiodła
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        print(f"Usunięto plik fizyczny: {filepath}")
            else:
                print(f"Niedozwolony typ pliku: {file.filename}")
                errors.append(f'{file.filename}: Niedozwolony typ')

        print(f"\n=== UPLOAD ZAKOŃCZONY ===")
        print(f"Zapisane pliki: {len(uploaded_files)}")
        print(f"Błędy: {len(errors)}")

        response = {'count': len(uploaded_files), 'uploaded': uploaded_files}
        if errors:
            response['errors'] = errors

        return jsonify(response), 201

    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/clients/<int:client_id>/documents', methods=['GET'])
def get_client_documents(client_id):
    """Pobiera listę dokumentów klienta"""
    print(f"=== GET DOCUMENTS dla klienta {client_id} ===")
    try:
        with engine.begin() as conn:
            # Sprawdź czy klient istnieje
            exists = conn.execute(
                text('SELECT 1 FROM clients WHERE id = :cid'),
                {"cid": client_id}
            ).scalar()

            if not exists:
                print(f"Klient {client_id} nie istnieje")
                return jsonify({'error': 'Klient nie istnieje'}), 404

            # Pobierz dokumenty
            result = conn.execute(text('''
                    SELECT id, client_id, file_name, file_type, file_size,
                           document_type, notes, upload_date, uploaded_by
                    FROM client_documents
                    WHERE client_id = :cid
                    ORDER BY upload_date DESC
                '''), {"cid": client_id})

            documents = [dict(row) for row in result.mappings().all()]
            print(f"Znaleziono {len(documents)} dokumentów")
            return jsonify(documents), 200

    except Exception as e:
        print(f"Błąd: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/<int:doc_id>/download', methods=['GET'])
def download_document(doc_id):
    print(f"\n=== DOWNLOAD DOCUMENT ID: {doc_id} ===")
    try:
        with engine.begin() as conn:
            result = conn.execute(text('''
                    SELECT file_name, file_path, file_type
                    FROM client_documents WHERE id = :did
                '''), {"did": doc_id})

            row = result.mappings().first()

            if not row:
                return jsonify({'error': 'Dokument nie istnieje'}), 404

            file_path = os.path.normpath(row['file_path'])
            print(f"Ścieżka: {file_path}")

            if not os.path.exists(file_path):
                return jsonify({'error': 'Plik nie został znaleziony'}), 404

            # Użyj send_file z Flask (nie Werkzeug)
            from flask import send_file as flask_send_file
            return flask_send_file(
                file_path,
                mimetype=row['file_type'],
                as_attachment=True,
                download_name=row['file_name']
            )

    except Exception as e:
        print(f"Błąd: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/<int:doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text('SELECT file_path FROM client_documents WHERE id = :did'),
                {"did": doc_id}
            )
            row = result.mappings().first()

            if not row:
                return jsonify({'error': 'Dokument nie istnieje'}), 404

            file_path = row['file_path']
            if os.path.exists(file_path):
                os.remove(file_path)

            conn.execute(
                text('DELETE FROM client_documents WHERE id = :did'),
                {"did": doc_id}
            )

            return jsonify({'message': 'Dokument usunięty'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === PROJECTS API ===

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Lista wszystkich projektów"""
    status_filter = request.args.get('status')  # opcjonalny filtr

    with engine.begin() as conn:
        sql = text("""
                SELECT id, title, description, start_date, end_date, status, 
                       budget, coordinator, partners, beneficiaries_count, photo_url,
                       created_at, updated_at
                FROM projects
                WHERE (:status IS NULL OR status = :status)
                ORDER BY start_date DESC NULLS LAST, created_at DESC
            """)

        result = conn.execute(sql, {"status": status_filter})
        projects = []

        for row in result.mappings().all():
            project = dict(row)
            # Konwertuj daty na stringi
            if project['start_date']:
                project['start_date'] = project['start_date'].isoformat()
            if project['end_date']:
                project['end_date'] = project['end_date'].isoformat()
            if project['created_at']:
                project['created_at'] = project['created_at'].isoformat()
            if project['updated_at']:
                project['updated_at'] = project['updated_at'].isoformat()
            projects.append(project)

        return jsonify(projects), 200


@app.route('/api/projects/<int:project_id>', methods=['GET'])
def get_project(project_id):
    """Szczegóły pojedynczego projektu"""
    with engine.begin() as conn:
        sql = text("""
                SELECT id, title, description, start_date, end_date, status, 
                       budget, coordinator, partners, beneficiaries_count, photo_url,
                       created_at, updated_at
                FROM projects
                WHERE id = :pid
            """)

        result = conn.execute(sql, {"pid": project_id})
        row = result.mappings().first()

        if not row:
            return jsonify({'error': 'Projekt nie znaleziony'}), 404

        project = dict(row)
        if project['start_date']:
            project['start_date'] = project['start_date'].isoformat()
        if project['end_date']:
            project['end_date'] = project['end_date'].isoformat()
        if project['created_at']:
            project['created_at'] = project['created_at'].isoformat()
        if project['updated_at']:
            project['updated_at'] = project['updated_at'].isoformat()

        return jsonify(project), 200


@app.route('/api/projects', methods=['POST'])
def create_project():
    """Tworzenie nowego projektu"""
    data = request.get_json(silent=True) or {}

    if not data.get('title'):
        return jsonify({'error': 'Tytuł jest wymagany'}), 400

    with engine.begin() as conn:
        sql = text("""
                INSERT INTO projects 
                (title, description, start_date, end_date, status, budget, 
                 coordinator, partners, beneficiaries_count, photo_url)
                VALUES (:title, :desc, :start, :end, :status, :budget, 
                        :coord, :partners, :benef, :photo)
                RETURNING id
            """)

        result = conn.execute(sql, {
            "title": data['title'],
            "desc": data.get('description'),
            "start": data.get('start_date'),
            "end": data.get('end_date'),
            "status": data.get('status', 'planowany'),
            "budget": data.get('budget'),
            "coord": data.get('coordinator'),
            "partners": data.get('partners'),
            "benef": data.get('beneficiaries_count'),
            "photo": data.get('photo_url')
        })

        new_id = result.scalar()
        return jsonify({'id': new_id, 'message': 'Projekt utworzony'}), 201


@app.route('/api/projects/<int:project_id>', methods=['PUT'])
def update_project(project_id):
    """Aktualizacja projektu"""
    data = request.get_json(silent=True) or {}

    if not data.get('title'):
        return jsonify({'error': 'Tytuł jest wymagany'}), 400

    with engine.begin() as conn:
        sql = text("""
                UPDATE projects
                SET title = :title,
                    description = :desc,
                    start_date = :start,
                    end_date = :end,
                    status = :status,
                    budget = :budget,
                    coordinator = :coord,
                    partners = :partners,
                    beneficiaries_count = :benef,
                    photo_url = :photo,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :pid
                RETURNING id
            """)

        result = conn.execute(sql, {
            "pid": project_id,
            "title": data['title'],
            "desc": data.get('description'),
            "start": data.get('start_date'),
            "end": data.get('end_date'),
            "status": data.get('status', 'planowany'),
            "budget": data.get('budget'),
            "coord": data.get('coordinator'),
            "partners": data.get('partners'),
            "benef": data.get('beneficiaries_count'),
            "photo": data.get('photo_url')
        })

        if not result.scalar():
            return jsonify({'error': 'Projekt nie znaleziony'}), 404

        return jsonify({'message': 'Projekt zaktualizowany'}), 200


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    """Usuwanie projektu"""
    with engine.begin() as conn:
        sql = text("DELETE FROM projects WHERE id = :pid RETURNING id")
        result = conn.execute(sql, {"pid": project_id})

        if not result.scalar():
            return jsonify({'error': 'Projekt nie znaleziony'}), 404

        return jsonify({'message': 'Projekt usunięty'}), 200


@app.get("/api/projects/report")
def get_projects_report():
    """Generuje raport merytoryczny dla wybranego roku"""
    year = request.args.get("year", type=int)
    if not year:
        year = datetime.now().year

    with engine.begin() as conn:
        # Projekty z danego roku
        sql = text("""
                SELECT 
                    id, title, description, status, 
                    start_date, end_date, budget, 
                    coordinator, partners, beneficiaries_count,
                    photo_url
                FROM projects
                WHERE 
                    EXTRACT(YEAR FROM start_date) = :year
                    OR EXTRACT(YEAR FROM end_date) = :year
                    OR (start_date <= :year_end AND (end_date >= :year_start OR end_date IS NULL))
                ORDER BY start_date, title
            """)

        projects = conn.execute(sql, {
            "year": year,
            "year_start": f"{year}-01-01",
            "year_end": f"{year}-12-31"
        }).mappings().all()

        # Podsumowanie
        total_projects = len(projects)
        completed_projects = sum(1 for p in projects if p['status'] == 'zakończony')
        total_beneficiaries = sum(p['beneficiaries_count'] or 0 for p in projects)
        total_budget = sum(float(p['budget'] or 0) for p in projects)

        return jsonify({
            "year": year,
            "summary": {
                "total_projects": total_projects,
                "completed_projects": completed_projects,
                "total_beneficiaries": total_beneficiaries,
                "total_budget": total_budget
            },
            "projects": [dict(p) for p in projects]
        })


def fetch_krs_data(krs_number):
    """
        Pobieranie danych z KRS przez API
        Używa publicznego API MS (api.stat.gov.pl) lub rejestr.io
        """
    try:
        # Próba 1: API MS (Ministerstwo Sprawiedliwości)
        # Uwaga: To jest przykładowy endpoint - w praktyce trzeba użyć prawdziwego API
        url = f"https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs_number}"

        headers = {
            'Accept': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return parse_krs_response(data)

        # Próba 2: Alternatywne API (rejestr.io)
        url_alt = f"https://rejestr.io/api/v1/krs/{krs_number}"
        response_alt = requests.get(url_alt, timeout=10)

        if response_alt.status_code == 200:
            data_alt = response_alt.json()
            return parse_rejestr_io_response(data_alt)

        return None

    except Exception as e:
        print(f"Błąd pobierania danych KRS: {e}")
        return None


def parse_krs_response(data):
    """Parsowanie odpowiedzi z oficjalnego API MS"""
    try:
        foundation_data = {
            'name': data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('danePodmiotu', {}).get('nazwa', ''),
            'krs': data.get('odpis', {}).get('naglowekA', {}).get('numerKRS', ''),
            'nip': data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('danePodmiotu', {}).get('identyfikatory',
                                                                                                       {}).get('nip',
                                                                                                               ''),
            'regon': data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('danePodmiotu', {}).get(
                'identyfikatory', {}).get('regon', ''),
        }

        # Adres siedziby
        adres = data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('siedzibaIAdres', {}).get('adres', {})
        foundation_data['city'] = adres.get('miejscowosc', '')
        foundation_data['voivodeship'] = adres.get('wojewodztwo', '')
        foundation_data['street'] = adres.get('ulica', '')
        foundation_data['building_number'] = adres.get('nrDomu', '')
        foundation_data['postal_code'] = adres.get('kodPocztowy', '')

        # Zarząd
        board_members = []
        zarzad = data.get('odpis', {}).get('dane', {}).get('dzial2', {}).get('reprezentacja', {}).get('czlonkowie', [])
        for member in zarzad:
            name = member.get('imieNazwisko', '')
            function = member.get('funkcja', '')
            if name:
                board_members.append(f"{name} - {function}")
        foundation_data['board_members'] = '\n'.join(board_members)

        return foundation_data

    except Exception as e:
        print(f"Błąd parsowania danych KRS: {e}")
        return None


def parse_rejestr_io_response(data):
    """Parsowanie odpowiedzi z alternatywnego API rejestr.io"""
    try:
        foundation_data = {
            'name': data.get('nazwa', ''),
            'krs': data.get('krs', ''),
            'nip': data.get('nip', ''),
            'regon': data.get('regon', ''),
            'city': data.get('adres', {}).get('miejscowosc', ''),
            'voivodeship': data.get('adres', {}).get('wojewodztwo', ''),
            'street': data.get('adres', {}).get('ulica', ''),
            'building_number': data.get('adres', {}).get('nr_domu', ''),
            'postal_code': data.get('adres', {}).get('kod_pocztowy', ''),
        }

        # Zarząd
        board_members = []
        for member in data.get('reprezentacja', []):
            name = member.get('imie_nazwisko', '')
            function = member.get('funkcja', '')
            if name:
                board_members.append(f"{name} - {function}")
        foundation_data['board_members'] = '\n'.join(board_members)

        return foundation_data

    except Exception as e:
        print(f"Błąd parsowania danych z rejestr.io: {e}")
        return None


@app.route('/api/foundation/fetch-krs', methods=['POST'])
def fetch_and_save_krs():
    """Endpoint do pobierania danych z KRS i zapisywania w bazie"""
    try:
        data = request.get_json()
        krs_number = data.get('krs', '').strip()

        if not krs_number:
            return jsonify({'error': 'Numer KRS jest wymagany'}), 400

        # Pobierz dane z KRS
        foundation_data = fetch_krs_data(krs_number)

        if not foundation_data:
            return jsonify({'error': 'Nie udało się pobrać danych z KRS. Sprawdź numer KRS lub spróbuj później.'}), 404

        # Zapisz w bazie danych - UŻYWAMY engine.begin()
        with engine.begin() as conn:
            conn.execute(text('''
                    INSERT INTO foundation 
                    (name, krs, nip, regon, city, voivodeship, street, building_number, 
                     postal_code, email, phone, board_members, updated_at)
                    VALUES (:name, :krs, :nip, :regon, :city, :voiv, :street, :building, 
                            :postal, :email, :phone, :board, :updated)
                    ON CONFLICT (krs) 
                    DO UPDATE SET 
                        name = EXCLUDED.name,
                        nip = EXCLUDED.nip,
                        regon = EXCLUDED.regon,
                        city = EXCLUDED.city,
                        voivodeship = EXCLUDED.voivodeship,
                        street = EXCLUDED.street,
                        building_number = EXCLUDED.building_number,
                        postal_code = EXCLUDED.postal_code,
                        board_members = EXCLUDED.board_members,
                        updated_at = EXCLUDED.updated_at
                '''), {
                'name': foundation_data.get('name'),
                'krs': foundation_data.get('krs'),
                'nip': foundation_data.get('nip'),
                'regon': foundation_data.get('regon'),
                'city': foundation_data.get('city'),
                'voiv': foundation_data.get('voivodeship'),
                'street': foundation_data.get('street'),
                'building': foundation_data.get('building_number'),
                'postal': foundation_data.get('postal_code'),
                'email': foundation_data.get('email', ''),
                'phone': foundation_data.get('phone', ''),
                'board': foundation_data.get('board_members'),
                'updated': datetime.now()
            })

        return jsonify(foundation_data), 200

    except Exception as e:
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500


@app.route('/api/foundation', methods=['GET'])
def get_foundation():
    """Pobierz dane fundacji z bazy"""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text('SELECT * FROM foundation ORDER BY updated_at DESC LIMIT 1')
            )
            row = result.mappings().first()

        if row:
            return jsonify(dict(row)), 200
        else:
            return jsonify({}), 200

    except Exception as e:
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500


@app.route('/api/foundation', methods=['POST'])
def save_foundation():
    """Zapisz/aktualizuj dane fundacji"""
    try:
        data = request.get_json()

        with engine.begin() as conn:
            conn.execute(text('''
                    INSERT INTO foundation 
                    (name, krs, nip, regon, city, voivodeship, street, building_number,
                     postal_code, email, phone, board_members, updated_at)
                    VALUES (:name, :krs, :nip, :regon, :city, :voiv, :street, :building,
                            :postal, :email, :phone, :board, :updated)
                    ON CONFLICT (krs) 
                    DO UPDATE SET 
                        name = EXCLUDED.name,
                        nip = EXCLUDED.nip,
                        regon = EXCLUDED.regon,
                        city = EXCLUDED.city,
                        voivodeship = EXCLUDED.voivodeship,
                        street = EXCLUDED.street,
                        building_number = EXCLUDED.building_number,
                        postal_code = EXCLUDED.postal_code,
                        email = EXCLUDED.email,
                        phone = EXCLUDED.phone,
                        board_members = EXCLUDED.board_members,
                        updated_at = EXCLUDED.updated_at
                '''), {
                'name': data.get('name'),
                'krs': data.get('krs'),
                'nip': data.get('nip'),
                'regon': data.get('regon'),
                'city': data.get('city'),
                'voiv': data.get('voivodeship'),
                'street': data.get('street'),
                'building': data.get('building_number'),
                'postal': data.get('postal_code'),
                'email': data.get('email'),
                'phone': data.get('phone'),
                'board': data.get('board_members'),
                'updated': datetime.now()
            })

        return jsonify({'message': 'Dane fundacji zapisane pomyślnie'}), 200

    except Exception as e:
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500


@app.route('/api/debug/schedule_structure', methods=['GET'])
def check_schedule_structure():
    """Sprawdź strukturę schedule_slots - z konwersją typów PG"""
    conn = None
    cur = None

    try:
        conn = psycopg2.connect(
            host='localhost',
            database='suo',  # ZMIEŃ
            user='postgres',  # ZMIEŃ
            password='EDUQ'  # ZMIEŃ
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Pobierz kolumny
        cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'schedule_slots'
                ORDER BY ordinal_position
            """)
        columns = [dict(c) for c in cur.fetchall()]

        # Pobierz przykładowe dane BEZ kolumn typu range
        cur.execute("""
                SELECT 
                    id, client_id, kind, therapist_id, driver_id, 
                    vehicle_id, 
                    starts_at::text as starts_at,  -- konwersja na text
                    ends_at::text as ends_at,      -- konwersja na text
                    place_from, place_to, status,
                    CASE WHEN group_id IS NOT NULL THEN group_id ELSE NULL END as group_id
                FROM schedule_slots 
                ORDER BY id DESC
                LIMIT 5
            """)
        samples = [dict(s) for s in cur.fetchall()]

        return jsonify({
            "status": "ok",
            "columns": columns,
            "sample_data": samples
        })

    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 200

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/api/schedule/check-conflicts', methods=['POST'])
def check_schedule_conflicts():
    """Sprawdza kolizje dla edytowanego pakietu"""
    data = request.get_json()

    group_id = data.get('group_id')  # UUID pakietu (jeśli edycja)
    client_id = data.get('client_id')
    therapy = data.get('therapy')
    pickup = data.get('pickup')
    dropoff = data.get('dropoff')

    conn = None
    cur = None
    conflicts = {
        "therapy": [],
        "pickup": [],
        "dropoff": [],
        "client": [],
        "total": 0
    }

    try:
        conn = psycopg2.connect(
            host='localhost',
            port='5432',
            database='suo',  # ZMIEŃ
            user='postgres',  # ZMIEŃ
            password='EDUQ'  # ZMIEŃ
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # SPRAWDŹ KOLIZJE TERAPEUTY
        if therapy:
            therapist_id = therapy.get('therapist_id')
            starts_at = therapy.get('starts_at')
            ends_at = therapy.get('ends_at')

            cur.execute("""
                    SELECT 
                        ss.id,
                        ss.group_id::text,
                        c.full_name as client_name,
                        ss.starts_at,
                        ss.ends_at,
                        'Terapeuta już zajęty' as reason
                    FROM schedule_slots ss
                    JOIN clients c ON ss.client_id = c.id
                    WHERE ss.therapist_id = %s
                    AND ss.status NOT IN ('cancelled')
                    AND (
                        (ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz)
                    )
                    AND (
                        %s IS NULL OR ss.group_id::text != %s
                    )
                    ORDER BY ss.starts_at
                """, (therapist_id, starts_at, ends_at, group_id, group_id))

            therapy_conflicts = cur.fetchall()
            conflicts["therapy"] = [dict(row) for row in therapy_conflicts]

        # SPRAWDŹ KOLIZJE KIEROWCY (PICKUP)
        if pickup:
            driver_id = pickup.get('driver_id')
            starts_at = pickup.get('starts_at')
            ends_at = pickup.get('ends_at')

            if driver_id:
                cur.execute("""
                        SELECT 
                            ss.id,
                            ss.group_id::text,
                            c.full_name as client_name,
                            ss.starts_at,
                            ss.ends_at,
                            ss.kind,
                            'Kierowca już zajęty' as reason
                        FROM schedule_slots ss
                        JOIN clients c ON ss.client_id = c.id
                        WHERE ss.driver_id = %s
                        AND ss.kind IN ('pickup', 'dropoff')
                        AND ss.status NOT IN ('cancelled')
                        AND (
                            (ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz)
                        )
                        AND (
                            %s IS NULL OR ss.group_id::text != %s
                        )
                        ORDER BY ss.starts_at
                    """, (driver_id, starts_at, ends_at, group_id, group_id))

                pickup_conflicts = cur.fetchall()
                conflicts["pickup"] = [dict(row) for row in pickup_conflicts]

        # SPRAWDŹ KOLIZJE KIEROWCY (DROPOFF)
        if dropoff:
            driver_id = dropoff.get('driver_id')
            starts_at = dropoff.get('starts_at')
            ends_at = dropoff.get('ends_at')

            if driver_id:
                cur.execute("""
                        SELECT 
                            ss.id,
                            ss.group_id::text,
                            c.full_name as client_name,
                            ss.starts_at,
                            ss.ends_at,
                            ss.kind,
                            'Kierowca już zajęty' as reason
                        FROM schedule_slots ss
                        JOIN clients c ON ss.client_id = c.id
                        WHERE ss.driver_id = %s
                        AND ss.kind IN ('pickup', 'dropoff')
                        AND ss.status NOT IN ('cancelled')
                        AND (
                            (ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz)
                        )
                        AND (
                            %s IS NULL OR ss.group_id::text != %s
                        )
                        ORDER BY ss.starts_at
                    """, (driver_id, starts_at, ends_at, group_id, group_id))

                dropoff_conflicts = cur.fetchall()
                conflicts["dropoff"] = [dict(row) for row in dropoff_conflicts]

        # SPRAWDŹ KOLIZJE KLIENTA (czy klient nie ma już czegoś w tym czasie)
        if client_id and therapy:
            starts_at = therapy.get('starts_at')
            ends_at = therapy.get('ends_at')

            cur.execute("""
                    SELECT 
                        ss.id,
                        ss.group_id::text,
                        ss.kind,
                        ss.starts_at,
                        ss.ends_at,
                        t.full_name as therapist_name,
                        'Klient ma już inne zajęcia' as reason
                    FROM schedule_slots ss
                    LEFT JOIN therapists t ON ss.therapist_id = t.id
                    WHERE ss.client_id = %s
                    AND ss.status NOT IN ('cancelled')
                    AND (
                        (ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz)
                    )
                    AND (
                        %s IS NULL OR ss.group_id::text != %s
                    )
                    ORDER BY ss.starts_at
                """, (client_id, starts_at, ends_at, group_id, group_id))

            client_conflicts = cur.fetchall()
            conflicts["client"] = [dict(row) for row in client_conflicts]

        # POLICZ WSZYSTKIE KONFLIKTY
        conflicts["total"] = (
                len(conflicts["therapy"]) +
                len(conflicts["pickup"]) +
                len(conflicts["dropoff"]) +
                len(conflicts["client"])
        )

        return jsonify(conflicts)

    except Exception as e:
        print(f"BŁĄD w check_schedule_conflicts: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# Endpoint do aktualizacji wizyty
@app.route('/api/schedule/<int:slot_id>', methods=['PATCH', 'PUT'])
def update_schedule(slot_id):
    """Aktualizuj wizytę w grafiku"""
    data = request.get_json()

    conn = None
    cur = None

    try:
        conn = psycopg2.connect(
            host='localhost',
            port='5432',
            database='suo',
            user='postgres',
            password='EDUQ'
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Sprawdź czy slot istnieje
        cur.execute("SELECT id FROM schedule_slots WHERE id = %s", (slot_id,))
        if not cur.fetchone():
            return jsonify({'error': 'Wizyta nie znaleziona'}), 404

        # Przygotuj UPDATE query
        update_fields = []
        params = []

        # Przygotuj UPDATE query
        update_fields = []
        params = []

        if 'client_id' in data:
            update_fields.append("client_id = %s")
            params.append(data['client_id'])

        if 'starts_at' in data:
            update_fields.append("starts_at = %s")
            params.append(data['starts_at'])

        if 'ends_at' in data:
            update_fields.append("ends_at = %s")
            params.append(data['ends_at'])

        if 'place_to' in data:
            update_fields.append("place_to = %s")
            params.append(data['place_to'])

        if 'status' in data:
            update_fields.append("status = %s")
            params.append(data['status'])

        if not update_fields:
            return jsonify({'error': 'Brak danych do aktualizacji'}), 400

            # Wykonaj UPDATE
        params.append(slot_id)
        query = f"UPDATE schedule_slots SET {', '.join(update_fields)} WHERE id = %s"

        print(f"Executing UPDATE: {query}")
        print(f"Params: {params}")

        cur.execute(query, params)
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Wizyta zaktualizowana',
            'slot_id': slot_id
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"BŁĄD w update_schedule: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# DODAJ TE ENDPOINTY DO BACKENDU:




@app.route('/api/drivers/<int:driver_id>/schedule', methods=['GET'])
def get_driver_schedule(driver_id):
    """Harmonogram tras kierowcy na dany dzień - WERSJA Z GPS"""
    date = request.args.get('date')

    conn = None
    cur = None
    try:
        conn = psycopg2.connect(
            host='localhost', port='5432', database='suo',
            user='postgres', password='EDUQ'
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # KWERENDA Z GPS I DISTANCE
        cur.execute("""
                SELECT 
                    ss.id as slot_id,
                    ss.group_id::text as group_id,
                    ss.driver_id,
                    ss.client_id,
                    c.full_name as client_name,
                    ss.starts_at,
                    ss.ends_at,
                    ss.kind,
                    ss.status,
                    ss.place_from,
                    ss.place_to,
                    ss.distance_km,  -- ✅ JUŻ JEST!
                    ss.vehicle_id
                FROM schedule_slots ss
                LEFT JOIN clients c ON ss.client_id = c.id
                WHERE ss.driver_id = %s
                AND ss.kind IN ('pickup', 'dropoff')
                AND DATE(ss.starts_at) = %s
                ORDER BY ss.starts_at
            """, (driver_id, date))

        routes = [dict(row) for row in cur.fetchall()]

        # Konwertuj Decimal na float dla JSON
        for route in routes:
            if route.get('distance_km'):
                route['distance_km'] = float(route['distance_km'])

        return jsonify(routes)

    except Exception as e:
        print(f"Błąd w get_driver_schedule: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/api/test-driver-gps/<int:driver_id>')
def test_driver_gps(driver_id):
    """TEST - Sprawdź czy GPS działa"""
    date = request.args.get('date', '2025-10-10')

    conn = psycopg2.connect(
        host='localhost', port='5432', database='suo',
        user='postgres', password='EDUQ'
    )
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Najprostsza możliwa kwerenda
    cur.execute("""
            SELECT 
                id, place_from, place_to,
                from_latitude, from_longitude,
                to_latitude, to_longitude,
                distance_km
            FROM schedule_slots
            WHERE driver_id = %s
            AND DATE(starts_at) = %s
            LIMIT 1
        """, (driver_id, date))

    result = cur.fetchone()
    cur.close()
    conn.close()

    return jsonify(dict(result) if result else {"error": "Brak danych"})


# OPCJONALNIE: Endpoint do przeliczania dystansu dla istniejących tras
@app.post("/api/schedule/recalculate-distances")
def recalculate_all_distances():
    """Przelicza dystansy dla wszystkich tras bez distance_km"""
    try:
        with engine.begin() as conn:
            # Znajdź wszystkie sloty bez dystansu
            rows = conn.execute(text("""
                    SELECT id, place_from, place_to
                    FROM schedule_slots
                    WHERE kind IN ('pickup', 'dropoff')
                    AND (distance_km IS NULL OR distance_km = 0)
                    AND place_from IS NOT NULL 
                    AND place_to IS NOT NULL
                """)).mappings().all()

            updated = 0
            for row in rows:
                distance = get_route_distance(row['place_from'], row['place_to'])
                if distance:
                    conn.execute(text("""
                            UPDATE schedule_slots 
                            SET distance_km = :dist 
                            WHERE id = :id
                        """), {"dist": distance, "id": row['id']})
                    updated += 1

            return jsonify({
                "message": f"Zaktualizowano {updated} tras",
                "total_checked": len(rows)
            }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ENDPOINT 1: Sprawdź czy API Google Maps działa
@app.get("/api/debug/test-google-maps")
def test_google_maps_api():
    """Testuje połączenie z Google Maps API"""
    try:
        print("\n=== TEST GOOGLE MAPS API ===")
        print(f"Klucz API: {GOOGLE_MAPS_API_KEY[:10]}..." if GOOGLE_MAPS_API_KEY else "BRAK KLUCZA!")

        # Test prosty
        origin = "Warszawa, Polska"
        destination = "Kraków, Polska"

        result = get_route_distance(origin, destination)

        return jsonify({
            "api_key_configured": bool(GOOGLE_MAPS_API_KEY),
            "api_key_preview": GOOGLE_MAPS_API_KEY[:10] + "..." if GOOGLE_MAPS_API_KEY else None,
            "test_route": f"{origin} -> {destination}",
            "calculated_distance_km": result,
            "status": "OK" if result else "FAILED"
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ENDPOINT 2: Sprawdź co jest zapisane w bazie
@app.get("/api/debug/check-distances")
def check_existing_distances():
    """Sprawdź jakie dystanse są w bazie"""
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                    SELECT 
                        id,
                        kind,
                        place_from,
                        place_to,
                        distance_km,
                        starts_at::date as date
                    FROM schedule_slots
                    WHERE kind IN ('pickup', 'dropoff')
                    ORDER BY starts_at DESC
                    LIMIT 20
                """))

            rows = [dict(row) for row in result.mappings().all()]

            stats = conn.execute(text("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(distance_km) as with_distance,
                        COUNT(*) - COUNT(distance_km) as without_distance,
                        AVG(distance_km) as avg_distance
                    FROM schedule_slots
                    WHERE kind IN ('pickup', 'dropoff')
                """)).mappings().first()

            return jsonify({
                "statistics": dict(stats),
                "recent_routes": rows
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ENDPOINT 3: Test z logowaniem
@app.post("/api/debug/test-distance-calculation")
def test_distance_with_logging():
    """Test z pełnym logowaniem"""
    data = request.get_json()
    place_from = data.get('from')
    place_to = data.get('to')

    print("\n" + "=" * 60)
    print("TEST OBLICZANIA DYSTANSU")
    print("=" * 60)
    print(f"Od: {place_from}")
    print(f"Do: {place_to}")
    print(f"Klucz API ustawiony: {bool(GOOGLE_MAPS_API_KEY)}")

    if not GOOGLE_MAPS_API_KEY:
        print("BŁĄD: Brak klucza API!")
        return jsonify({"error": "Brak klucza GOOGLE_MAPS_API_KEY"}), 400

    try:
        # Wywołaj funkcję z logowaniem
        import requests

        origin_safe = requests.utils.quote(place_from)
        destination_safe = requests.utils.quote(place_to)
        url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin_safe}&destination={destination_safe}&key={GOOGLE_MAPS_API_KEY}"

        print(f"\nWysyłam zapytanie do Google Maps...")
        print(f"URL (bez klucza): {url.replace(GOOGLE_MAPS_API_KEY, 'HIDDEN')}")

        response = requests.get(url, timeout=10)
        print(f"Status code: {response.status_code}")

        data = response.json()
        print(f"Status odpowiedzi: {data.get('status')}")

        if data.get('status') == 'OK':
            distance_meters = data['routes'][0]['legs'][0]['distance']['value']
            distance_km = round(distance_meters / 1000, 2)
            print(f"✓ SUKCES! Dystans: {distance_km} km")

            return jsonify({
                "success": True,
                "distance_km": distance_km,
                "from": place_from,
                "to": place_to,
                "raw_response": data
            })
        else:
            print(f"✗ BŁĄD: {data.get('status')}")
            print(f"Szczegóły: {data.get('error_message', 'Brak')}")

            return jsonify({
                "success": False,
                "error": data.get('status'),
                "error_message": data.get('error_message'),
                "raw_response": data
            }), 400

    except Exception as e:
        print(f"✗ WYJĄTEK: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
    finally:
        print("=" * 60 + "\n")


# ENDPOINT 4: Przelicz konkretną trasę ręcznie
@app.post("/api/debug/force-calculate-distance/<int:slot_id>")
def force_calculate_distance(slot_id):
    """Wymusza przeliczenie dystansu dla konkretnego slotu"""
    try:
        with engine.begin() as conn:
            # Pobierz slot
            result = conn.execute(text("""
                    SELECT id, place_from, place_to, distance_km
                    FROM schedule_slots
                    WHERE id = :sid
                """), {"sid": slot_id})

            slot = result.mappings().first()
            if not slot:
                return jsonify({"error": "Slot nie istnieje"}), 404

            print(f"\n=== WYMUSZAM PRZELICZENIE DLA SLOTU {slot_id} ===")
            print(f"Od: {slot['place_from']}")
            print(f"Do: {slot['place_to']}")
            print(f"Stary dystans: {slot['distance_km']}")

            # Oblicz nowy dystans
            new_distance = get_route_distance(slot['place_from'], slot['place_to'])
            print(f"Nowy dystans: {new_distance}")

            if new_distance:
                # Zapisz w bazie
                conn.execute(text("""
                        UPDATE schedule_slots
                        SET distance_km = :dist
                        WHERE id = :sid
                    """), {"dist": new_distance, "sid": slot_id})

                return jsonify({
                    "success": True,
                    "slot_id": slot_id,
                    "old_distance": slot['distance_km'],
                    "new_distance": new_distance,
                    "from": slot['place_from'],
                    "to": slot['place_to']
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "Nie udało się obliczyć dystansu",
                    "slot_id": slot_id
                }), 400

    except Exception as e:
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.get("/api/clients/<int:client_id>/notes")
def get_client_notes(client_id):
    """Pobiera notatki dla danego klienta z opcjonalnym filtrem kategorii"""
    category = request.args.get('category')

    try:
        with engine.begin() as conn:
            # Sprawdź czy klient istnieje
            exists = conn.execute(
                text('SELECT 1 FROM clients WHERE id = :cid'),
                {"cid": client_id}
            ).scalar()

            if not exists:
                return jsonify({'error': 'Klient nie istnieje'}), 404

            # Pobierz notatki z filtrem lub bez
            if category and category != 'all':
                sql = text('''
                        SELECT id, client_id, content, category, 
                               created_by_name, created_at, updated_at
                        FROM client_notes
                        WHERE client_id = :cid AND category = :cat
                        ORDER BY created_at DESC
                    ''')
                result = conn.execute(sql, {"cid": client_id, "cat": category})
            else:
                sql = text('''
                        SELECT id, client_id, content, category, 
                               created_by_name, created_at, updated_at
                        FROM client_notes
                        WHERE client_id = :cid
                        ORDER BY created_at DESC
                    ''')
                result = conn.execute(sql, {"cid": client_id})

            notes = []
            for row in result.mappings().all():
                note = dict(row)
                # Konwertuj daty na ISO format
                if note['created_at']:
                    note['created_at'] = note['created_at'].isoformat()
                if note['updated_at']:
                    note['updated_at'] = note['updated_at'].isoformat()
                notes.append(note)

            return jsonify(notes), 200

    except Exception as e:
        print(f"Błąd w get_client_notes: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.post("/api/clients/<int:client_id>/notes")
def add_client_note(client_id):
    """Dodaje nową notatkę dla klienta"""
    data = request.get_json(silent=True) or {}

    content = (data.get('content') or '').strip()
    category = data.get('category', 'general')
    created_by_name = data.get('created_by_name', 'System')  # Możesz pobrać z sesji użytkownika

    if not content:
        return jsonify({'error': 'Treść notatki jest wymagana'}), 400

    try:
        with engine.begin() as conn:
            # Sprawdź czy klient istnieje
            exists = conn.execute(
                text('SELECT 1 FROM clients WHERE id = :cid'),
                {"cid": client_id}
            ).scalar()

            if not exists:
                return jsonify({'error': 'Klient nie istnieje'}), 404

            # Dodaj notatkę
            result = conn.execute(text('''
                    INSERT INTO client_notes (client_id, content, category, created_by_name)
                    VALUES (:cid, :content, :category, :created_by)
                    RETURNING id, client_id, content, category, created_by_name, 
                              created_at, updated_at
                '''), {
                "cid": client_id,
                "content": content,
                "category": category,
                "created_by": created_by_name
            })

            note = dict(result.mappings().first())
            note['created_at'] = note['created_at'].isoformat()
            note['updated_at'] = note['updated_at'].isoformat()

            return jsonify(note), 201

    except Exception as e:
        print(f"Błąd w add_client_note: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.put("/api/clients/<int:client_id>/notes/<int:note_id>")
def update_client_note(client_id, note_id):
    """Aktualizuje istniejącą notatkę"""
    data = request.get_json(silent=True) or {}

    content = (data.get('content') or '').strip()
    category = data.get('category')

    if not content:
        return jsonify({'error': 'Treść notatki jest wymagana'}), 400

    try:
        with engine.begin() as conn:
            # Sprawdź czy notatka należy do tego klienta
            exists = conn.execute(text('''
                    SELECT 1 FROM client_notes 
                    WHERE id = :nid AND client_id = :cid
                '''), {"nid": note_id, "cid": client_id}).scalar()

            if not exists:
                return jsonify({'error': 'Notatka nie istnieje lub nie należy do tego klienta'}), 404

            # Aktualizuj notatkę
            result = conn.execute(text('''
                    UPDATE client_notes
                    SET content = :content,
                        category = :category,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :nid AND client_id = :cid
                    RETURNING id, client_id, content, category, created_by_name,
                              created_at, updated_at
                '''), {
                "nid": note_id,
                "cid": client_id,
                "content": content,
                "category": category
            })

            note = dict(result.mappings().first())
            note['created_at'] = note['created_at'].isoformat()
            note['updated_at'] = note['updated_at'].isoformat()

            return jsonify(note), 200

    except Exception as e:
        print(f"Błąd w update_client_note: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.delete("/api/clients/<int:client_id>/notes/<int:note_id>")
def delete_client_note(client_id, note_id):
    """Usuwa notatkę"""
    try:
        with engine.begin() as conn:
            # Sprawdź czy notatka należy do tego klienta
            exists = conn.execute(text('''
                    SELECT 1 FROM client_notes 
                    WHERE id = :nid AND client_id = :cid
                '''), {"nid": note_id, "cid": client_id}).scalar()

            if not exists:
                return jsonify({'error': 'Notatka nie istnieje lub nie należy do tego klienta'}), 404

            # Usuń notatkę
            conn.execute(text('''
                    DELETE FROM client_notes
                    WHERE id = :nid AND client_id = :cid
                '''), {"nid": note_id, "cid": client_id})

            return jsonify({'message': 'Notatka usunięta pomyślnie'}), 200

    except Exception as e:
        print(f"Błąd w delete_client_note: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.get("/api/clients/<int:client_id>/sessions")
def get_client_sessions(client_id):
    """Pobiera sesje terapii dla danego klienta z opcjonalnym filtrem miesiąca"""
    month = request.args.get('month')

    try:
        with engine.begin() as conn:
            # Sprawdź czy klient istnieje
            exists = conn.execute(
                text('SELECT 1 FROM clients WHERE id = :cid'),
                {"cid": client_id}
            ).scalar()

            if not exists:
                return jsonify({'error': 'Klient nie istnieje'}), 404

            # Zapytanie z filtrem miesiąca
            if month:
                sql = text('''
                        SELECT 
                            ss.id,
                            eg.label,
                            ss.starts_at,
                            ss.ends_at,
                            ss.place_to,
                            EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes,
                            th.full_name as therapist_name,
                            cn.content as notes,
                            cn.id as note_id
                        FROM schedule_slots ss
                        LEFT JOIN event_groups eg ON eg.id = ss.group_id::uuid
                        LEFT JOIN therapists th ON th.id = ss.therapist_id
                        LEFT JOIN client_notes cn ON cn.client_id = ss.client_id 
                            AND DATE(cn.created_at) = DATE(ss.starts_at)
                            AND cn.category = 'session'
                        WHERE ss.client_id = :cid
                            AND ss.kind = 'therapy'
                            AND ss.starts_at IS NOT NULL
                            AND DATE_TRUNC('month', ss.starts_at) = DATE_TRUNC('month', TO_DATE(:month, 'YYYY-MM'))
                        ORDER BY ss.starts_at DESC
                    ''')
                result = conn.execute(sql, {"cid": client_id, "month": month + "-01"})
            else:
                sql = text('''
                        SELECT 
                            ss.id,
                            eg.label,
                            ss.starts_at,
                            ss.ends_at,
                            ss.place_to,
                            EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes,
                            th.full_name as therapist_name,
                            cn.content as notes,
                            cn.id as note_id
                        FROM schedule_slots ss
                        LEFT JOIN event_groups eg ON eg.id = ss.group_id::uuid
                        LEFT JOIN therapists th ON th.id = ss.therapist_id
                        LEFT JOIN client_notes cn ON cn.client_id = ss.client_id 
                            AND DATE(cn.created_at) = DATE(ss.starts_at)
                            AND cn.category = 'session'
                        WHERE ss.client_id = :cid
                            AND ss.kind = 'therapy'
                            AND ss.starts_at IS NOT NULL
                        ORDER BY ss.starts_at DESC
                        LIMIT 100
                    ''')
                result = conn.execute(sql, {"cid": client_id})

            sessions = []
            for row in result.mappings().all():
                session = dict(row)
                if session['starts_at']:
                    session['starts_at'] = session['starts_at'].isoformat()
                if session['ends_at']:
                    session['ends_at'] = session['ends_at'].isoformat()
                if session['duration_minutes']:
                    session['duration_minutes'] = int(session['duration_minutes'])
                sessions.append(session)

            return jsonify(sessions), 200

    except Exception as e:
        print(f"Błąd w get_client_sessions: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.get("/api/waiting-clients")
def get_waiting_clients():
    """Pobiera listę klientów oczekujących z paginacją"""
    status = request.args.get('status', 'oczekujący')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Walidacja paginacji
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 50

    try:
        with engine.begin() as conn:
            # Zapytanie z paginacją
            sql = text('''
                    SELECT 
                        id,
                        first_name,
                        last_name,
                        birth_date,
                        diagnosis,
                        registration_date,
                        notes,
                        status,
                        CURRENT_DATE - registration_date as waiting_days,
                        created_at,
                        updated_at
                    FROM waiting_clients
                    WHERE (:status = 'all' OR status = :status)
                    ORDER BY registration_date ASC
                    LIMIT :limit OFFSET :offset
                ''')

            result = conn.execute(sql, {
                "status": status,
                "limit": per_page,
                "offset": (page - 1) * per_page
            })

            clients = []
            for row in result.mappings().all():
                client = dict(row)
                # Konwertuj daty na ISO format
                for date_field in ['birth_date', 'registration_date', 'created_at', 'updated_at']:
                    if client.get(date_field):
                        client[date_field] = client[date_field].isoformat()
                clients.append(client)

            # Pobierz całkowitą liczbę rekordów
            count_sql = text('''
                    SELECT COUNT(*) FROM waiting_clients
                    WHERE (:status = 'all' OR status = :status)
                ''')
            total = conn.execute(count_sql, {"status": status}).scalar()

            return jsonify({
                'clients': clients,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'pages': (total + per_page - 1) // per_page
                }
            }), 200

    except Exception as e:
        print(f"Błąd w get_waiting_clients: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Błąd pobierania danych'}), 500


@app.post("/api/waiting-clients")
def add_waiting_client():
    """Dodaje nowego klienta do listy oczekujących"""
    data = request.get_json(silent=True) or {}

    # Walidacja wymaganych pól
    required = ['first_name', 'last_name', 'birth_date']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Pole {field} jest wymagane'}), 400

    # Walidacja długości
    validations = [
        validate_length(data.get('first_name'), 'Imię', 100),
        validate_length(data.get('last_name'), 'Nazwisko', 100),
        validate_length(data.get('diagnosis'), 'Diagnoza', 1000),
        validate_length(data.get('notes'), 'Notatki', 2000),
    ]

    for error in validations:
        if error:
            return jsonify({'error': error}), 400

    # Walidacja formatu dat
    date_error = validate_date(data.get('birth_date'), 'birth_date')
    if date_error:
        return jsonify({'error': date_error}), 400

    if data.get('registration_date'):
        date_error = validate_date(data.get('registration_date'), 'registration_date')
        if date_error:
            return jsonify({'error': date_error}), 400

    # Bezpieczne strip
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()

    if not first_name or not last_name:
        return jsonify({'error': 'Imię i nazwisko nie mogą być puste'}), 400

    try:
        with engine.begin() as conn:
            # Sprawdź duplikaty
            exists = conn.execute(text('''
                    SELECT 1 FROM waiting_clients 
                    WHERE first_name = :fname 
                    AND last_name = :lname 
                    AND birth_date = :bdate
                    AND status = 'oczekujący'
                '''), {
                "fname": first_name,
                "lname": last_name,
                "bdate": data['birth_date']
            }).scalar()

            if exists:
                return jsonify({'error': 'Klient już istnieje na liście oczekujących'}), 409

            # Dodaj nowego klienta
            sql = text('''
                    INSERT INTO waiting_clients 
                    (first_name, last_name, birth_date, diagnosis, registration_date, notes, status)
                    VALUES (:fname, :lname, :bdate, :diag, :regdate, :notes, :status)
                    RETURNING id, first_name, last_name, registration_date, status
                ''')

            result = conn.execute(sql, {
                "fname": first_name,
                "lname": last_name,
                "bdate": data['birth_date'],
                "diag": data.get('diagnosis', '').strip(),
                "regdate": data.get('registration_date', date.today().isoformat()),
                "notes": data.get('notes', '').strip(),
                "status": data.get('status', 'oczekujący')
            })

            new_client = dict(result.mappings().first())
            new_client['registration_date'] = new_client['registration_date'].isoformat()

            return jsonify({
                'success': True,
                'client': new_client,
                'message': 'Klient dodany pomyślnie'
            }), 201

    except Exception as e:
        print(f"Błąd w add_waiting_client: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Błąd podczas dodawania klienta'}), 500


@app.put("/api/waiting-clients/<int:client_id>")
def update_waiting_client(client_id):
    """Aktualizuje dane klienta oczekującego - tylko przekazane pola"""
    data = request.get_json(silent=True) or {}

    if not data:
        return jsonify({'error': 'Brak danych do aktualizacji'}), 400

    try:
        with engine.begin() as conn:
            # Sprawdź czy istnieje
            exists = conn.execute(
                text('SELECT 1 FROM waiting_clients WHERE id = :id'),
                {"id": client_id}
            ).scalar()

            if not exists:
                return jsonify({'error': 'Klient nie znaleziony'}), 404

            # Buduj dynamiczne UPDATE tylko dla przekazanych pól
            update_fields = []
            params = {"id": client_id}

            if 'first_name' in data:
                if not data['first_name'].strip():
                    return jsonify({'error': 'Imię nie może być puste'}), 400
                update_fields.append("first_name = :fname")
                params["fname"] = data['first_name'].strip()

            if 'last_name' in data:
                if not data['last_name'].strip():
                    return jsonify({'error': 'Nazwisko nie może być puste'}), 400
                update_fields.append("last_name = :lname")
                params["lname"] = data['last_name'].strip()

            if 'birth_date' in data:
                error = validate_date(data['birth_date'], 'birth_date')
                if error:
                    return jsonify({'error': error}), 400
                update_fields.append("birth_date = :bdate")
                params["bdate"] = data['birth_date']

            if 'diagnosis' in data:
                update_fields.append("diagnosis = :diag")
                params["diag"] = data['diagnosis'].strip()

            if 'registration_date' in data:
                error = validate_date(data['registration_date'], 'registration_date')
                if error:
                    return jsonify({'error': error}), 400
                update_fields.append("registration_date = :regdate")
                params["regdate"] = data['registration_date']

            if 'notes' in data:
                update_fields.append("notes = :notes")
                params["notes"] = data['notes'].strip()

            if 'status' in data:
                allowed_statuses = ['oczekujący', 'przyjęty', 'anulowany']
                if data['status'] not in allowed_statuses:
                    return jsonify({'error': f'Nieprawidłowy status. Dozwolone: {allowed_statuses}'}), 400
                update_fields.append("status = :status")
                params["status"] = data['status']

            if not update_fields:
                return jsonify({'error': 'Brak pól do aktualizacji'}), 400

            # Zawsze aktualizuj updated_at
            update_fields.append("updated_at = CURRENT_TIMESTAMP")

            sql = text(f'''
                    UPDATE waiting_clients
                    SET {', '.join(update_fields)}
                    WHERE id = :id
                    RETURNING id, first_name, last_name, status, updated_at
                ''')

            result = conn.execute(sql, params)
            updated = dict(result.mappings().first())

            if updated.get('updated_at'):
                updated['updated_at'] = updated['updated_at'].isoformat()

            return jsonify({
                'success': True,
                'client': updated,
                'message': 'Klient zaktualizowany'
            }), 200

    except Exception as e:
        print(f"Błąd w update_waiting_client: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Błąd podczas aktualizacji'}), 500


@app.delete("/api/waiting-clients/<int:client_id>")
def delete_waiting_client(client_id):
    """Soft delete - zmienia status na 'anulowany' zamiast usuwać"""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text('''
                        UPDATE waiting_clients 
                        SET status = 'anulowany', updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id AND status != 'anulowany'
                        RETURNING id
                    '''),
                {"id": client_id}
            )

            if not result.scalar():
                return jsonify({'error': 'Klient nie znaleziony lub już anulowany'}), 404

            return jsonify({
                'success': True,
                'message': 'Klient oznaczony jako anulowany'
            }), 200

    except Exception as e:
        print(f"Błąd w delete_waiting_client: {str(e)}")
        return jsonify({'error': 'Błąd podczas usuwania'}), 500


@app.post("/api/waiting-clients/<int:client_id>/accept")
def accept_waiting_client(client_id):
    """Przenosi klienta z listy oczekujących do aktywnych klientów"""
    try:
        with engine.begin() as conn:
            # Pobierz dane z waiting_clients
            waiting = conn.execute(
                text('SELECT * FROM waiting_clients WHERE id = :id AND status = :status'),
                {"id": client_id, "status": "oczekujący"}
            ).mappings().first()

            if not waiting:
                return jsonify({'error': 'Klient nie znaleziony lub już przyjęty'}), 404

            # Dodaj do clients z pełnymi danymi
            new_client = conn.execute(text('''
                    INSERT INTO clients (
                        full_name, 
                        phone, 
                        address, 
                        active,
                        birth_date,
                        diagnosis,
                        notes,
                        waiting_client_id
                    )
                    VALUES (:name, :phone, :address, true, :bdate, :diag, :notes, :wid)
                    RETURNING id, full_name
                '''), {
                "name": f"{waiting['first_name']} {waiting['last_name']}",
                "phone": '',
                "address": '',
                "bdate": waiting.get('birth_date'),
                "diag": waiting.get('diagnosis'),
                "notes": waiting.get('notes'),
                "wid": client_id
            }).mappings().first()

            # Zmień status w waiting_clients
            conn.execute(
                text('''
                        UPDATE waiting_clients 
                        SET status = :status, updated_at = CURRENT_TIMESTAMP 
                        WHERE id = :id
                    '''),
                {"status": 'przyjęty', "id": client_id}
            )

            return jsonify({
                'success': True,
                'message': 'Klient przyjęty',
                'client_id': new_client['id'],
                'full_name': new_client['full_name']
            }), 200

    except Exception as e:
        print(f"Błąd w accept_waiting_client: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Błąd podczas przyjmowania klienta'}), 500


@app.get("/api/waiting-clients/stats")
def get_waiting_stats():
    """Pobiera statystyki listy oczekujących"""
    try:
        with engine.begin() as conn:
            stats = conn.execute(text('''
                    SELECT 
                        COUNT(*) FILTER (WHERE status = 'oczekujący') as oczekujacy,
                        COUNT(*) FILTER (WHERE status = 'przyjęty') as przyjeci,
                        COUNT(*) FILTER (WHERE status = 'anulowany') as anulowani,
                        ROUND(AVG(CURRENT_DATE - registration_date) FILTER (WHERE status = 'oczekujący')) as sredni_czas_dni,
                        MAX(CURRENT_DATE - registration_date) FILTER (WHERE status = 'oczekujący') as max_czas_dni
                    FROM waiting_clients
                ''')).mappings().first()

            return jsonify(dict(stats)), 200

    except Exception as e:
        print(f"Błąd w get_waiting_stats: {str(e)}")
        return jsonify({'error': 'Błąd pobierania statystyk'}), 500

    # === DZIENNIK ENDPOINTS ===

#@app.get("/api/journal")
#def get_journal_entries():
#        """Pobiera wszystkie wpisy z dziennika z pełnymi nazwami"""

        # Opcjonalny filtr na klienta
#        client_id = request.args.get('client_id', type=int)

#        with session_scope() as db_session:
#            query = db_session.query(JournalEntry).options(
#                joinedload(JournalEntry.client),
#                joinedload(JournalEntry.therapist)
#            )

 #           if client_id:
 #               query = query.filter(JournalEntry.client_id == client_id)

  #          entries = query.order_by(JournalEntry.data.desc(), JournalEntry.id.desc()).all()

  #          results = []
  #          for e in entries:
                # Upewnij się, że używasz bezpiecznego dostępu do relacji
  #              client_name = e.client.full_name if e.client else 'Nieznany Klient'
  #              therapist_name = e.therapist.full_name if e.therapist else 'Nieznany Terapeuta'

  #              results.append({
  #                  "id": e.id,
  #                  "data": e.data.isoformat(),
  #                  "client_id": e.client_id,
  #                  "klient": client_name,
  #                  "therapist_id": e.therapist_id,
  #                  "terapeuta": therapist_name,
  #                  "temat": e.temat,
  #                  "cele": e.cele,
  #                  "created_at": e.created_at.isoformat() if e.created_at else None
  #              })

   #         return jsonify(results), 200


@app.route('/api/journal', methods=['GET'])
def get_journal_entries():
    """
    Pobiera wpisy dziennika, filtrując po client_id i/lub miesiącu (RRRR-MM).
    Używa SQLAlchemy ORM.
    """
    try:
        # 1. Pobranie parametrów z żądania
        client_id = request.args.get('client_id')
        month_str = request.args.get('month') # Format "YYYY-MM"

        with session_scope() as db_session:
            # 2. Budowanie bazowego zapytania ORM
            query = db_session.query(JournalEntry).options(
                joinedload(JournalEntry.client),
                joinedload(JournalEntry.therapist)
            )

            # 3. Dodawanie filtra po kliencie (jeśli istnieje)
            if client_id:
                try:
                    query = query.filter(JournalEntry.client_id == int(client_id))
                except (ValueError, TypeError):
                    pass # Ignoruj niepoprawne ID

            # 4. DODANO: Logika filtrowania po miesiącu
            if month_str:
                try:
                    year, month = map(int, month_str.split('-'))
                    # Używamy funkcji 'extract' z SQLAlchemy do filtrowania po części daty
                    query = query.filter(extract('year', JournalEntry.data) == year)
                    query = query.filter(extract('month', JournalEntry.data) == month)
                except (ValueError, TypeError):
                    pass # Ignoruj niepoprawny format miesiąca

            # 5. Sortowanie i wykonanie zapytania
            entries = query.order_by(JournalEntry.data.desc(), JournalEntry.id.desc()).all()

            # 6. Formatowanie wyników (tak jak miałeś wcześniej)
            results = []
            for e in entries:
                client_name = e.client.full_name if e.client else 'Nieznany Klient'
                therapist_name = e.therapist.full_name if e.therapist else 'Nieznany Terapeuta'
                results.append({
                    "id": e.id,
                    "data": e.data.isoformat(),
                    "client_id": e.client_id,
                    "klient": client_name,
                    "therapist_id": e.therapist_id,
                    "terapeuta": therapist_name,
                    "temat": e.temat,
                    "cele": e.cele,
                })
                
            return jsonify(results), 200

    except Exception as e:
        # Lepsze logowanie błędów
        print(f"Wystąpił nieoczekiwany błąd w get_journal_entries: {e}")
        return jsonify({"error": "Wystąpił wewnętrzny błąd serwera."}), 500


@app.post("/api/journal")
def create_journal_entry():
    """Tworzy nowy wpis w dzienniku"""
    data = request.get_json(silent=True) or {}

    try:
        # Walidacja wymaganych pól
        required = ['data', 'client_id', 'therapist_id']
        if not all(k in data for k in required):
            return jsonify({"error": "Pola 'data', 'client_id' i 'therapist_id' są wymagane."}), 400

        # === POCZĄTEK POPRAWKI: Elastyczne parsowanie daty ===
        date_str = data.get("data")
        entry_date = None

        if not date_str:
            return jsonify({"error": "Brak pola 'data'."}), 400

        try:
            # 1. Spróbuj formatu ISO (YYYY-MM-DD), np. z ręcznego wpisu
            entry_date = datetime.fromisoformat(date_str).date()
        except ValueError:
            # 2. Spróbuj formatu polskiego (DD.MM.YYYY), np. z CSV
            try:
                entry_date = datetime.strptime(date_str, '%d.%m.%Y').date()
            except ValueError:
                # 3. Jeśli oba formaty zawiodą, zwróć błąd
                return jsonify({"error": f"Nieprawidłowy format daty: '{date_str}'. Oczekiwano YYYY-MM-DD lub DD.MM.YYYY."}), 400
        
        if not entry_date:
            return jsonify({"error": "Nie udało się przetworzyć daty."}), 400
        # === KONIEC POPRAWKI ===

        client_id = int(data["client_id"])
        therapist_id = int(data["therapist_id"])

    except (ValueError, TypeError) as e:
        # Ten błąd wyłapie teraz głównie błędy konwersji ID (np. int(None))
        return jsonify({"error": f"Nieprawidłowy format danych (np. ID klienta/terapeuty): {str(e)}"}), 400

    with session_scope() as db_session:
        try:
            new_entry = JournalEntry(
                data=entry_date,
                client_id=client_id,
                therapist_id=therapist_id,
                temat=data.get("temat"),
                cele=data.get("cele")
            )
            db_session.add(new_entry)
            db_session.flush() # Upewnij się, że dostaniemy ID

            return jsonify({
                "id": new_entry.id,
                "data": new_entry.data.isoformat(),
                "message": "Wpis do dziennika utworzony."
            }), 201
        
        except IntegrityError as e:
            # Obsługa błędu, jeśli ID klienta lub terapeuty nie istnieje
            db_session.rollback()
            print(f"Błąd IntegrityError w create_journal_entry: {e}")
            return jsonify({"error": "Błąd integralności bazy danych. Sprawdź, czy ID klienta i terapeuty są poprawne.", "details": str(e.orig)}), 409
        
        except Exception as e:
            # Ogólna obsługa błędów zapisu
            db_session.rollback()
            print(f"Błąd Exception w create_journal_entry: {e}")
            return jsonify({"error": f"Wewnętrzny błąd serwera podczas zapisu: {str(e)}"}), 500

@app.get("/api/journal/<int:entry_id>")
def get_journal_entry(entry_id):
        """Pobiera pojedynczy wpis z dziennika"""
        with session_scope() as db_session:
            entry = db_session.query(JournalEntry).options(
                joinedload(JournalEntry.client),
                joinedload(JournalEntry.therapist)
            ).filter(JournalEntry.id == entry_id).first()

            if not entry:
                return jsonify({"error": "Wpis nie znaleziony"}), 404

            return jsonify({
                "id": entry.id,
                "data": entry.data.isoformat(),
                "client_id": entry.client_id,
                "klient": entry.client.full_name if entry.client else 'Nieznany Klient',
                "therapist_id": entry.therapist_id,
                "terapeuta": entry.therapist.full_name if entry.therapist else 'Nieznany Terapeuta',
                "temat": entry.temat,
                "cele": entry.cele,
                "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
            }), 200


@app.put("/api/journal/<int:entry_id>")
@app.patch("/api/journal/<int:entry_id>")
def update_journal_entry(entry_id):
    """Aktualizuje wpis w dzienniku"""
    data = request.get_json(silent=True) or {}

    with session_scope() as db_session:
        entry = db_session.query(JournalEntry).filter(JournalEntry.id == entry_id).first()

        if not entry:
            return jsonify({"error": "Wpis nie znaleziony"}), 404

        # Aktualizacja pól tylko jeśli są przekazane
        if "data" in data:
            try:
                entry.data = datetime.fromisoformat(data["data"]).date()
            except (ValueError, TypeError):
                return jsonify({"error": "Nieprawidłowy format daty."}), 400

        if "client_id" in data: entry.client_id = int(data["client_id"])
        if "therapist_id" in data: entry.therapist_id = int(data["therapist_id"])
        if "temat" in data: entry.temat = data["temat"]
        if "cele" in data: entry.cele = data["cele"]

        db_session.commit()

        return jsonify({"id": entry.id, "message": "Wpis zaktualizowany."}), 200

@app.delete("/api/journal/<int:entry_id>")
def delete_journal_entry(entry_id):
        """Usuwa wpis z dziennika"""
        with session_scope() as db_session:
            entry = db_session.query(JournalEntry).filter(JournalEntry.id == entry_id).first()

            if not entry:
                return jsonify({"error": "Wpis nie znaleziony"}), 404

            db_session.delete(entry)
            db_session.commit()

            return "", 204  # 204 No Content - standardowa odpowiedź na DELETE


@app.get("/api/clients/<int:client_id>/all-sessions")
def get_client_all_sessions(client_id: int):
    """
    Zwraca ujednoliconą historię spotkań klienta, łącząc:
    1. Spotkania indywidualne (schedule_slots z kind='therapy')
    2. Wpisy z Dziennika (dziennik)
    3. Sesje TUS (jeśli są powiązane)
    """
    try:
        with engine.begin() as conn:
            # 1. Spotkania indywidualne (schedule_slots)
            individual_sql = text('''
                SELECT 
                    ss.id as source_id,
                    'individual' as source_type,
                    ss.starts_at,
                    ss.ends_at,
                    ss.status,
                    th.full_name as therapist_name,
                    eg.label as topic_or_temat,
                    ss.place_to as place,
                    EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes,
                    cn.content as notes,
                    cn.id as note_id
                FROM schedule_slots ss
                LEFT JOIN therapists th ON th.id = ss.therapist_id
                LEFT JOIN event_groups eg ON eg.id = ss.group_id
                LEFT JOIN client_notes cn ON cn.client_id = ss.client_id 
                    AND DATE(cn.created_at) = DATE(ss.starts_at)
                    AND cn.category = 'session'
                WHERE ss.client_id = :cid
                    AND ss.kind = 'therapy'

                UNION ALL

                -- 2. Wpisy z Dziennika (dziennik)
                SELECT 
                    d.id as source_id,
                    'journal' as source_type,
                    d.data::timestamp with time zone AS starts_at, -- Używamy daty jako startu
                    (d.data + interval '60 minutes')::timestamp with time zone AS ends_at,
                    'done' as status,
                    th.full_name as therapist_name,
                    d.temat as topic_or_temat,
                    'Dziennik' as place,
                    60 as duration_minutes,
                    d.cele as notes, -- Notatki zapisane są w kolumnie 'cele'
                    NULL as note_id -- Dziennik nie używa tabeli client_notes
                FROM dziennik d
                JOIN therapists th ON th.id = d.therapist_id
                WHERE d.client_id = :cid

                ORDER BY starts_at DESC
            ''')

            # UWAGA: Sesje TUS pominąłem, aby nie komplikować Unii,
            # ale powinny być ładowane oddzielnie lub dodane do Unii.

            rows = conn.execute(individual_sql, {"cid": client_id}).mappings().all()

            history = []
            for row in rows:
                row_dict = dict(row)
                if row_dict['starts_at']:
                    row_dict['starts_at'] = row_dict['starts_at'].isoformat()
                if row_dict['ends_at']:
                    row_dict['ends_at'] = row_dict['ends_at'].isoformat()
                if row_dict['duration_minutes']:
                    row_dict['duration_minutes'] = int(row_dict['duration_minutes'])

                history.append(row_dict)

            return jsonify(history), 200

    except Exception as e:
        print(f"❌ BŁĄD w get_client_all_sessions: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/schedule/<int:slot_id>', methods=['GET'])
def get_schedule_slot(slot_id):
    """Pobiera pojedynczą wizytę z harmonogramu"""
    print(f"=== GET SCHEDULE SLOT {slot_id} ===")

    try:
        with engine.begin() as conn:
            # Pobierz slot z wszystkimi danymi
            slot = conn.execute(text("""
                SELECT 
                    ss.id, ss.group_id, ss.client_id, ss.therapist_id, 
                    ss.driver_id, ss.kind, ss.starts_at, ss.ends_at,
                    ss.place_to, ss.status, ss.distance_km,
                    c.full_name as client_name,
                    t.full_name as therapist_name,
                    d.full_name as driver_name,
                    eg.label as group_label
                FROM schedule_slots ss
                LEFT JOIN clients c ON c.id = ss.client_id
                LEFT JOIN therapists t ON t.id = ss.therapist_id
                LEFT JOIN drivers d ON d.id = ss.driver_id
                LEFT JOIN event_groups eg ON eg.id = ss.group_id::uuid
                WHERE ss.id = :id
            """), {"id": slot_id}).mappings().first()

            if not slot:
                return jsonify({"error": "Wizyta nie znaleziona"}), 404

            # Konwertuj daty na stringi
            slot_dict = dict(slot)
            if slot_dict['starts_at']:
                slot_dict['starts_at'] = slot_dict['starts_at'].isoformat()
            if slot_dict['ends_at']:
                slot_dict['ends_at'] = slot_dict['ends_at'].isoformat()

            print(f"✅ Znaleziono wizytę ID: {slot_id}")
            return jsonify(slot_dict), 200

    except Exception as e:
        print(f"❌ Błąd pobierania wizyty: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Błąd pobierania wizyty: {str(e)}"}), 500


# Funkcja do znalezienia wszystkich duplikatów endpointów
def debug_endpoints():
    print("\n=== DEBUG: WSZYSTKIE ENDPOINTY ===")
    endpoints = {}
    
    for rule in app.url_map.iter_rules():
        key = f"{rule.rule}::{','.join(rule.methods)}"
        if key in endpoints:
            print(f"🚨 DUPLIKAT: {key}")
            print(f"   Istniejący: {endpoints[key]}")
            print(f"   Nowy: {rule.endpoint}")
        else:
            endpoints[key] = rule.endpoint
    
    print(f"✓ Łącznie endpointów: {len(endpoints)}")
    return endpoints

@app.route('/api/debug/users')
def debug_users():
    """Debug - pokaż wszystkich użytkowników"""
    try:
        with session_scope() as db_session:
            users = db_session.query(User).all()
            result = []
            for user in users:
                result.append({
                    'id': user.id,
                    'username': user.username,
                    'is_admin': user.is_admin,
                    'password_hash_length': len(user.password_hash) if user.password_hash else 0,
                    'password_hash_preview': user.password_hash[:30] + '...' if user.password_hash else 'EMPTY'
                })
            return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)})

# Wywołaj diagnostykę
debug_endpoints()

# === INICJALIZACJA DOMYŚLNEGO UŻYTKOWNIKA ===
print("\n" + "="*60)
print("INICJALIZACJA DOMYŚLNEGO UŻYTKOWNIKA")
print("="*60)
create_default_user()
print("="*60 + "\n")

# === Uruchomienie aplikacji ===

# Inicjalizacja tabel MUSI być poza blokiem main
# Gunicorn uruchomi ten kod podczas importowania 'app'
if not init_all_tables():
    print("KRYTYCZNY BŁĄD: Nie udało się zainicjalizować tabel. Aplikacja zatrzymana.")
    # W normalnej sytuacji można by tu zatrzymać aplikację, 
    # ale na razie tylko logujemy błąd.
    # sys.exit(1) # Możesz to odkomentować, jeśli chcesz


    # Wywołaj przy starcie aplikacji
if __name__ == '__main__':
    init_documents_table()  # Dodaj tę linię
    app.run(debug=True, host='0.0.0.0', port=5000)
        # app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False))

