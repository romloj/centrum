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

print("--- SERWER ZALADOWAL NAJNOWSZA WERSJE PLIKU ---")

# === KONFIGURACJA APLIKACJI ===
TZ = ZoneInfo("Europe/Warsaw")
# Główna instancja aplikacji
app = Flask(__name__, static_folder="static", static_url_path="", template_folder='templates') # Określamy folder szablonów
CORS(app, supports_credentials=True) # supports_credentials=True jest ważne dla sesji
app.config['DEBUG'] = True

# Wczytywanie konfiguracji ze zmiennych środowiskowych
DATABASE_URL = os.getenv("DATABASE_URL")
GOOGLE_MAPS_API_KEY = os.getenv("AIzaSyC5TGcemvDn-BZ5khdlQOOpPZVV2qLMYc8")
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

auth_bp = Blueprint('auth', __name__, template_folder='static')

CENTRUM = os.environ.get('admin')

if not CENTRUM:
    print("="*50)
    print("BŁĄD: Nie ustawiono zmiennej środowiskowej 'ADMIN_PASSWORD'!")
    print("Moduł logowania nie będzie działać poprawnie.")
    print("="*50)

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            # Jeśli żądanie jest do API, zwróć błąd 401
            if request.path.startswith('/api/'):
                 return jsonify(message="Authentication required"), 401
            # W przeciwnym razie przekieruj do strony logowania
            return redirect(url_for('auth.login_page'))
        return view(**kwargs)
    return wrapped_view

@auth_bp.route('/login', methods=['GET'])
def login_page():
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('main_index')) # Przekieruj na główną stronę aplikacji
    return render_template('login.html', error=None)

@auth_bp.route('/api/login', methods=['POST'])
def handle_login():
    data = request.get_json()
    error = None

    if not data or 'password' not in data:
        return jsonify({'error': 'Brak hasła w zapytaniu'}), 400

    wpisane_haslo = data.get('password')
    username = data.get('username') # Można dodać walidację

    if wpisane_haslo == CENTRUM:
        session['logged_in'] = True
        session['username'] = username # Opcjonalnie
        # Zwróć URL do przekierowania po stronie klienta
        return jsonify({'redirect_url': url_for('main_index')})
    else:
        return jsonify({'error': 'Niepoprawne hasło lub nazwa użytkownika.'}), 401

@auth_bp.route('/logout')
@login_required # Tylko zalogowany może się wylogować
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('auth.login_page'))

# === REJESTRACJA BLUEPRINTU ===
app.register_blueprint(auth_bp)


# === GŁÓWNA STRONA APLIKACJI (po zalogowaniu) ===
@app.route('/')
@login_required # Ta strona wymaga zalogowania
def main_index():
    # Renderuje główny interfejs aplikacji
    return render_template('index.html')


# === DEFINICJE MODELI SQLAlchemy ===
# (Tutaj wklej wszystkie klasy modeli: TUSSessionAttendance, Client, Therapist, itd. z pierwszego kodu)

class TUSSessionAttendance(Base):
    __tablename__ = 'tus_session_attendance'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('tus_sessions.id', ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default='obecny')  # np. obecny, nieobecny, spóźniony, usprawiedliwiony
    is_present = Column(Boolean, default=True) # Nowe pole do oznaczania obecności

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
    photo_url = Column(String) # Dodane pole na URL zdjęcia
    birth_date = Column(Date) # Dodane pole
    diagnosis = Column(TEXT) # Dodane pole
    notes = Column(TEXT) # Dodane pole
    waiting_client_id = Column(Integer, ForeignKey('waiting_clients.id', ondelete="SET NULL"), nullable=True) # Dodane powiązanie

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
        foreign_keys="[TUSGroup.therapist_id]",
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
    vehicle_id = Column(Integer) # Dodane pole
    place_from = Column(String) # Dodane pole
    place_to = Column(String) # Dodane pole
    group_tus_id = Column(Integer, ForeignKey('tus_groups.id', ondelete="SET NULL")) # ID grupy TUS

    attendance = relationship("IndividualSessionAttendance", uselist=False, cascade="all, delete-orphan")


class TUSGroupMember(Base):
    __tablename__ = "tus_group_members"
    group_id = Column(Integer, ForeignKey("tus_groups.id", ondelete="CASCADE"), primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    is_active = Column(Boolean, default=True, nullable=False)

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

    therapist = relationship("Therapist", back_populates="tus_groups", lazy="selectin", foreign_keys=[therapist_id])
    sessions = relationship("TUSSession", back_populates="group", cascade="all, delete-orphan", lazy="selectin")
    assistant_therapist = relationship("Therapist", lazy="selectin", foreign_keys=[assistant_therapist_id])
    member_associations = relationship("TUSGroupMember", back_populates="group", cascade="all, delete-orphan")
    members = association_proxy(
        'member_associations',
        'client',
        creator=_create_member_association
    )

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
    points = Column(Integer, default=0) # Dodano pole points
    __table_args__ = (UniqueConstraint('session_id', 'client_id'),)


class TUSGroupTarget(Base):
    __tablename__ = 'tus_group_targets'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('tus_groups.id', ondelete="CASCADE"), nullable=False)
    school_year_start = Column(Integer, nullable=False)
    semester = Column(Integer, nullable=False)
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
    status = Column(String(50), default='planowany')
    budget = Column(Float)
    coordinator = Column(String(255))
    partners = Column(String)
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

    client = relationship("Client", foreign_keys=[client_id], lazy="joined")
    therapist = relationship("Therapist", foreign_keys=[therapist_id], lazy="joined")

class ClientNote(Base):
    __tablename__ = 'client_notes'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    content = Column(TEXT, nullable=False)
    category = Column(String(50), nullable=False, default='general')
    created_by_name = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())

class ClientDocument(Base):
    __tablename__ = 'client_documents'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id', ondelete="CASCADE"), nullable=False)
    file_name = Column(TEXT, nullable=False)
    file_path = Column(TEXT, nullable=False)
    file_type = Column(TEXT, nullable=False)
    file_size = Column(Integer, nullable=False)
    document_type = Column(TEXT)
    notes = Column(TEXT)
    upload_date = Column(TIMESTAMP(timezone=True), default=func.now())
    uploaded_by = Column(TEXT)

class Foundation(Base):
    __tablename__ = 'foundation'
    id = Column(Integer, primary_key=True)
    name = Column(TEXT)
    krs = Column(TEXT, unique=True)
    nip = Column(TEXT)
    regon = Column(TEXT)
    city = Column(TEXT)
    voivodeship = Column(TEXT)
    street = Column(TEXT)
    building_number = Column(TEXT)
    postal_code = Column(TEXT)
    email = Column(TEXT)
    phone = Column(TEXT)
    board_members = Column(TEXT)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())

class WaitingClient(Base):
     __tablename__ = 'waiting_clients'
     id = Column(Integer, primary_key=True)
     first_name = Column(String(100), nullable=False)
     last_name = Column(String(100), nullable=False)
     birth_date = Column(Date, nullable=False)
     diagnosis = Column(TEXT)
     registration_date = Column(Date, nullable=False, default=func.current_date())
     notes = Column(TEXT)
     status = Column(String(50), default='oczekujący') # np. oczekujący, przyjęty, anulowany
     created_at = Column(TIMESTAMP(timezone=True), default=func.now())
     updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())

# === WCZYTANIE MODELI AI ===
# (Reszta kodu modeli AI bez zmian)
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
    session_db = SessionLocal() # Używamy poprawnej nazwy zmiennej
    try:
        yield session_db
        session_db.commit()
    except Exception:
        session_db.rollback()
        raise
    finally:
        session_db.close()

# === Reszta funkcji pomocniczych (_time_bucket, _score, get_route_distance itd.) ===
# (Tutaj wklej resztę funkcji pomocniczych z pierwszego kodu)
def validate_date(date_string, field_name):
    """Waliduje format daty"""
    if not date_string: return None # Puste jest OK
    try:
        # Spróbuj sparsować jako ISO (YYYY-MM-DD...)
        datetime.fromisoformat(str(date_string).split('T')[0])
        return None
    except (ValueError, TypeError):
        try:
             # Spróbuj sparsować jako DD.MM.YYYY
             datetime.strptime(str(date_string), '%d.%m.%Y')
             return None
        except (ValueError, TypeError):
            return f'Nieprawidłowy format daty w polu {field_name}. Użyj YYYY-MM-DD lub DD.MM.YYYY.'


def validate_length(value, field_name, max_length):
    """Waliduje długość tekstu"""
    if value and len(str(value)) > max_length: # Konwertuj na string przed sprawdzeniem długości
        return f'{field_name} zbyt długie (max {max_length} znaków)'
    return None


def calculate_distance(lat1, lon1, lat2, lon2):
    if lat1 and lon1 and lat2 and lon2:
        return geodesic((lat1, lon1), (lat2, lon2)).kilometers
    return 0


def get_db_connection(): # Funkcja potencjalnie niepotrzebna przy użyciu SQLAlchemy
    """Tworzy połączenie z bazą PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='prefer') # Użyj sslmode='prefer' dla Render
        conn.cursor_factory = RealDictCursor
        return conn
    except Exception as e:
        print(f"Błąd połączenia z bazą (psycopg2): {e}")
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
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                category VARCHAR(50) NOT NULL DEFAULT 'general',
                created_by_name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_client_notes_client_id ON client_notes(client_id)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_client_notes_category ON client_notes(category)'))
    print("✓ Tabela client_notes zainicjalizowana")


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
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_waiting_clients_status ON waiting_clients(status)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_waiting_clients_registration ON waiting_clients(registration_date)'))
    print("✓ Tabela waiting_clients zainicjalizowana")

def init_documents_table():
    """Inicjalizacja tabeli dokumentów w PostgreSQL"""
    with engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS client_documents (
                id SERIAL PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                document_type TEXT,
                notes TEXT,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by TEXT
            )
        '''))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_client_documents_client_id ON client_documents(client_id)'))
    print("✓ Tabela client_documents zainicjalizowana")

def init_foundation_table():
    with engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS foundation (
                id SERIAL PRIMARY KEY, name TEXT, krs TEXT UNIQUE, nip TEXT, regon TEXT,
                city TEXT, voivodeship TEXT, street TEXT, building_number TEXT, postal_code TEXT,
                email TEXT, phone TEXT, board_members TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_foundation_krs ON foundation(krs)'))
    print("✓ Tabela foundation zainicjalizowana")

def init_projects_table():
    with engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY, title VARCHAR(255) NOT NULL, description TEXT, start_date DATE, end_date DATE,
                status VARCHAR(50) DEFAULT 'planowany', budget FLOAT, coordinator VARCHAR(255), partners TEXT,
                beneficiaries_count INTEGER, photo_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_projects_dates ON projects(start_date, end_date)'))
    print("✓ Tabela projects zainicjalizowana")

# Dodaj inicjalizację tabeli absences
def init_absences_table():
    with engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS absences (
                id SERIAL PRIMARY KEY,
                person_type VARCHAR(20) NOT NULL, -- 'therapist' lub 'driver'
                person_id INTEGER NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status VARCHAR(50), -- np. 'Urlop', 'Zwolnienie', 'Szkolenie'
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        '''))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_absences_person ON absences(person_type, person_id);'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_absences_dates ON absences(start_date, end_date);'))
    print("✓ Tabela absences zainicjalizowana")


def init_all_tables():
    """Inicjalizacja wszystkich tabel aplikacji"""
    print("\n" + "=" * 60)
    print("INICJALIZACJA TABEL BAZY DANYCH")
    print("=" * 60)
    try:
        with engine.begin() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✓ Połączono z PostgreSQL {version[:15]}...")

        # Inicjalizuj wszystkie tabele
        Base.metadata.create_all(bind=engine) # Automatyczne tworzenie tabel z modeli SQLAlchemy

        # Wywołaj dodatkowe inicjalizacje (jeśli potrzebne, np. dla indeksów)
        init_journal_table()
        init_client_notes_table()
        init_waiting_clients_table()
        init_documents_table()
        init_foundation_table()
        init_projects_table()
        init_absences_table() # Dodano inicjalizację absences


        print("=" * 60)
        print("✓ WSZYSTKIE TABELE GOTOWE (SQLAlchemy + dodatkowe)")
        print("=" * 60 + "\n")
        return True
    except Exception as e:
        print("\n" + "=" * 60 + "\n✗ BŁĄD INICJALIZACJI BAZY DANYCH\n" + "=" * 60)
        print(f"Błąd: {str(e)}")
        print(traceback.format_exc())
        print("=" * 60 + "\n")
        return False


def find_best_match(name_to_find, name_list):
    if not name_to_find or not name_list: return None
    name_to_find_clean = re.sub(r'[\.\s]+', ' ', name_to_find.strip())
    name_to_find_lower = name_to_find_clean.lower()
    if not name_to_find_lower: return None
    parts_to_find = name_to_find_lower.split()
    best_match = None
    highest_score = 0

    for full_name in name_list:
        current_score = 0
        full_name_clean = re.sub(r'[\.\s]+', ' ', full_name.strip())
        full_name_lower = full_name_clean.lower()
        parts_full = full_name_lower.split()

        # Debug:
        # print(f"Porównuję: '{name_to_find_lower}' z '{full_name_lower}'")

        if full_name_lower == name_to_find_lower: current_score = 100
        elif len(parts_to_find) == 2 and len(parts_full) >= 2:
            first_name_find = parts_to_find[0]
            last_initial_find = parts_to_find[1]
            if (parts_full[0] == first_name_find and len(last_initial_find) == 1 and parts_full[1][0] == last_initial_find[0]):
                current_score = 95
        elif len(parts_to_find) == 1 and len(parts_full) >= 1:
            if parts_full[0] == parts_to_find[0]: current_score = 70
        elif name_to_find_lower in full_name_lower: current_score = 50
        elif parts_to_find and parts_full and parts_to_find[0] == parts_full[0]: current_score = 60
        else:
            matching_words = 0
            for word in parts_to_find:
                if any(part.startswith(word) for part in parts_full if len(word) > 1):
                    matching_words += 1
            if matching_words == len(parts_to_find): current_score = 80
            elif matching_words > 0: current_score = 40 + (matching_words * 10)

        if current_score > highest_score:
            highest_score = current_score
            best_match = full_name

    # print(f"NAJLEPSZE DOPASOWANIE: {best_match} (wynik: {highest_score})")
    return best_match if highest_score >= 40 else None


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

def get_semester_dates(school_year_start, semester):
    if semester == 1:
        start_date = date(school_year_start, 9, 1)
        end_date = date(school_year_start + 1, 2, 1) # Kończy się przed 1 lutego
    elif semester == 2:
        start_date = date(school_year_start + 1, 2, 1)
        end_date = date(school_year_start + 1, 7, 1) # Kończy się przed 1 lipca
    else:
        raise ValueError("Semester must be 1 or 2")
    return start_date, end_date

def get_route_distance(origin, destination):
    """Oblicza dystans między dwoma punktami za pomocą Google Maps API."""
    print(f"\n{'=' * 60}\nFUNKCJA get_route_distance(): {origin} -> {destination}")
    api_key = GOOGLE_MAPS_API_KEY
    if not api_key:
        print("⚠️ OSTRZEŻENIE: Brak klucza GOOGLE_MAPS_API_KEY.")
        return None
    if not origin or not destination:
        print("⚠️ OSTRZEŻENIE: Brak origin lub destination")
        return None

    origin_safe = requests.utils.quote(origin)
    destination_safe = requests.utils.quote(destination)
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin_safe}&destination={destination_safe}&key={api_key}"
    print(f"📡 URL (bez klucza): ...{url[-50:]}")

    try:
        response = requests.get(url, timeout=10)
        print(f"📥 Status code: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        print(f"📊 Status API: {data.get('status')}")

        if data.get('status') == 'OK' and data.get('routes'):
            # Znajdź najkrótszą trasę (czasami API zwraca alternatywy)
            best_route = min(data['routes'], key=lambda r: r['legs'][0]['distance']['value'])
            distance_meters = best_route['legs'][0]['distance']['value']
            distance_km = round(distance_meters / 1000, 2)
            print(f"✅ SUKCES! Dystans: {distance_km} km")
            return distance_km
        else:
            print(f"❌ Błąd API: {data.get('status')} - {data.get('error_message', 'Brak')}")
            print(f"Pełna odpowiedź: {data}")
            return None
    except requests.exceptions.Timeout:
        print(f"⏱️ TIMEOUT")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Błąd połączenia z Google Maps API: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"❌ Błąd parsowania odpowiedzi: {e}")
        print(f"Struktura danych: {data if 'data' in locals() else 'Brak odpowiedzi'}")
        return None
    except Exception as e:
        print(f"❌ Nieoczekiwany błąd: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        return None
    finally:
         print(f"{'=' * 60}\n")


def _time_bucket(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    m = 0 if m < 30 else 30
    return f"{h:02d}:{m:02d}"


def _date_str(dt):
    return dt.strftime("%Y-%m-%d")


def _score(freq, maxfreq, recency_days):
    if maxfreq <= 0: base = 0.0
    else: base = (freq + 1.0) / (maxfreq + 2.0)
    rec_bonus = 0.3 * exp(-recency_days / 30.0) if recency_days is not None else 0.0
    return min(1.0, base + rec_bonus)


def _parse_time(s: str):
    h, m = map(int, s.split(":"))
    return h, m


def _to_tstz(date_yyyy_mm_dd: str, hhmm: str, tz=TZ):
    h, m = _parse_time(hhmm)
    d = datetime.fromisoformat(date_yyyy_mm_dd)
    return d.replace(hour=h, minute=m, second=0, microsecond=0, tzinfo=tz)


def _softmax(x):
    m = max(x) if x else 0.0
    exps = [math.exp(v - m) for v in x]
    s = sum(exps) or 1.0
    return [v / s for v in exps]


def _score_cd_row(r):
    n = r.get("n_runs", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5 * rec + 0.3 * done + 0.2 * min(1.0, n / 10.0) + 0.1 * min(1.0, mins / 600.0)

def _score_ct_row(r):
    n = r.get("n_sessions", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5 * rec + 0.3 * done + 0.2 * min(1.0, n / 10.0) + 0.1 * min(1.0, mins / 600.0)


def find_overlaps(conn, *, driver_id=None, therapist_id=None, starts_at=None, ends_at=None, exclude_slot_id=None):
    if starts_at is None or ends_at is None: return []

    # Zapewnij, że daty mają strefę czasową
    if starts_at.tzinfo is None: starts_at = starts_at.replace(tzinfo=TZ)
    if ends_at.tzinfo is None: ends_at = ends_at.replace(tzinfo=TZ)

    if therapist_id is not None:
        sql = text("""
            -- Konflikty z kalendarza indywidualnego
            SELECT ss.id, 'individual' as schedule_type, ss.kind, ss.starts_at, ss.ends_at, ss.status,
                   t.full_name AS therapist_name, c.full_name AS client_name
            FROM schedule_slots ss
            JOIN therapists t ON t.id = ss.therapist_id
            LEFT JOIN clients c ON c.id = ss.client_id
            WHERE ss.therapist_id = :person_id AND ss.status != 'cancelled'
              AND tstzrange(ss.starts_at, ss.ends_at, '[)') && tstzrange(:s, :e, '[)')
              AND (:exclude_id IS NULL OR ss.id != :exclude_id)
            UNION ALL
            -- Konflikty z kalendarza grupowego TUS
            SELECT s.id, 'tus_group' as schedule_type, 'therapy' as kind,
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
            SELECT ss.id, 'individual' as schedule_type, ss.kind, ss.starts_at, ss.ends_at, ss.status,
                   d.full_name AS driver_name, c.full_name AS client_name
            FROM schedule_slots ss
            JOIN drivers d ON d.id = ss.driver_id
            LEFT JOIN clients c ON c.id = ss.client_id
            WHERE ss.driver_id = :person_id AND ss.status != 'cancelled'
              AND tstzrange(ss.starts_at, ss.ends_at, '[)') && tstzrange(:s, :e, '[)')
              AND (:exclude_id IS NULL OR ss.id != :exclude_id)
        """)
        params = {"person_id": driver_id, "s": starts_at, "e": ends_at, "exclude_id": exclude_slot_id}
    else:
        return []

    try:
        # Konwertuj daty w wynikach na stringi ISO dla JSON
        conflicts = []
        for r in conn.execute(sql, params).mappings().all():
            row_dict = dict(r)
            if row_dict.get('starts_at'): row_dict['starts_at'] = row_dict['starts_at'].isoformat()
            if row_dict.get('ends_at'): row_dict['ends_at'] = row_dict['ends_at'].isoformat()
            conflicts.append(row_dict)
        return conflicts
    except Exception as e:
        print(f"Błąd w find_overlaps: {e}")
        return []


def ensure_shared_run_id_for_driver(conn, driver_id, starts_at, ends_at):
    q = text("SELECT id, run_id FROM schedule_slots WHERE driver_id = :did AND starts_at = :s AND ends_at = :e LIMIT 1")
    row = conn.execute(q, {"did": driver_id, "s": starts_at, "e": ends_at}).mappings().first()
    if not row: return None
    if row["run_id"] is None:
        new_run = str(uuid.uuid4())
        conn.execute(text("UPDATE schedule_slots SET run_id = :rid WHERE id = :id"), {"rid": new_run, "id": row["id"]})
        return new_run
    return row["run_id"]


def ensure_shared_session_id_for_therapist(conn, therapist_id, starts_at, ends_at):
    q = text("SELECT id, session_id FROM schedule_slots WHERE therapist_id = :tid AND starts_at = :s AND ends_at = :e LIMIT 1")
    row = conn.execute(q, {"tid": therapist_id, "s": starts_at, "e": ends_at}).mappings().first()
    if not row: return str(uuid.uuid4()) # Zawsze zwracaj ID, nawet jeśli nie ma jeszcze slotu
    if row["session_id"] is None:
        new_sid = str(uuid.uuid4())
        conn.execute(text("UPDATE schedule_slots SET session_id = :sid WHERE id = :id"), {"sid": new_sid, "id": row["id"]})
        return new_sid
    return row["session_id"]


# === DEKORATORY I HOOKI FLASK ===
@app.before_request
def parse_json_only_when_needed():
    # Pomijaj sprawdzanie dla endpointów logowania i statycznych plików
    if request.endpoint and (request.endpoint.startswith('auth.') or request.endpoint == 'static'):
        return

    # Jeśli endpoint wymaga logowania, sprawdź sesję PRZED próbą parsowania JSON
    view_func = app.view_functions.get(request.endpoint)
    if hasattr(view_func, '__wrapped__') and 'login_required' in str(view_func.__wrapped__):
         if 'logged_in' not in session or not session['logged_in']:
              # login_required sam obsłuży przekierowanie lub błąd 401
              return

    # Jeśli zalogowany lub endpoint nie wymaga logowania, parsuj JSON dla POST/PUT/PATCH
    if request.method in ('POST', 'PUT', 'PATCH'):
        g.json = request.get_json(silent=True) or {}
    else:
        g.json = None


@app.after_request
def after_request(response):
    # Dodaj nagłówki, aby uniknąć problemów z cache'owaniem API
    if request.path.startswith('/api/'):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# === GŁÓWNE ENDPOINTY APLIKACJI ===
# (Tutaj wklej WSZYSTKIE endpointy API: /api/clients, /api/therapists, /api/tus/groups itd.)
# WAŻNE: Dodaj dekorator @login_required do WSZYSTKICH endpointów API

@app.get("/api/available-therapists")
@login_required
def get_available_therapists():
    try:
        with engine.begin() as conn:
            therapists = conn.execute(text("SELECT id, full_name, specialization FROM therapists WHERE active = true ORDER BY full_name")).mappings().all()
            return jsonify([dict(t) for t in therapists]), 200
    except Exception as e:
        print(f"Błąd pobierania terapeutów: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-availability', methods=['POST', 'GET'])
@login_required
def check_availability():
    if request.method == 'GET':
        return jsonify({"message": "Endpoint check-availability jest aktywny", "usage": "Wymaga metody POST z danymi: therapist_id, starts_at, ends_at", "example_payload": {"therapist_id": 1, "starts_at": "2024-01-23T10:00:00", "ends_at": "2024-01-23T11:00:00"}}), 200

    data = request.get_json(silent=True) or {}
    therapist_id = data.get('therapist_id')
    starts_at = data.get('starts_at')
    ends_at = data.get('ends_at')
    exclude_slot_id = data.get('exclude_slot_id')

    if not all([therapist_id, starts_at, ends_at]): return jsonify({"error": "Brak wymaganych pól"}), 400

    try:
        starts_at_dt = datetime.fromisoformat(starts_at.replace('Z', '+00:00')).astimezone(TZ)
        ends_at_dt = datetime.fromisoformat(ends_at.replace('Z', '+00:00')).astimezone(TZ)

        with engine.begin() as conn:
            conflicts = find_overlaps(conn, therapist_id=therapist_id, starts_at=starts_at_dt, ends_at=ends_at_dt, exclude_slot_id=exclude_slot_id)
            return jsonify({"available": len(conflicts) == 0, "conflicts": conflicts}), 200
    except Exception as e:
        print(f"Błąd sprawdzania dostępności: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.get("/api/ai/gaps")
@login_required
def ai_gaps():
    mk = request.args.get("month") or datetime.now(TZ).strftime("%Y-%m")
    first = datetime.fromisoformat(mk + "-01").date()
    if first.month == 12: nxt = first.replace(year=first.year + 1, month=1, day=1)
    else: nxt = first.replace(month=first.month + 1, day=1)
    days = []
    d = first
    while d < nxt: days.append(d); d += timedelta(days=1)

    with engine.begin() as conn:
        clients = conn.execute(text("SELECT id, full_name FROM clients WHERE active=true")).mappings().all()
        therapists = conn.execute(text("SELECT id, full_name FROM therapists WHERE active=true")).mappings().all()
        drivers = conn.execute(text("SELECT id, full_name FROM drivers WHERE active=true")).mappings().all()
        q = text("SELECT kind, client_id, therapist_id, driver_id, (starts_at AT TIME ZONE 'Europe/Warsaw')::date AS d FROM schedule_slots WHERE to_char(starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk")
        rows = conn.execute(q, {"mk": mk}).mappings().all()

    had_therapy = {(r["client_id"], r["d"]) for r in rows if r["kind"] == "therapy"}
    th_worked = {(r["therapist_id"], r["d"]) for r in rows if r["therapist_id"] and r["kind"] == 'therapy'}
    dr_worked = {(r["driver_id"], r["d"]) for r in rows if r["driver_id"] and r["kind"] in ('pickup', 'dropoff')}

    clients_without = [{"id": c["id"], "full_name": c["full_name"], "date": _date_str(d)} for c in clients for d in days if (c["id"], d) not in had_therapy]
    therapists_idle = [{"id": t["id"], "full_name": t["full_name"], "date": _date_str(d)} for t in therapists for d in days if (t["id"], d) not in th_worked]
    drivers_idle = [{"id": dr["id"], "full_name": dr["full_name"], "date": _date_str(d)} for dr in drivers for d in days if (dr["id"], d) not in dr_worked]

    return jsonify({"clients_without_therapy_days": clients_without, "therapists_idle_days": therapists_idle, "drivers_idle_days": drivers_idle}), 200

@app.post("/api/ai/suggest")
@login_required
def ai_suggest():
    data = request.get_json(silent=True) or {}
    cid = int(data["client_id"])
    date_str = data["date"]
    window = data.get("therapy_window") or ["08:00", "16:00"]
    pk_off = int(data.get("pickup_offset_min", 30))
    dp_off = int(data.get("dropoff_offset_min", 30))
    start_bucket = _time_bucket(window[0])
    end_bucket = _time_bucket(window[1])

    all_buckets = []
    sh, sm = _parse_time(start_bucket); eh, em = _parse_time(end_bucket)
    cur_h, cur_m = sh, sm
    while (cur_h, cur_m) <= (eh, em):
        all_buckets.append(f"{cur_h:02d}:{cur_m:02d}")
        if cur_m == 0: cur_h, cur_m = cur_h, 30
        else: cur_h, cur_m = cur_h + 1, 0

    with engine.begin() as conn:
        q1 = text("SELECT t.id, t.full_name, COALESCE(v.n,0) AS n, v.last_dt FROM therapists t LEFT JOIN v_hist_client_therapist v ON v.therapist_id = t.id AND v.client_id = :cid WHERE t.active = true")
        th_rows = conn.execute(q1, {"cid": cid}).mappings().all()
        if not th_rows: return jsonify({"therapy": [], "drivers_pickup": [], "drivers_dropoff": []}), 200
        max_n_th = max((r["n"] for r in th_rows), default=0)

        q_thh = text("SELECT therapist_id, hhmm, n FROM v_hist_therapist_hour WHERE hhmm = ANY(:buckets)")
        thh = conn.execute(q_thh, {"buckets": all_buckets}).mappings().all()
        pref_map = {}
        for r in thh: pref_map.setdefault(r["therapist_id"], {})[r["hhmm"]] = r["n"]

        therapy_candidates = []
        today = datetime.now(TZ).date()
        for r in th_rows:
            last_dt = r["last_dt"]
            rec_days = (today - last_dt.date()).days if last_dt else None
            base_score = _score(r["n"], max_n_th, rec_days)
            hours_pref = pref_map.get(r["id"], {})
            best_bucket = max(all_buckets, key=lambda b: hours_pref.get(b, 0)) if hours_pref else all_buckets[len(all_buckets) // 2]
            th_start = _to_tstz(date_str, best_bucket)
            th_end = th_start + timedelta(minutes=60)

            col = find_overlaps(conn, therapist_id=r["id"], starts_at=th_start, ends_at=th_end)
            if col:
                tried = {best_bucket}
                ok = False
                for b in all_buckets:
                    if b in tried: continue
                    s2 = _to_tstz(date_str, b); e2 = s2 + timedelta(minutes=60)
                    if not find_overlaps(conn, therapist_id=r["id"], starts_at=s2, ends_at=e2):
                        best_bucket, th_start, th_end = b, s2, e2; ok = True; break
                if not ok: continue

            therapy_candidates.append({"therapist_id": r["id"], "full_name": r["full_name"], "score": round(base_score, 3), "suggested_start": th_start.isoformat(), "suggested_end": th_end.isoformat()})

        therapy_candidates.sort(key=lambda x: x["score"], reverse=True)
        therapy_candidates = therapy_candidates[:5]

        drivers_pickup = []; drivers_dropoff = []
        if therapy_candidates:
            best_th = therapy_candidates[0]
            th_s = datetime.fromisoformat(best_th["suggested_start"]); th_e = datetime.fromisoformat(best_th["suggested_end"])
            pk_end = th_s; pk_start = pk_end - timedelta(minutes=pk_off)
            dp_start = th_e; dp_end = dp_start + timedelta(minutes=dp_off)

            q2 = text("SELECT d.id, d.full_name, COALESCE(v.n,0) AS n, v.last_dt FROM drivers d LEFT JOIN v_hist_client_driver v ON v.driver_id = d.id AND v.client_id = :cid WHERE d.active = true")
            dr_rows = conn.execute(q2, {"cid": cid}).mappings().all()
            max_n_dr = max((r["n"] for r in dr_rows), default=0)

            buckets_needed = list({_time_bucket(pk_start.strftime("%H:%M")), _time_bucket(dp_start.strftime("%H:%M"))})
            q_drh = text("SELECT driver_id, hhmm, n FROM v_hist_driver_hour WHERE hhmm = ANY(:buckets)")
            drh = conn.execute(q_drh, {"buckets": buckets_needed}).mappings().all()
            dr_pref = {}
            for r in drh: dr_pref.setdefault(r["driver_id"], {})[r["hhmm"]] = r["n"]

            for r in dr_rows:
                rec_days = (today - r["last_dt"].date()).days if r["last_dt"] else None
                base = _score(r["n"], max_n_dr, rec_days)
                bpk = _time_bucket(pk_start.strftime("%H:%M"))
                base_pk = base + (0.05 if dr_pref.get(r["id"], {}).get(bpk, 0) > 0 else 0.0)
                col_pk = find_overlaps(conn, driver_id=r["id"], starts_at=pk_start, ends_at=pk_end)
                if not col_pk: drivers_pickup.append({"driver_id": r["id"], "full_name": r["full_name"], "score": round(base_pk, 3), "suggested_start": pk_start.isoformat(), "suggested_end": pk_end.isoformat()})

                bdp = _time_bucket(dp_start.strftime("%H:%M"))
                base_dp = base + (0.05 if dr_pref.get(r["id"], {}).get(bdp, 0) > 0 else 0.0)
                col_dp = find_overlaps(conn, driver_id=r["id"], starts_at=dp_start, ends_at=dp_end)
                if not col_dp: drivers_dropoff.append({"driver_id": r["id"], "full_name": r["full_name"], "score": round(base_dp, 3), "suggested_start": dp_start.isoformat(), "suggested_end": dp_end.isoformat()})

            drivers_pickup.sort(key=lambda x: x["score"], reverse=True)
            drivers_dropoff.sort(key=lambda x: x["score"], reverse=True)
            drivers_pickup = drivers_pickup[:5]
            drivers_dropoff = drivers_dropoff[:5]

    return jsonify({"therapy": therapy_candidates, "drivers_pickup": drivers_pickup, "drivers_dropoff": drivers_dropoff}), 200

@app.get("/api/ai/recommend")
@login_required
def ai_recommend():
    cid = request.args.get("client_id", type=int)
    if not cid: return jsonify({"error": "client_id is required"}), 400

    with engine.begin() as conn:
        q_ct = text("SELECT f.therapist_id, t.full_name, f.n_sessions, f.minutes_sum, f.done_ratio, f.days_since_last, f.recency_weight FROM v_ct_features f JOIN therapists t ON t.id=f.therapist_id AND t.active=true WHERE f.client_id=:cid")
        ct_rows = [dict(r) for r in conn.execute(q_ct, {"cid": cid}).mappings().all()]
        q_cd = text("SELECT f.driver_id, d.full_name, f.n_runs, f.minutes_sum, f.done_ratio, f.days_since_last, f.recency_weight FROM v_cd_features f JOIN drivers d ON d.id=f.driver_id AND d.active=true WHERE f.client_id=:cid")
        cd_rows = [dict(r) for r in conn.execute(q_cd, {"cid": cid}).mappings().all()]
        qtp = text("SELECT dow, hour, cnt FROM v_client_time_prefs WHERE client_id=:cid ORDER BY cnt DESC LIMIT 6")
        time_prefs = [dict(r) for r in conn.execute(qtp, {"cid": cid}).mappings().all()]

    if ct_model and ct_rows:
        features = ["n_sessions", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
        X_ct = pd.DataFrame(ct_rows)[features].fillna(0) # Dodano fillna(0)
        scores = ct_model.predict_proba(X_ct)[:, 1]
        for r, score in zip(ct_rows, scores): r["score"] = round(score, 4)
    else:
        for r in ct_rows: r["score"] = round(_score_ct_row(r), 4)

    if cd_model and cd_rows:
        features = ["n_runs", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
        X_cd = pd.DataFrame(cd_rows)[features].fillna(0) # Dodano fillna(0)
        scores = cd_model.predict_proba(X_cd)[:, 1]
        for r, score in zip(cd_rows, scores): r["score"] = round(score, 4)
    else:
        for r in cd_rows: r["score"] = round(_score_cd_row(r), 4)

    ct_rows.sort(key=lambda x: x["score"], reverse=True)
    cd_rows.sort(key=lambda x: x["score"], reverse=True)

    return jsonify({"therapists": ct_rows[:5], "drivers": cd_rows[:5], "time_prefs": time_prefs}), 200

@app.get("/api/clients")
@login_required
def list_clients_with_suo():
    mk = request.args.get("month") or datetime.now(TZ).strftime("%Y-%m")
    q = (request.args.get("q") or "").strip()
    therapist_id = request.args.get("therapist_id", type=int)
    include_inactive = request.args.get("include_inactive") in ("1", "true", "yes")
    where = []
    params = {"mk": mk}
    if not include_inactive: where.append("c.active IS TRUE")
    if q: where.append("c.full_name ILIKE :q"); params["q"] = f"%{q}%"
    if therapist_id: where.append("EXISTS (SELECT 1 FROM schedule_slots s WHERE s.client_id = c.id AND s.therapist_id = :tid AND s.kind = 'therapy' AND to_char(s.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk)"); params["tid"] = therapist_id
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"""WITH used AS (SELECT client_id, minutes_used FROM suo_usage WHERE month_key = :mk) SELECT c.id AS client_id, c.full_name, c.phone, c.address, c.active, c.photo_url, EXISTS (SELECT 1 FROM client_unavailability cu WHERE cu.client_id = c.id) AS has_unavailability_plan, :mk AS month_key, a.minutes_quota, COALESCE(u.minutes_used, 0) AS minutes_used, CASE WHEN a.minutes_quota IS NULL THEN NULL ELSE a.minutes_quota - COALESCE(u.minutes_used, 0) END AS minutes_left, (a.minutes_quota IS NULL) AS needs_allocation FROM clients c LEFT JOIN used u ON u.client_id = c.id LEFT JOIN suo_allocations a ON a.client_id = c.id AND a.month_key = :mk {where_sql} ORDER BY c.full_name;"""
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        return jsonify([dict(r) for r in rows]), 200

@app.delete("/api/clients/<int:cid>")
@login_required
def delete_client(cid):
    with engine.begin() as conn:
        res = conn.execute(text("DELETE FROM clients WHERE id=:id"), {"id": cid})
    return ("", 204) if res.rowcount > 0 else (jsonify({"error": "Client not found"}), 404)

@app.post("/api/clients")
@login_required
def create_client():
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    if not full_name: return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400
    sql = "INSERT INTO clients (full_name, phone, address, active, birth_date, diagnosis, notes) VALUES (:full_name, :phone, :address, COALESCE(:active,true), :bdate, :diag, :notes) RETURNING id, full_name, phone, address, active, birth_date, diagnosis, notes;"
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {"full_name": full_name, "phone": data.get("phone"), "address": data.get("address"), "active": bool(data.get("active", True)), "bdate": data.get("birth_date"), "diag": data.get("diagnosis"), "notes": data.get("notes") }).mappings().first()
            new_client = dict(row)
            if new_client.get('birth_date'): new_client['birth_date'] = new_client['birth_date'].isoformat()
            return jsonify(new_client), 201
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION: return jsonify({"error": "Taki klient już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409

@app.put("/api/clients/<int:cid>")
@login_required
def update_client(cid):
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    if not full_name: return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400
    sql = "UPDATE clients SET full_name = :full_name, phone = :phone, address = :address, active = COALESCE(:active, true), photo_url = :photo_url, birth_date = :bdate, diagnosis = :diag, notes = :notes WHERE id = :id RETURNING id, full_name, phone, address, active, photo_url, birth_date, diagnosis, notes;"
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {"id": cid, "full_name": full_name, "phone": data.get("phone"), "address": data.get("address"), "active": data.get("active", True), "photo_url": data.get("photo_url"), "bdate": data.get("birth_date"), "diag": data.get("diagnosis"), "notes": data.get("notes")}).mappings().first()
            if not row: return jsonify({"error": "Klient nie istnieje."}), 404
            updated_client = dict(row)
            if updated_client.get('birth_date'): updated_client['birth_date'] = updated_client['birth_date'].isoformat()
            return jsonify(updated_client), 200
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION: return jsonify({"error": "Taki klient już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409

@app.route('/api/groups/<group_id>', methods=['GET'])
@login_required
def get_package_group(group_id):
    """Pobiera pakiet na podstawie UUID group_id - UŻYWA SQLAlchemy"""
    try:
        group_uuid = uuid.UUID(group_id) # Walidacja UUID
    except ValueError:
        return jsonify({"error": "Nieprawidłowy format group_id (oczekiwano UUID)"}), 400

    try:
        with session_scope() as db_session:
            slots = db_session.query(ScheduleSlot).filter(ScheduleSlot.group_id == group_uuid).order_by(
                # Sortowanie pickup -> therapy -> dropoff
                func.nullif(ScheduleSlot.kind == 'pickup', False),
                func.nullif(ScheduleSlot.kind == 'therapy', False),
                func.nullif(ScheduleSlot.kind == 'dropoff', False)
            ).all()

            if not slots: return jsonify({"error": "Pakiet nie znaleziony"}), 404

            first = slots[0]
            result = {"group_id": str(first.group_id), "client_id": first.client_id, "status": first.status, "label": None } # Domyślny label

            # Pobierz label z EventGroup jeśli istnieje
            event_group = db_session.query(EventGroup).filter(EventGroup.id == group_uuid).first()
            if event_group: result["label"] = event_group.label

            for slot in slots:
                slot_data = {
                    "slot_id": slot.id,
                    "starts_at": slot.starts_at.isoformat() if slot.starts_at else None,
                    "ends_at": slot.ends_at.isoformat() if slot.ends_at else None,
                    "status": slot.status
                }
                if slot.kind == "therapy":
                    result["therapy"] = {**slot_data, "therapist_id": slot.therapist_id, "place": slot.place_to}
                elif slot.kind == "pickup":
                    result["pickup"] = {**slot_data, "driver_id": slot.driver_id, "vehicle_id": slot.vehicle_id, "from": slot.place_from, "to": slot.place_to}
                elif slot.kind == "dropoff":
                    result["dropoff"] = {**slot_data, "driver_id": slot.driver_id, "vehicle_id": slot.vehicle_id, "from": slot.place_from, "to": slot.place_to}

            return jsonify(result)

    except Exception as e:
        print(f"BŁĄD w get_package_group: {e}"); traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.get("/api/therapists")
@login_required
def list_therapists():
    with SessionLocal() as s:
        therapists = s.query(Therapist).filter(Therapist.active == True).order_by(Therapist.full_name).all()
        return jsonify([{"id": t.id, "full_name": t.full_name, "specialization": t.specialization, "phone": t.phone, "active": bool(t.active)} for t in therapists])

@app.post("/api/therapists")
@login_required
def create_therapist():
    data = request.get_json(force=True)
    full_name = (data.get("full_name") or "").strip()
    if not full_name: return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400
    sql = text("INSERT INTO therapists (full_name, specialization, phone, active) VALUES (:full_name, :specialization, :phone, COALESCE(:active,true)) RETURNING id, full_name, specialization, phone, active;")
    try:
        with engine.begin() as conn:
            row = conn.execute(sql, {"full_name": full_name, "specialization": data.get("specialization"), "phone": data.get("phone"), "active": bool(data.get("active", True))}).mappings().first()
            return jsonify(dict(row)), 201
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION: return jsonify({"error": "Taki terapeuta już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409

@app.put("/api/therapists/<int:tid>")
@login_required
def update_therapist(tid):
    with session_scope() as db_session: # Poprawiono session na db_session
        therapist = db_session.query(Therapist).filter_by(id=tid).first()
        if not therapist: return jsonify({"error": "Terapeuta nie istnieje."}), 404
        data = request.get_json(silent=True) or {}
        therapist.full_name = data.get("full_name", therapist.full_name)
        therapist.specialization = data.get("specialization", therapist.specialization)
        therapist.phone = data.get("phone", therapist.phone)
        therapist.active = data.get("active", therapist.active)
        try:
            # db_session.commit() # session_scope robi commit automatycznie
            return jsonify({"id": therapist.id, "full_name": therapist.full_name}), 200
        except IntegrityError:
            # db_session.rollback() # session_scope robi rollback automatycznie
            return jsonify({"error": "Taki terapeuta już istnieje (imię i nazwisko)."}), 409

@app.delete("/api/therapists/<int:tid>")
@login_required
def delete_therapist(tid):
    with session_scope() as db_session:
        therapist = db_session.query(Therapist).filter_by(id=tid).first()
        if not therapist: return jsonify({"error": "Therapist not found"}), 404
        db_session.delete(therapist)
        # db_session.commit() # session_scope robi commit automatycznie
    return "", 204

@app.get("/api/drivers")
@login_required
def list_drivers():
    with session_scope() as s:
        q = s.query(Driver)
        active_param = request.args.get("active")
        if active_param is not None:
            val = str(active_param).strip().lower()
            if val in ("1", "true", "t", "yes", "y"): q = q.filter(Driver.active.is_(True))
            elif val in ("0", "false", "f", "no", "n"): q = q.filter(Driver.active.is_(False))
        drivers = q.order_by(Driver.full_name).all()
        return jsonify([{"id": d.id, "full_name": d.full_name, "phone": getattr(d, "phone", None), "active": getattr(d, "active", True)} for d in drivers])

@app.post("/api/drivers")
@login_required
def create_driver():
    data = request.get_json(silent=True) or {}
    if not data or not data.get("full_name"): return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400
    with session_scope() as db_session:
        new_driver = Driver(full_name=data["full_name"], phone=data.get("phone"), active=data.get("active", True))
        db_session.add(new_driver)
        try:
            db_session.flush() # Aby uzyskać ID przed commitem
            return jsonify({"id": new_driver.id, "full_name": new_driver.full_name}), 201
        except IntegrityError:
            # db_session.rollback() # session_scope robi rollback
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409

@app.put("/api/drivers/<int:did>")
@login_required
def update_driver(did):
    with session_scope() as db_session:
        driver = db_session.query(Driver).filter_by(id=did).first()
        if not driver: return jsonify({"error": "Kierowca nie istnieje."}), 404
        data = request.get_json(silent=True) or {}
        driver.full_name = data.get("full_name", driver.full_name)
        driver.phone = data.get("phone", driver.phone)
        driver.active = data.get("active", driver.active)
        try:
            # db_session.commit() # session_scope robi commit
            return jsonify({"id": driver.id, "full_name": driver.full_name}), 200
        except IntegrityError:
            # db_session.rollback() # session_scope robi rollback
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409

@app.delete("/api/drivers/<int:did>")
@login_required
def delete_driver(did):
    with session_scope() as db_session:
        driver = db_session.query(Driver).filter_by(id=did).first()
        if not driver: return jsonify({"error": "Driver not found"}), 404
        db_session.delete(driver)
        # db_session.commit() # session_scope robi commit
    return "", 204

# === Reszta endpointów API (dodaj @login_required do każdego) ===
# (Tutaj wklej resztę endpointów API z pierwszego kodu, dodając @login_required)

@app.get("/api/clients/<int:client_id>/unavailability")
@login_required
def get_client_unavailability(client_id):
    sql = text("SELECT id, day_of_week, start_time, end_time, notes FROM client_unavailability WHERE client_id = :cid ORDER BY day_of_week, start_time")
    with engine.begin() as conn:
        rows = conn.execute(sql, {"cid": client_id}).mappings().all()
        results = [{**row, 'start_time': row['start_time'].strftime('%H:%M'), 'end_time': row['end_time'].strftime('%H:%M')} for row in rows]
        return jsonify(results)

@app.post("/api/clients/<int:client_id>/unavailability")
@login_required
def add_client_unavailability(client_id):
    data = request.get_json(silent=True) or {}
    required = ['day_of_week', 'start_time', 'end_time']
    if not all(k in data for k in required): return jsonify({"error": "Brak wymaganych pól (dzień, start, koniec)."}), 400
    sql = text("INSERT INTO client_unavailability (client_id, day_of_week, start_time, end_time, notes) VALUES (:cid, :dow, :start, :end, :notes) RETURNING id")
    with engine.begin() as conn:
        new_id = conn.execute(sql, {"cid": client_id, "dow": data['day_of_week'], "start": data['start_time'], "end": data['end_time'], "notes": data.get('notes')}).scalar_one()
    return jsonify({"id": new_id, **data}), 201

@app.delete("/api/unavailability/<int:entry_id>")
@login_required
def delete_unavailability(entry_id):
    sql = text("DELETE FROM client_unavailability WHERE id = :id")
    with engine.begin() as conn:
        result = conn.execute(sql, {"id": entry_id})
    return ("", 204) if result.rowcount > 0 else (jsonify({"error": "Nie znaleziono wpisu."}), 404)


# === Uruchomienie aplikacji ===
if __name__ == '__main__':
    # Inicjalizacja tabel przy starcie (opcjonalnie, ale zalecane)
    if init_all_tables():
        # Uruchom serwer testowy Flask
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        print("Nie udało się zainicjalizować tabel bazy danych. Aplikacja nie zostanie uruchomiona.")

