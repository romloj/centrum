# === SEKCJA 1: IMPORTY ===

# 1. Biblioteka standardowa
import base64
import io
import json
import math
import mimetypes
import os
import re
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, date, time
from functools import wraps
from math import exp
from zoneinfo import ZoneInfo

# 2. Biblioteki zewnętrzne
import joblib
import pandas as pd
import psutil
import psycopg2
import requests
from PIL import Image
from flask import Flask, jsonify, request, g, session, redirect, url_for, send_from_directory, send_file,render_template
from flask_cors import CORS
from geopy.distance import geodesic
from psycopg2 import errorcodes
from psycopg2.extras import RealDictCursor
from requests.exceptions import ReadTimeout
from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Table,
                        Boolean, Float, Time, create_engine, func, text, bindparam, TIMESTAMP, Date, desc,
                        UniqueConstraint, select, ARRAY, Enum, TEXT)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import declarative_base, selectinload
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base, relationship, joinedload, aliased
from werkzeug.utils import secure_filename

print("--- SERWER ZALADOWAL NAJNOWSZA WERSJE PLIKU (POSPRZĄTANĄ) ---")

# === SEKCJA 2: KONFIGURACJA APLIKACJI I ZMIENNE GLOBALNE ===

# Strefa czasowa
TZ = ZoneInfo("Europe/Warsaw")

# Inicjalizacja aplikacji Flask
app = Flask(__name__)
CORS(app)
app.config['DEBUG'] = True

# Wczytywanie konfiguracji ze zmiennych środowiskowych
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:EDUQ@localhost:5432/suo")
GOOGLE_MAPS_API_KEY = os.getenv("klucz", "AIzaSyC5TGcemvDn-BZ5khdlQOOpPZVV2qLMYc8")  # Dodano fallback dla klucza

# Konfiguracja uploadu
UPLOAD_FOLDER = 'uploads/documents'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Stwórz folder jeśli nie istnieje
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join('uploads', 'clients'), exist_ok=True) # Dla zdjęć klientów

# Dodaj do konfiguracji Flask
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# === DODAJ TĘ LINIĘ DIAGNOSTYCZNĄ ===
print(f"--- APLIKACJA ŁĄCZY SIĘ Z BAZĄ DANYCH: {DATABASE_URL} ---")
# ====================================

# === SEKCJA 3: INICJALIZACJA BAZY DANYCH (ORM) ===

engine = create_engine(DATABASE_URL, future=True)
Base = declarative_base()
SessionLocal = scoped_session(
    sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
)
Session = sessionmaker(bind=engine) # Używane w niektórych miejscach

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


# === SEKCJA 4: MODELE BAZY DANYCH (SQLALCHEMY) ===

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
    photo_url = Column(String) # Dodane pole ze zduplikowanego list_clients
    # Relacje
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
    # Nowe pola z /api/schedule/check-conflicts (jeśli ich brakuje)
    vehicle_id = Column(Integer)
    place_from = Column(String)
    place_to = Column(String)
    # Relacje
    attendance = relationship("IndividualSessionAttendance", uselist=False, cascade="all, delete-orphan")

class TUSGroupMember(Base):
    __tablename__ = "tus_group_members"
    group_id = Column(Integer, ForeignKey("tus_groups.id", ondelete="CASCADE"), primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # Relacje
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
    # Pola na cele
    halfyear_target_points = Column(Integer)
    halfyear_reward = Column(String)
    annual_target_points = Column(Integer)
    annual_reward = Column(String)
    schedule_days = Column(ARRAY(Date))
    # Relacje
    therapist = relationship("Therapist", back_populates="tus_groups", lazy="selectin", foreign_keys=[therapist_id])
    sessions = relationship("TUSSession", back_populates="group", cascade="all, delete-orphan", lazy="selectin")
    assistant_therapist = relationship("Therapist", lazy="selectin", foreign_keys=[assistant_therapist_id])
    member_associations = relationship("TUSGroupMember", back_populates="group", cascade="all, delete-orphan")
    members = association_proxy(
        'member_associations',
        'client',
        creator=_create_member_association
    )

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
    # Relacje
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
    # Relacje
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
    # Relacje
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
    # Relacje
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
    # Relacje
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
    # Relacje
    client = relationship("Client", foreign_keys=[client_id], lazy="joined")
    therapist = relationship("Therapist", foreign_keys=[therapist_id], lazy="joined")


# === SEKCJA 5: INICJALIZACJA TABEL (FUNKCJE) ===

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

def init_all_tables():
    """Inicjalizacja wszystkich tabel aplikacji"""
    print("\n" + "=" * 60)
    print("INICJALIZACJA TABEL BAZY DANYCH")
    print("=" * 60)
    try:
        with engine.begin() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✓ Połączono z PostgreSQL")
            print(f"  {version[:60]}...")
        
        # Wywołaj poszczególne funkcje inicjalizujące
        # (Kolejność może mieć znaczenie, jeśli są zależności FK)
        # Tabele bazowe
        init_journal_table()
        init_client_notes_table()
        init_waiting_clients_table()
        init_documents_table()
        init_foundation_table()
        init_projects_table()
        
        # Tabele zależne (jeśli takie są)
        # ...

        print("=" * 60)
        print("✓ WSZYSTKIE TABELE GOTOWE")
        print("=" * 60 + "\n")
        return True
    except Exception as e:
        print("\n" + "=" * 60)
        print("✗ BŁĄD INICJALIZACJI")
        print("=" * 60)
        print(f"Błąd: {str(e)}")
        print(traceback.format_exc())
        print("=" * 60 + "\n")
        return False


# === SEKCJA 6: WCZYTANIE MODELI AI ===

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


# === SEKCJA 7: FUNKCJE POMOCNICZE ===

def validate_date(date_string, field_name):
    """Waliduje format daty"""
    try:
        # Używamy date.fromisoformat dla 'YYYY-MM-DD'
        if 'T' in date_string:
            datetime.fromisoformat(date_string)
        else:
            date.fromisoformat(date_string)
        return None
    except (ValueError, TypeError):
        return f'Nieprawidłowy format daty w polu {field_name}'

def validate_length(value, field_name, max_length):
    """Waliduje długość tekstu"""
    if value and len(value) > max_length:
        return f'{field_name} zbyt długie (max {max_length} znaków)'
    return None

def calculate_distance(lat1, lon1, lat2, lon2):
    if lat1 and lon1 and lat2 and lon2:
        return geodesic((lat1, lon1), (lat2, lon2)).kilometers
    return 0

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
        # print(f"Porównuję: '{name_to_find_lower}' z '{full_name_lower}'") # Wyłączone dla czystości

        # 1. Dokładne dopasowanie (najwyższy priorytet)
        if full_name_lower == name_to_find_lower:
            current_score = 100
            # print("  → Dokładne dopasowanie!")

        # 2. Dopasowanie skrótu z inicjałem "Jan M" -> "Jan Kowalski"
        elif len(parts_to_find) == 2 and len(parts_full) >= 2:
            first_name_find = parts_to_find[0]
            last_initial_find = parts_to_find[1]

            if (parts_full[0] == first_name_find and
                    len(last_initial_find) == 1 and
                    parts_full[1][0] == last_initial_find[0]):
                current_score = 95
                # print(f"  → Dopasowanie inicjału...")

        # 3. Dopasowanie tylko imienia "Jan" -> "Jan Kowalski"
        elif len(parts_to_find) == 1 and len(parts_full) >= 1:
            if parts_full[0] == parts_to_find[0]:
                current_score = 70
                # print(f"  → Dopasowanie imienia...")

        # 4. Dopasowanie przez zawieranie
        elif name_to_find_lower in full_name_lower:
            current_score = 50
            # print(f"  → Zawieranie...")

        # 5. Dopasowanie pierwszego słowa
        elif parts_to_find and parts_full and parts_to_find[0] == parts_full[0]:
            current_score = 60
            # print(f"  → Dopasowanie pierwszego słowa...")

        # 6. Dopasowanie przez wspólne słowa
        else:
            matching_words = 0
            for word in parts_to_find:
                if any(part.startswith(word) for part in parts_full if len(word) > 1):
                    matching_words += 1

            if matching_words == len(parts_to_find):
                current_score = 80
                # print(f"  → Wszystkie słowa pasują...")
            elif matching_words > 0:
                current_score = 40 + (matching_words * 10)
                # print(f"  → Częściowe dopasowanie słów...")

        # Aktualizuj najlepsze dopasowanie
        if current_score > highest_score:
            highest_score = current_score
            best_match = full_name
            # print(f"  → NOWE NAJLEPSZE DOPASOWANIE: {full_name} (wynik: {current_score})")

    # Zwróć wynik tylko jeśli osiągnięto minimalny próg dopasowania
    # print(f"NAJLEPSZE DOPASOWANIE: {best_match} (wynik: {highest_score})")

    if highest_score >= 40:
        return best_match
    
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

def get_route_distance(origin, destination):
    """Oblicza dystans między dwoma punktami za pomocą Google Maps API."""
    print(f"\n{'=' * 60}")
    print(f"FUNKCJA get_route_distance() WYWOŁANA")
    print(f"Origin: '{origin}'")
    print(f"Destination: '{destination}'")
    
    api_key = GOOGLE_MAPS_API_KEY
    print(f"Klucz API w funkcji: {api_key[:10]}..." if api_key else "❌ BRAK")

    if not api_key:
        print("⚠️ OSTRZEŻENIE: Brak klucza GOOGLE_MAPS_API_KEY. Obliczanie dystansu nie zadziała.")
        return None
    if not origin or not destination:
        print("⚠️ OSTRZEŻENIE: Brak origin lub destination")
        return None

    origin_safe = requests.utils.quote(origin)
    destination_safe = requests.utils.quote(destination)
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin_safe}&destination={destination_safe}&key={api_key}"
    print(f"📡 URL (bez klucza): ...{url.replace(api_key, 'KLUCZ_UKRYTY')[-70:]}")

    try:
        print("📤 Wysyłam zapytanie do Google Maps...")
        response = requests.get(url, timeout=10)
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

def _score_ct_row(r):
    """Heurystyka oceny dopasowania klient-terapeuta (fallback dla AI)."""
    n = r.get("n_sessions", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5 * rec + 0.3 * done + 0.2 * min(1.0, n / 10.0) + 0.1 * min(1.0, mins / 600.0)

def find_overlaps(conn, *, driver_id=None, therapist_id=None, starts_at=None, ends_at=None):
    """
    Zwraca listę kolidujących slotów dla driver_id/therapist_id i podanego zakresu czasu,
    sprawdzając ZARÓWNO kalendarz indywidualny, jak i grupowy TUS.
    """
    if starts_at is None or ends_at is None:
        return []

    if therapist_id is not None:
        sql = text("""
            -- 1. Konflikty z kalendarza indywidualnego
            SELECT
              ss.id, 'individual' as schedule_type, ss.kind, ss.starts_at, ss.ends_at, ss.status,
              t.full_name AS therapist_name, c.full_name AS client_name
            FROM schedule_slots ss
            JOIN therapists t ON t.id = ss.therapist_id
            LEFT JOIN clients c ON c.id = ss.client_id
            WHERE ss.therapist_id = :person_id
              AND tstzrange(ss.starts_at, ss.ends_at, '[)') && tstzrange(:s, :e, '[)')
            UNION ALL
            -- 2. Konflikty z kalendarza grupowego TUS
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
        params = {"person_id": therapist_id, "s": starts_at, "e": ends_at}
    elif driver_id is not None:
        sql = text("""
            SELECT
              ss.id, 'individual' as schedule_type, ss.kind, ss.starts_at, ss.ends_at, ss.status,
              d.full_name AS driver_name, c.full_name AS client_name
            FROM schedule_slots ss
            JOIN drivers d ON d.id = ss.driver_id
            LEFT JOIN clients c ON c.id = ss.client_id
            WHERE ss.driver_id = :person_id
              AND tstzrange(ss.starts_at, ss.ends_at, '[)') && tstzrange(:s, :e, '[)')
        """)
        params = {"person_id": driver_id, "s": starts_at, "e": ends_at}
    else:
        return []

    stmt = sql.bindparams(
        bindparam("s", type_=TIMESTAMP(timezone=True)),
        bindparam("e", type_=TIMESTAMP(timezone=True)),
    )
    return [dict(r) for r in conn.execute(stmt, params).mappings().all()]

def _availability_conflicts(conn, therapist_id=None, driver_id=None, starts_at=None, ends_at=None):
    """Sprawdza konflikty w harmonogramie dla danej osoby i czasu."""
    return find_overlaps(conn,
                         therapist_id=therapist_id,
                         driver_id=driver_id,
                         starts_at=starts_at, ends_at=ends_at)

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

def _half_bounds(year: int, half: int):
    if half == 1:
        a = datetime(year, 1, 1, tzinfo=TZ);
        b = datetime(year, 7, 1, tzinfo=TZ)
    else:
        a = datetime(year, 7, 1, tzinfo=TZ);
        b = datetime(year + 1, 1, 1, tzinfo=TZ)
    return a, b

def fetch_krs_data(krs_number):
    """Pobieranie danych z KRS przez API (placeholder)"""
    try:
        # Próba 1: API MS (Ministerstwo Sprawiedliwości)
        url = f"https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs_number}"
        headers = {'Accept': 'application/json'}
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
    """Parsowanie odpowiedzi z oficjalnego API MS (placeholder)"""
    try:
        foundation_data = {
            'name': data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('danePodmiotu', {}).get('nazwa', ''),
            'krs': data.get('odpis', {}).get('naglowekA', {}).get('numerKRS', ''),
            'nip': data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('danePodmiotu', {}).get('identyfikatory', {}).get('nip', ''),
            'regon': data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('danePodmiotu', {}).get('identyfikatory', {}).get('regon', ''),
        }
        adres = data.get('odpis', {}).get('dane', {}).get('dzial1', {}).get('siedzibaIAdres', {}).get('adres', {})
        foundation_data['city'] = adres.get('miejscowosc', '')
        foundation_data['voivodeship'] = adres.get('wojewodztwo', '')
        foundation_data['street'] = adres.get('ulica', '')
        foundation_data['building_number'] = adres.get('nrDomu', '')
        foundation_data['postal_code'] = adres.get('kodPocztowy', '')
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
    """Parsowanie odpowiedzi z alternatywnego API rejestr.io (placeholder)"""
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


# === SEKCJA 8: FLASK HOOKS ===

@app.before_request
def parse_json_only_when_needed():
    if request.method in ('POST', 'PUT', 'PATCH'):
        g.json = request.get_json(silent=True) or {}
    else:
        g.json = None

@app.before_request
def print_endpoint():
    """Loguje wywoływany endpoint do konsoli."""
    if request.endpoint:
        print(f"--- Endpoint: {request.endpoint}, Method: {request.method} ---")


# === SEKCJA 9: TRASY API (ENDPOINTY) ===

# --- Trasy serwujące pliki (HTML, Uploads) ---

@app.get("/")
def index():
    """Serwuje główną stronę aplikacji (panel nawigacyjny)."""
    # Używamy render_template, ponieważ plik jest w folderze /templates
    # i zawiera logikę Jinja2 (np. url_for, {% if ... %})
    try:
        # Przekazujemy domyślne wartości, aby uniknąć błędów renderowania
        return render_template('index.html', is_admin=True, therapist_id=1, driver_id=1)
    except Exception as e:
        print(f"BŁĄD renderowania index.html: {e}")
        return f"Błąd szablonu: {e}", 500

@app.get("/tus")
def tus_page():
    """Serwuje stronę modułu TUS."""
    # Ten plik jest również szablonem w /templates
    return render_template("tus.html")

@app.get("/individual_attendance.html")
def individual_attendance_page():
    """Serwuje stronę obecności indywidualnej."""
    # Ten plik jest również szablonem w /templates
    return render_template("individual_attendance.html")

# --- DODANE BRAKUJĄCE TRASY Z index.html ---
# Te trasy są wymagane przez wywołania {{ url_for(...) }} w Twoim panelu.
# Na razie wszystkie renderują 'index.html' jako placeholder.
# Później możesz podmienić 'index.html' na właściwe pliki szablonów.

@app.get("/klient-panel")
def klient_panel():
    """Placeholder dla panelu klienta."""
    # TODO: Zmień 'index.html' na właściwy szablon, np. 'klient_panel.html'
    return render_template('klient-panel.html', is_admin=True, therapist_id=1, driver_id=1)

@app.get("/driver-schedule")
def driver_schedule_page():
    """Placeholder dla panelu kierowcy."""
    # TODO: Zmień 'index.html' na właściwy szablon
    return render_template('kierowcy.html', is_admin=True, therapist_id=1, driver_id=1)

@app.get("/panel-suo")
def panel():
    """Placeholder dla planu SUO."""
    # TODO: Zmień 'index.html' na właściwy szablon
    return render_template('panel.html', is_admin=True, therapist_id=1, driver_id=1)

@app.get("/manager")
def manager_page():
    """Placeholder dla menadżera dokumentów."""
    # TODO: Zmień 'index.html' na właściwy szablon
    return render_template('manager.html', is_admin=True, therapist_id=1, driver_id=1)

@app.get("/waiting-list")
def waiting_list_page():
    """Placeholder dla listy oczekujących."""
    # TODO: Zmień 'index.html' na właściwy szablon
    return render_template('poczekalnia.html', is_admin=True, therapist_id=1, driver_id=1)

@app.get("/terapeuta")
def terapeuta():
    """Placeholder dla strony terapeuty."""
    # TODO: Zmień 'index.html' na właściwy szablon
    return render_template('terapeuta.html', is_admin=True, therapist_id=1, driver_id=1)

@app.get("/sprawozdania-new")
def sprawozdania_new():
    """Placeholder dla strony sprawozdań."""
    # TODO: Zmień 'index.html' na właściwy szablon
    return render_template('sprawozdania.html', is_admin=True, therapist_id=1, driver_id=1)

# --- Trasa serwująca UPLOADY (zostaje bez zmian) ---

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Serwuje uploadowane pliki"""
    # Poprawka: serwowanie z podkatalogów (np. /uploads/clients/...)
    base_dir = os.path.join(os.getcwd(), 'uploads')
    # Zabezpieczenie przed cofaniem się w ścieżce
    safe_path = os.path.normpath(os.path.join(base_dir, filename))
    if not safe_path.startswith(base_dir):
        return "Forbidden", 403
    
    # Znajdź katalog, w którym jest plik
    directory, file_name = os.path.split(safe_path)
    return send_from_directory(directory, file_name)

# --- Trasy AI i Rekomendacji ---

@app.get("/api/ai/gaps")
def ai_gaps():
    """Zwraca luki w harmonogramie dla miesiąca."""
    mk = request.args.get("month") or datetime.now(TZ).strftime("%Y-%m")
    first = datetime.fromisoformat(mk + "-01").date()
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
        clients = conn.execute(text("SELECT id, full_name FROM clients WHERE active=true")).mappings().all()
        therapists = conn.execute(text("SELECT id, full_name FROM therapists WHERE active=true")).mappings().all()
        drivers = conn.execute(text("SELECT id, full_name FROM drivers WHERE active=true")).mappings().all()

        q = text("""
              SELECT kind, client_id, therapist_id, driver_id,
                     (starts_at AT TIME ZONE 'Europe/Warsaw')::date AS d
              FROM schedule_slots
              WHERE to_char(starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            """)
        rows = conn.execute(q, {"mk": mk}).mappings().all()

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
    """Sugeruje terapeutów i kierowców dla klienta i daty."""
    data = request.get_json(silent=True) or {}
    cid = int(data["client_id"])
    date_str = data["date"]
    window = data.get("therapy_window") or ["08:00", "16:00"]
    pk_off = int(data.get("pickup_offset_min", 30))
    dp_off = int(data.get("dropoff_offset_min", 30))
    start_bucket = _time_bucket(window[0])
    end_bucket = _time_bucket(window[1])

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

        max_n_th = max((r["n"] for r in th_rows), default=0)
        q_thh = text("""
              SELECT therapist_id, hhmm, n FROM v_hist_therapist_hour
              WHERE hhmm = ANY(:buckets)
            """)
        thh = conn.execute(q_thh, {"buckets": all_buckets}).mappings().all()
        pref_map = {}
        for r in thh:
            pref_map.setdefault(r["therapist_id"], {})[r["hhmm"]] = r["n"]

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

            col = _availability_conflicts(conn, therapist_id=r["id"], starts_at=th_start, ends_at=th_end)
            if col:
                tried = {best_bucket}
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

        drivers_pickup = []
        drivers_dropoff = []
        if therapy_candidates:
            best_th = therapy_candidates[0]
            th_s = datetime.fromisoformat(best_th["suggested_start"])
            th_e = datetime.fromisoformat(best_th["suggested_end"])
            pk_end = th_s
            pk_start = pk_end - timedelta(minutes=pk_off)
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

            buckets_needed = list({_time_bucket(pk_start.strftime("%H:%M")), _time_bucket(dp_start.strftime("%H:%M"))})
            q_drh = text("""
                  SELECT driver_id, hhmm, n FROM v_hist_driver_hour
                  WHERE hhmm = ANY(:buckets)
                """)
            drh = conn.execute(q_drh, {"buckets": buckets_needed}).mappings().all()
            dr_pref = {}
            for r in drh:
                dr_pref.setdefault(r["driver_id"], {})[r["hhmm"]] = r["n"]

            for r in dr_rows:
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

@app.get("/api/ai/recommend")
def ai_recommend():
    """Zwraca TOP propozycje (AI/heurystyka) dla klienta."""
    cid = request.args.get("client_id", type=int)
    if not cid:
        return jsonify({"error": "client_id is required"}), 400

    with engine.begin() as conn:
        q_ct = text("""
              SELECT f.therapist_id, t.full_name,
                     f.n_sessions, f.minutes_sum, f.done_ratio, f.days_since_last, f.recency_weight
              FROM v_ct_features f
              JOIN therapists t ON t.id=f.therapist_id AND t.active=true
              WHERE f.client_id=:cid
            """)
        ct_rows = [dict(r) for r in conn.execute(q_ct, {"cid": cid}).mappings().all()]

        q_cd = text("""
              SELECT f.driver_id, d.full_name,
                     f.n_runs, f.minutes_sum, f.done_ratio, f.days_since_last, f.recency_weight
              FROM v_cd_features f
              JOIN drivers d ON d.id=f.driver_id AND d.active=true
              WHERE f.client_id=:cid
            """)
        cd_rows = [dict(r) for r in conn.execute(q_cd, {"cid": cid}).mappings().all()]

        qtp = text("SELECT dow, hour, cnt FROM v_client_time_prefs WHERE client_id=:cid ORDER BY cnt DESC LIMIT 6")
        time_prefs = [dict(r) for r in conn.execute(qtp, {"cid": cid}).mappings().all()]

    if ct_model and ct_rows:
        features = ["n_sessions", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
        X_ct = pd.DataFrame(ct_rows)[features]
        scores = ct_model.predict_proba(X_ct)[:, 1]
        for r, score in zip(ct_rows, scores):
            r["score"] = round(score, 4)
    else:
        for r in ct_rows:
            r["score"] = round(_score_ct_row(r), 4)

    if cd_model and cd_rows:
        features = ["n_runs", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
        X_cd = pd.DataFrame(cd_rows)[features]
        scores = cd_model.predict_proba(X_cd)[:, 1]
        for r, score in zip(cd_rows, scores):
            r["score"] = round(score, 4)
    else:
        for r in cd_rows:
            r["score"] = round(_score_cd_row(r), 4)

    ct_rows.sort(key=lambda x: x["score"], reverse=True)
    cd_rows.sort(key=lambda x: x["score"], reverse=True)

    return jsonify({
        "therapists": ct_rows[:5],
        "drivers": cd_rows[:5],
        "time_prefs": time_prefs
    }), 200

@app.post("/api/ai/plan-day")
def ai_plan_day():
    """Prosty plan dnia (placeholder)."""
    data = request.get_json(silent=True) or {}
    date = data.get("date")
    clients = data.get("clients") or []
    if not date or not clients:
        return jsonify({"error": "date and clients[] required"}), 400

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
        hour_start += 1
    return jsonify({"date": date, "proposals": plans}), 200

@app.post("/api/parse-schedule-image")
def parse_schedule_image():
    """Parsuje obraz harmonogramu i dopasowuje skrócone nazwy do pełnych z bazy"""
    if 'schedule_image' not in request.files:
        return jsonify({"error": "Brak pliku obrazu w zapytaniu."}), 400

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

    with session_scope() as db_session:
        all_clients = [c.full_name for c in db_session.query(Client).all()]
        all_groups = [g.name for g in db_session.query(TUSGroup).all()]

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
    else: # scope == 'day'
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
    
    # UWAGA: Klucz API jest zahardkodowany, co jest złą praktyką.
    # Powinien być ładowany z GOOGLE_MAPS_API_KEY lub innej zmiennej środowiskowej
    api_key_gemini = "AIzaSyDbkt_jhBU9LNd40MAJm1GazLUPeywYo1E" # TODO: Zmień na os.getenv
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key_gemini}"
    
    try:
        response = requests.post(
            api_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=90
        )
        response.raise_for_status()
        result = response.json()
        
        if 'candidates' not in result or not result['candidates']:
            raise Exception("AI nie zwróciło wyników w 'candidates'.")

        json_text = result['candidates'][0]['content']['parts'][0]['text']
        parsed_data = json.loads(json_text)

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

        return jsonify({
            "success": True,
            "data": processed_data,
            "matched_count": len([d for d in processed_data if d['matched']]),
            "total_count": len(processed_data)
        })

    except ReadTimeout:
        return jsonify({"error": "Przetwarzanie obrazu trwało zbyt długo (timeout)."}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Błąd komunikacji z API Gemini: {e}"}), 502
    except Exception as e:
        print(f"Błąd w parse_schedule_image: {traceback.format_exc()}")
        return jsonify({"error": f"Wystąpił błąd: {str(e)}"}), 500

@app.post("/api/save-parsed-schedule")
def save_parsed_schedule():
    """Zapisuje przetworzone dane harmonogramu do bazy"""
    print("=== ENDPOINT save_parsed_schedule WYWOŁANY ===")
    try:
        data = request.get_json()
        if not isinstance(data, list):
            return jsonify({"success": False, "error": "Oczekiwano tablicy obiektów.", "saved_count": 0, "total_count": 0, "errors": []}), 400

        saved_count = 0
        errors = []
        conflicts_found = []

        with session_scope() as db_session:
            therapists = db_session.query(Therapist).all()
            clients = db_session.query(Client).all()
            groups = db_session.query(TUSGroup).all()

            therapists_map = {t.full_name.lower(): t.id for t in therapists}
            clients_map = {c.full_name.lower(): c.id for c in clients}
            groups_map = {g.name.lower(): g.id for g in groups}
            
            valid_items = []

            for i, item in enumerate(data):
                try:
                    print(f"Sprawdzanie wiersza {i + 1}: {item}")
                    required_fields = ['date', 'start_time', 'end_time', 'client_name', 'therapist_name', 'type']
                    missing_fields = [field for field in required_fields if not item.get(field)]
                    if missing_fields:
                        errors.append(f"Wiersz {i + 1}: Brak pól: {', '.join(missing_fields)}")
                        continue

                    therapist_name = item['therapist_name'].lower()
                    if therapist_name not in therapists_map:
                        errors.append(f"Wiersz {i + 1}: Nieznany terapeuta '{item['therapist_name']}'")
                        continue
                    therapist_id = therapists_map[therapist_name]

                    try:
                        starts_at = datetime.fromisoformat(f"{item['date']}T{item['start_time']}:00").replace(tzinfo=TZ)
                        ends_at = datetime.fromisoformat(f"{item['date']}T{item['end_time']}:00").replace(tzinfo=TZ)
                    except ValueError as e:
                        errors.append(f"Wiersz {i + 1}: Nieprawidłowy format daty/czasu - {e}")
                        continue

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

                    try:
                        conflicts = find_overlaps(db_session.connection(), therapist_id=therapist_id, starts_at=starts_at, ends_at=ends_at)
                        if conflicts:
                            conflict_msg = f"Wiersz {i + 1}: Konflikt czasowy {item['start_time']}-{item['end_time']} z istniejącymi zajęciami"
                            conflicts_found.append(conflict_msg)
                            errors.append(conflict_msg)
                            print(f"  → KONFLIKT: {conflict_msg}")
                            continue
                    except Exception as e:
                        print(f"Ostrzeżenie: Błąd sprawdzania konfliktów: {e}")

                    valid_items.append({
                        'index': i, 'item': item, 'therapist_id': therapist_id,
                        'starts_at': starts_at, 'ends_at': ends_at,
                        'item_type': item_type, 'client_name': client_name
                    })
                    print(f"  → Wiersz {i + 1} OK")

                except Exception as e:
                    error_msg = f"Wiersz {i + 1}: Błąd walidacji - {str(e)}"
                    errors.append(error_msg)
                    print(f"  → BŁĄD: {error_msg}")
                    continue

            print(f"Znaleziono {len(valid_items)} poprawnych wpisów do zapisania")
            
            for valid in valid_items:
                i, item, therapist_id = valid['index'], valid['item'], valid['therapist_id']
                starts_at, ends_at = valid['starts_at'], valid['ends_at']
                item_type, client_name = valid['item_type'], valid['client_name']

                try:
                    if item_type == 'tus':
                        group_id = groups_map[client_name]
                        new_session = TUSSession(
                            group_id=group_id,
                            topic_id=1,  # TODO: Domyślny temat, można poprawić
                            session_date=starts_at.date(),
                            session_time=starts_at.time()
                        )
                        db_session.add(new_session)
                        print(f"  → Zapisano sesję TUS: {item['client_name']}")
                    else:
                        client_id = clients_map[client_name]
                        new_group_id = uuid.uuid4()
                        new_event_group = EventGroup(
                            id=new_group_id,
                            client_id=client_id,
                            label=f"Import {item['date']} {item['client_name']}"
                        )
                        session_id = str(uuid.uuid4())
                        new_slot = ScheduleSlot(
                            group_id=new_group_id,
                            client_id=client_id,
                            therapist_id=therapist_id,
                            kind='therapy',
                            starts_at=starts_at,
                            ends_at=ends_at,
                            status='planned',
                            session_id=session_id
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
            "success": True, "saved_count": saved_count, "total_count": len(data),
            "errors": errors, "conflicts_count": len(conflicts_found),
            "message": f"Zapisano {saved_count} z {len(data)} wpisów. Znaleziono {len(conflicts_found)} konfliktów."
        })
    except Exception as e:
        print(f"BŁĄD KRYTYCZNY w save_parsed_schedule: {traceback.format_exc()}")
        return jsonify({"success": False, "error": f"Wewnętrzny błąd serwera: {str(e)}", "saved_count": 0, "total_count": 0, "errors": []}), 500

# --- Trasy CRUD: Clients ---

@app.get("/api/clients")
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
          FROM suo
          WHERE month_key = :mk
        )
        SELECT
          c.id AS client_id, c.full_name, c.phone, c.address, c.active,
          c.photo_url,
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

@app.post("/api/clients")
def create_client():
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    sql = """
        INSERT INTO clients (full_name, phone, address, active, photo_url)
        VALUES (:full_name, :phone, :address, COALESCE(:active,true), :photo_url)
        RETURNING id, full_name, phone, address, active, photo_url;
        """
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {
                "full_name": full_name,
                "phone": (data.get("phone") or None),
                "address": (data.get("address") or None),
                "active": bool(data.get("active", True)),
                "photo_url": data.get("photo_url")
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
                "photo_url": data.get("photo_url"),
            }).mappings().first()
            if not row:
                return jsonify({"error": "Klient nie istnieje."}), 404
            return jsonify(dict(row)), 200
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki klient już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409

@app.delete("/api/clients/<int:cid>")
def delete_client(cid):
    """Trwale usuwa klienta i wszystkie jego powiązania (kaskadowo)."""
    with engine.begin() as conn:
        res = conn.execute(text("DELETE FROM clients WHERE id=:id"), {"id": cid})
    if res.rowcount == 0:
        return jsonify({"error": "Client not found"}), 404
    return "", 204

@app.route('/api/upload/client-photo', methods=['POST'])
def upload_client_photo():
    if 'photo' not in request.files:
        return jsonify({'error': 'Brak pliku'}), 400
    file = request.files['photo']
    if not allowed_file(file.filename):
        return jsonify({'error': 'Niedozwolony format pliku'}), 400
    
    filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
    filepath = os.path.join('uploads', 'clients', filename)
    file.save(filepath)
    photo_url = f"/uploads/clients/{filename}"
    return jsonify({'photo_url': photo_url}), 200

# --- Trasy CRUD: Therapists ---

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
            # session_scope() sam robi commit
            return jsonify({"id": therapist.id, "full_name": therapist.full_name}), 200
        except IntegrityError:
            db_session.rollback()
            return jsonify({"error": "Taki terapeuta już istnieje (imię i nazwisko)."}), 409

@app.delete("/api/therapists/<int:tid>")
def delete_therapist(tid):
    """Usuwa terapeutę."""
    with session_scope() as db_session:
        therapist = db_session.query(Therapist).filter_by(id=tid).first()
        if not therapist:
            return jsonify({"error": "Therapist not found"}), 404
        db_session.delete(therapist)
        # session_scope() sam robi commit
        return "", 204

# --- Trasy CRUD: Drivers ---

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

        drivers = q.order_by(Driver.full_name).all()
        out = [{
            "id": d.id,
            "full_name": d.full_name,
            "phone": getattr(d, "phone", None),
            "active": getattr(d, "active", True),
        } for d in drivers]
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
            db_session.flush() # Aby uzyskać ID
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
            # session_scope() robi commit
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
        return "", 204

# --- Trasy: Harmonogramy (Schedule, Slots, Groups) ---

@app.post("/api/schedule/group")
def create_group_with_slots():
    """Tworzy pakiet (grupę) i powiązane sloty (terapia, pickup, dropoff)."""
    data = request.get_json(silent=True) or {}
    gid = uuid.uuid4()
    status = data.get("status", "planned")

    print(f"\n{'=' * 80}\n🔥 TWORZENIE NOWEGO PAKIETU: {gid}\n{'=' * 80}")
    print(f"Klient: {data.get('client_id')}, Status: {status}")
    print(f"Klucz Google Maps: {'✓ USTAWIONY' if GOOGLE_MAPS_API_KEY else '✗ BRAK'}")

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
                "group_id": str(gid), "client_id": data["client_id"],
                "therapist_id": t["therapist_id"], "starts_at": ts, "ends_at": te,
                "place": t.get("place"), "status": status, "session_id": session_id
            }).scalar_one()

            # 3) Utwórz wpis o obecności
            if therapy_slot_id:
                conn.execute(text("""
                            INSERT INTO individual_session_attendance (slot_id, status)
                            VALUES (:slot_id, 'obecny')
                        """), {"slot_id": therapy_slot_id})

            # 4) Funkcja pomocnicza do tworzenia kursów
            def insert_run(run_data, kind):
                if not run_data:
                    print(f"⚠️  Brak danych dla {kind}")
                    return
                
                print(f"\n--- Przetwarzam {kind.upper()} ---")
                s = datetime.fromisoformat(run_data["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(run_data["ends_at"]).replace(tzinfo=TZ)
                run_id = ensure_shared_run_id_for_driver(conn, int(run_data["driver_id"]), s, e)
                
                place_from = run_data.get("from")
                place_to = run_data.get("to")
                distance = None
                if place_from and place_to:
                    print(f"🔍 Obliczam dystans: '{place_from}' -> '{place_to}'")
                    distance = get_route_distance(place_from, place_to)
                    print(f"{'✓' if distance else '✗'} Dystans: {distance} km")
                else:
                    print(f"⚠️  Brak adresów - pomijam obliczanie dystansu")

                result = conn.execute(text("""
                            INSERT INTO schedule_slots (
                                group_id, client_id, driver_id, vehicle_id, kind, 
                                starts_at, ends_at, place_from, place_to, status, run_id,
                                distance_km
                            ) VALUES (
                                :group_id, :client_id, :driver_id, :vehicle_id, :kind, 
                                :starts_at, :ends_at, :from, :to, :status, :run_id, :distance
                            ) RETURNING id
                        """), {
                    "group_id": str(gid), "client_id": data["client_id"],
                    "driver_id": run_data["driver_id"], "vehicle_id": run_data.get("vehicle_id"),
                    "kind": kind, "starts_at": s, "ends_at": e,
                    "from": place_from, "to": place_to, "status": status,
                    "run_id": run_id, "distance": distance
                })
                new_id = result.scalar_one()
                print(f"✓ Slot {kind} utworzony (ID: {new_id}, dystans: {distance} km)")

            insert_run(data.get("pickup"), "pickup")
            insert_run(data.get("dropoff"), "dropoff")

            print(f"\n✅ PAKIET UTWORZONY: {gid}\n{'=' * 80}\n")
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
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/groups/<group_id>', methods=['GET'])
def get_package_group(group_id):
    """Pobiera pakiet na podstawie UUID group_id (wersja psycopg2)"""
    conn = None
    cur = None
    try:
        # TODO: Zrefaktoryzować do użycia engine i session_scope
        conn = psycopg2.connect(DATABASE_URL.replace("postgresql+psycopg2", "postgresql"))
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
                SELECT 
                    id as slot_id, group_id::text as group_id, client_id, kind,
                    therapist_id, driver_id, vehicle_id, starts_at, ends_at,
                    place_from, place_to, status, distance_km
                FROM schedule_slots
                WHERE group_id = %s::uuid
                ORDER BY CASE kind 
                    WHEN 'pickup' THEN 1
                    WHEN 'therapy' THEN 2
                    WHEN 'dropoff' THEN 3
                    ELSE 4
                END
            """, (group_id,))
        slots = cur.fetchall()

        if not slots:
            return jsonify({"error": "Pakiet nie znaleziony"}), 404

        first = slots[0]
        result = {
            "group_id": first["group_id"],
            "client_id": first["client_id"],
            "status": first["status"],
            "label": None
        }

        for slot in slots:
            if slot["kind"] == "therapy":
                result["therapy"] = {
                    "slot_id": slot["slot_id"], "therapist_id": slot["therapist_id"],
                    "starts_at": slot["starts_at"].isoformat() if slot["starts_at"] else None,
                    "ends_at": slot["ends_at"].isoformat() if slot["ends_at"] else None,
                    "place": slot["place_to"], "status": slot["status"]
                }
            elif slot["kind"] == "pickup":
                result["pickup"] = {
                    "slot_id": slot["slot_id"], "driver_id": slot["driver_id"],
                    "vehicle_id": slot["vehicle_id"],
                    "starts_at": slot["starts_at"].isoformat() if slot["starts_at"] else None,
                    "ends_at": slot["ends_at"].isoformat() if slot["ends_at"] else None,
                    "from": slot["place_from"], "to": slot["place_to"], "status": slot["status"]
                }
            elif slot["kind"] == "dropoff":
                result["dropoff"] = {
                    "slot_id": slot["slot_id"], "driver_id": slot["driver_id"],
                    "vehicle_id": slot["vehicle_id"],
                    "starts_at": slot["starts_at"].isoformat() if slot["starts_at"] else None,
                    "ends_at": slot["ends_at"].isoformat() if slot["ends_at"] else None,
                    "from": slot["place_from"], "to": slot["place_to"], "status": slot["status"]
                }
        return jsonify(result)
    except Exception as e:
        print(f"BŁĄD w get_package_group: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

@app.put("/api/groups/<string:gid>")
def update_group(gid):
    """Aktualizuje pakiet (grupę) i powiązane sloty."""
    data = request.get_json(silent=True) or {}
    label = data.get("label")
    status = data.get("status", "planned")
    therapy = data.get("therapy")
    pickup = data.get("pickup")
    dropoff = data.get("dropoff")

    if not all(k in (therapy or {}) for k in ["therapist_id", "starts_at", "ends_at"]):
        return jsonify({"error": "Brak kompletnych danych terapii (terapeuta, start, koniec)."}), 400

    try:
        with engine.begin() as conn:
            ok = conn.execute(text("SELECT 1 FROM event_groups WHERE id=:gid"), {"gid": gid}).scalar()
            if not ok: return jsonify({"error": "Nie znaleziono grupy."}), 404

            conn.execute(text("UPDATE event_groups SET label=:label WHERE id=:gid"), {"label": label, "gid": gid})

            ts = datetime.fromisoformat(therapy["starts_at"]).replace(tzinfo=TZ)
            te = datetime.fromisoformat(therapy["ends_at"]).replace(tzinfo=TZ)
            session_id = ensure_shared_session_id_for_therapist(conn, int(therapy["therapist_id"]), ts, te)

            ex = conn.execute(text("SELECT id FROM schedule_slots WHERE group_id=:gid AND kind='therapy' LIMIT 1"), {"gid": gid}).mappings().first()
            if ex:
                conn.execute(text("""
                        UPDATE schedule_slots SET therapist_id=:tid, starts_at=:s, ends_at=:e, place_to=:place, status=:status, session_id=:sid WHERE id=:id
                    """), {"tid": therapy["therapist_id"], "s": ts, "e": te, "place": therapy.get("place"), "status": status, "sid": session_id, "id": ex["id"]})
            else:
                conn.execute(text("""
                        INSERT INTO schedule_slots (group_id, client_id, therapist_id, kind, starts_at, ends_at, place_to, status, session_id)
                        SELECT :gid, client_id, :tid, 'therapy', :s, :e, :place, :status, :sid FROM schedule_slots WHERE group_id=:gid LIMIT 1
                    """), {"gid": gid, "tid": therapy["therapist_id"], "s": ts, "e": te, "place": therapy.get("place"), "status": status, "sid": session_id})

            def upsert_run(kind, block):
                ex = conn.execute(text("SELECT id FROM schedule_slots WHERE group_id=:gid AND kind=:kind LIMIT 1"), {"gid": gid, "kind": kind}).mappings().first()
                if block is None:
                    if ex: conn.execute(text("DELETE FROM schedule_slots WHERE id=:id"), {"id": ex["id"]})
                    return

                distance = get_route_distance(block.get("from"), block.get("to"))
                s = datetime.fromisoformat(block["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(block["ends_at"]).replace(tzinfo=TZ)
                payload = {
                    "did": block["driver_id"], "veh": block.get("vehicle_id"), "s": s, "e": e,
                    "from": block.get("from"), "to": block.get("to"), "status": status,
                    "gid": gid, "kind": kind, "distance": distance
                }

                if ex:
                    conn.execute(text("""
                            UPDATE schedule_slots 
                            SET driver_id=:did, vehicle_id=:veh, starts_at=:s, ends_at=:e, 
                                place_from=:from, place_to=:to, status=:status, distance_km=:distance
                            WHERE id=:id
                        """), {**payload, "id": ex["id"]})
                else:
                    conn.execute(text("""
                            INSERT INTO schedule_slots 
                            (group_id, client_id, driver_id, vehicle_id, kind, starts_at, ends_at, 
                             place_from, place_to, status, distance_km)
                            SELECT :gid, client_id, :did, :veh, :kind, :s, :e, 
                                   :from, :to, :status, :distance 
                            FROM schedule_slots WHERE group_id=:gid AND kind='therapy' LIMIT 1
                        """), payload)

            upsert_run("pickup", pickup)
            upsert_run("dropoff", dropoff)

        return jsonify({"ok": True, "group_id": gid}), 200
    except IntegrityError as e:
        if getattr(e.orig, "pgcode", None) == errorcodes.FOREIGN_KEY_VIOLATION:
            return jsonify({"error": "Naruszenie klucza obcego – sprawdź ID osób/pojazdu."}), 400
        return jsonify({"error": "Błąd bazy", "details": str(e.orig)}), 400

@app.delete("/api/groups/<string:gid>")
def delete_group(gid):
    """Usuwa cały pakiet indywidualny (rekord z event_groups i kaskadowo sloty)."""
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM event_groups WHERE id = CAST(:gid AS UUID)"), {"gid": gid})
    if result.rowcount == 0:
        return jsonify({"error": "Pakiet nie został znaleziony lub już został usunięty."}), 404
    return jsonify({"message": "Pakiet został pomyślnie usunięty."}), 200

@app.patch("/api/slots/<int:sid>")
def update_slot(sid):
    """Aktualizuje pojedynczy slot (np. status, czas)."""
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
    
    valid_statuses = ['planned', 'confirmed', 'done', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({"error": f"Nieprawidłowy status. Dozwolone: {', '.join(valid_statuses)}"}), 400

    try:
        with engine.begin() as conn:
            slot_exists = conn.execute(text("SELECT id FROM schedule_slots WHERE id = :id"), {"id": slot_id}).scalar()
            if not slot_exists:
                return jsonify({"error": "Slot nie znaleziony"}), 404
            
            conn.execute(text("UPDATE schedule_slots SET status = :status WHERE id = :id"), {"status": new_status, "id": slot_id})
            return jsonify({"status": "ok", "slot_id": slot_id, "new_status": new_status, "message": "Status zaktualizowany"})
    except Exception as e:
        print(f"BŁĄD w update_slot_status: {e}")
        return jsonify({"error": f"Wewnętrzny błąd serwera: {str(e)}"}), 500

@app.route('/api/schedule/check-conflicts', methods=['POST'])
def check_schedule_conflicts():
    """Sprawdza kolizje dla edytowanego pakietu (wersja psycopg2)"""
    data = request.get_json()
    group_id = data.get('group_id')
    client_id = data.get('client_id')
    therapy = data.get('therapy')
    pickup = data.get('pickup')
    dropoff = data.get('dropoff')

    conn = None
    cur = None
    conflicts = {"therapy": [], "pickup": [], "dropoff": [], "client": [], "total": 0}

    try:
        # TODO: Zrefaktoryzować do użycia engine i session_scope
        conn = psycopg2.connect(DATABASE_URL.replace("postgresql+psycopg2", "postgresql"))
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if therapy:
            therapist_id, starts_at, ends_at = therapy.get('therapist_id'), therapy.get('starts_at'), therapy.get('ends_at')
            cur.execute("""
                    SELECT ss.id, ss.group_id::text, c.full_name as client_name, ss.starts_at, ss.ends_at, 'Terapeuta już zajęty' as reason
                    FROM schedule_slots ss
                    JOIN clients c ON ss.client_id = c.id
                    WHERE ss.therapist_id = %s AND ss.status NOT IN ('cancelled')
                    AND ((ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz))
                    AND (%s IS NULL OR ss.group_id::text != %s)
                """, (therapist_id, starts_at, ends_at, group_id, group_id))
            conflicts["therapy"] = [dict(row) for row in cur.fetchall()]

        if pickup:
            driver_id, starts_at, ends_at = pickup.get('driver_id'), pickup.get('starts_at'), pickup.get('ends_at')
            if driver_id:
                cur.execute("""
                        SELECT ss.id, ss.group_id::text, c.full_name as client_name, ss.starts_at, ss.ends_at, ss.kind, 'Kierowca już zajęty' as reason
                        FROM schedule_slots ss
                        JOIN clients c ON ss.client_id = c.id
                        WHERE ss.driver_id = %s AND ss.kind IN ('pickup', 'dropoff') AND ss.status NOT IN ('cancelled')
                        AND ((ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz))
                        AND (%s IS NULL OR ss.group_id::text != %s)
                    """, (driver_id, starts_at, ends_at, group_id, group_id))
                conflicts["pickup"] = [dict(row) for row in cur.fetchall()]

        if dropoff:
            driver_id, starts_at, ends_at = dropoff.get('driver_id'), dropoff.get('starts_at'), dropoff.get('ends_at')
            if driver_id:
                cur.execute("""
                        SELECT ss.id, ss.group_id::text, c.full_name as client_name, ss.starts_at, ss.ends_at, ss.kind, 'Kierowca już zajęty' as reason
                        FROM schedule_slots ss
                        JOIN clients c ON ss.client_id = c.id
                        WHERE ss.driver_id = %s AND ss.kind IN ('pickup', 'dropoff') AND ss.status NOT IN ('cancelled')
                        AND ((ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz))
                        AND (%s IS NULL OR ss.group_id::text != %s)
                    """, (driver_id, starts_at, ends_at, group_id, group_id))
                conflicts["dropoff"] = [dict(row) for row in cur.fetchall()]

        if client_id and therapy:
            starts_at, ends_at = therapy.get('starts_at'), therapy.get('ends_at')
            cur.execute("""
                    SELECT ss.id, ss.group_id::text, ss.kind, ss.starts_at, ss.ends_at, t.full_name as therapist_name, 'Klient ma już inne zajęcia' as reason
                    FROM schedule_slots ss
                    LEFT JOIN therapists t ON ss.therapist_id = t.id
                    WHERE ss.client_id = %s AND ss.status NOT IN ('cancelled')
                    AND ((ss.starts_at, ss.ends_at) OVERLAPS (%s::timestamptz, %s::timestamptz))
                    AND (%s IS NULL OR ss.group_id::text != %s)
                """, (client_id, starts_at, ends_at, group_id, group_id))
            conflicts["client"] = [dict(row) for row in cur.fetchall()]

        conflicts["total"] = len(conflicts["therapy"]) + len(conflicts["pickup"]) + len(conflicts["dropoff"]) + len(conflicts["client"])
        return jsonify(conflicts)
    except Exception as e:
        print(f"BŁĄD w check_schedule_conflicts: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

@app.route('/api/schedule/<int:slot_id>', methods=['DELETE'])
def delete_schedule_slot(slot_id):
    """Usuwa pojedynczą sesję (slot)"""
    try:
        with engine.begin() as conn:
            slot = conn.execute(text('SELECT id FROM schedule_slots WHERE id = :id'), {"id": slot_id}).scalar()
            if not slot:
                return jsonify({'error': 'Sesja nie znaleziona'}), 404
            
            conn.execute(text('DELETE FROM schedule_slots WHERE id = :id'), {"id": slot_id})
            return jsonify({'message': 'Sesja usunięta pomyślnie'}), 200
    except Exception as e:
        print(f"Błąd usuwania sesji: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/schedule/<int:slot_id>', methods=['PUT'])
def update_schedule_slot(slot_id):
    """Aktualizuje sesję (wersja ORM/engine)"""
    data = request.get_json()
    try:
        with engine.begin() as conn:
            slot = conn.execute(text('SELECT id FROM schedule_slots WHERE id = :id'), {"id": slot_id}).scalar()
            if not slot:
                return jsonify({'error': 'Sesja nie znaleziona'}), 404

            update_fields = []
            params = {"id": slot_id}
            if 'label' in data:
                # Uwaga: 'label' jest w 'event_groups', nie 'schedule_slots'
                # To zapytanie powinno prawdopodobnie aktualizować event_groups
                # Na razie pomijam, bo logika jest niejasna
                pass
            if 'starts_at' in data:
                update_fields.append("starts_at = :starts_at")
                params["starts_at"] = data['starts_at']
            if 'ends_at' in data:
                update_fields.append("ends_at = :ends_at")
                params["ends_at"] = data['ends_at']
            if 'place_to' in data:
                update_fields.append("place_to = :place_to")
                params["place_to"] = data['place_to']

            if not update_fields:
                return jsonify({'error': 'Brak danych do aktualizacji'}), 400

            set_clause = ", ".join(update_fields)
            conn.execute(text(f'UPDATE schedule_slots SET {set_clause} WHERE id = :id'), params)
            return jsonify({'message': 'Sesja zaktualizowana'}), 200
    except Exception as e:
        print(f"Błąd aktualizacji sesji: {e}")
        return jsonify({'error': str(e)}), 500

# --- Trasy: Widoki harmonogramów (Klient, Terapeuta, Kierowca) ---

@app.get("/api/client/<int:cid>/packages")
def client_packages(cid):
    """Pobiera pakiety indywidualne i TUS dla klienta."""
    mk = request.args.get("month")
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

@app.get("/api/therapists/<int:tid>/schedule")
def therapist_schedule(tid):
    """Pobiera harmonogram indywidualny i TUS dla terapeuty."""
    mk = request.args.get("month")
    if not mk:
        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

    all_results = []
    with engine.begin() as conn:
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

    for r in all_results:
        row_dict = dict(r)
        if starts_at := row_dict.get('starts_at'):
            if starts_at.tzinfo is None:
                row_dict['starts_at'] = starts_at.replace(tzinfo=TZ)
    
    all_results.sort(key=lambda r: r.get('starts_at') or datetime.max.replace(tzinfo=ZoneInfo("UTC")))

    results = []
    for r in all_results:
        row_dict = dict(r)
        if starts_at_aware := row_dict.get('starts_at'):
            row_dict['starts_at'] = starts_at_aware.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
        if ends_at_aware := row_dict.get('ends_at'):
            row_dict['ends_at'] = ends_at_aware.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
        results.append(row_dict)

    return jsonify(results)

@app.route('/api/drivers/<int:driver_id>/schedule', methods=['GET'])
def get_driver_schedule(driver_id):
    """Harmonogram tras kierowcy na dany dzień - WERSJA Z GPS (psycopg2)"""
    date = request.args.get('date')
    if not date:
        return jsonify({"error": "Date parameter is required"}), 400

    conn = None
    cur = None
    try:
        # TODO: Zrefaktoryzować do użycia engine i session_scope
        conn = psycopg2.connect(DATABASE_URL.replace("postgresql+psycopg2", "postgresql"))
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
                SELECT 
                    ss.id as slot_id, ss.group_id::text as group_id, ss.driver_id,
                    ss.client_id, c.full_name as client_name,
                    ss.starts_at, ss.ends_at, ss.kind, ss.status,
                    ss.place_from, ss.place_to, ss.distance_km, ss.vehicle_id
                FROM schedule_slots ss
                LEFT JOIN clients c ON ss.client_id = c.id
                WHERE ss.driver_id = %s
                AND ss.kind IN ('pickup', 'dropoff')
                AND DATE(ss.starts_at AT TIME ZONE 'Europe/Warsaw') = %s
                ORDER BY ss.starts_at
            """, (driver_id, date))
        routes = [dict(row) for row in cur.fetchall()]

        for route in routes:
            if route.get('distance_km'):
                route['distance_km'] = float(route['distance_km'])
            if route.get('starts_at'):
                route['starts_at'] = route['starts_at'].isoformat()
            if route.get('ends_at'):
                route['ends_at'] = route['ends_at'].isoformat()

        return jsonify(routes)
    except Exception as e:
        print(f"Błąd w get_driver_schedule: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- Trasy: Luki (Gaps) ---

@app.get("/api/gaps/day")
def gaps_day():
    """Zwraca listy aktywnych osób bez slotu w danym dniu."""
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
          LEFT JOIN schedule_slots ss ON ss.client_id = c.id AND (ss.starts_at AT TIME ZONE 'Europe/Warsaw')::date = :d
          WHERE c.active = true AND ss.id IS NULL
          ORDER BY c.full_name;
        """
    sql_therapists = """
          SELECT t.id, t.full_name
          FROM therapists t
          LEFT JOIN schedule_slots ss ON ss.therapist_id = t.id AND ss.kind = 'therapy' AND (ss.starts_at AT TIME ZONE 'Europe/Warsaw')::date = :d
          WHERE t.active = true AND ss.id IS NULL
          ORDER BY t.full_name;
        """
    sql_drivers = """
          SELECT d.id, d.full_name
          FROM drivers d
          LEFT JOIN schedule_slots ss ON ss.driver_id = d.id AND ss.kind IN ('pickup','dropoff') AND (ss.starts_at AT TIME ZONE 'Europe/Warsaw')::date = :d
          WHERE d.active = true AND ss.id IS NULL
          ORDER BY d.full_name;
        """

    with engine.begin() as conn:
        clients = [dict(r) for r in conn.execute(text(sql_clients), {"d": d}).mappings().all()]
        therapists = [dict(r) for r in conn.execute(text(sql_therapists), {"d": d}).mappings().all()]
        drivers = [dict(r) for r in conn.execute(text(sql_drivers), {"d": d}).mappings().all()]

    return jsonify({
        "date": d.isoformat(),
        "clients": clients, "therapists": therapists, "drivers": drivers,
        "counts": {"clients": len(clients), "therapists": len(therapists), "drivers": len(drivers)}
    }), 200

@app.get("/api/gaps/month")
def gaps_month():
    """Zwraca aktywne osoby bez slotu w danym miesiącu."""
    mk = (request.args.get("month") or "").strip()
    if not mk:
        mk = datetime.now(TZ).strftime("%Y-%m")

    sql_clients = """
          SELECT c.id, c.full_name FROM clients c
          WHERE c.active = true AND NOT EXISTS (
              SELECT 1 FROM schedule_slots ss WHERE ss.client_id = c.id
                AND ss.starts_at IS NOT NULL AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            ) ORDER BY c.full_name;
        """
    sql_therapists = """
          SELECT t.id, t.full_name FROM therapists t
          WHERE t.active = true AND NOT EXISTS (
              SELECT 1 FROM schedule_slots ss WHERE ss.therapist_id = t.id AND ss.kind = 'therapy'
                AND ss.starts_at IS NOT NULL AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            ) ORDER BY t.full_name;
        """
    sql_drivers = """
          SELECT d.id, d.full_name FROM drivers d
          WHERE d.active = true AND NOT EXISTS (
              SELECT 1 FROM schedule_slots ss WHERE ss.driver_id = d.id AND ss.kind IN ('pickup','dropoff')
                AND ss.starts_at IS NOT NULL AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk
            ) ORDER BY d.full_name;
        """
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

    absences_map = {}
    for ab in absences_rows:
        absences_map[(ab['person_type'], ab['person_id'])] = ab['status']

    for t in therapists:
        if ('therapist', t['id']) in absences_map:
            t['absence_status'] = absences_map[('therapist', t['id'])]
    for d in drivers:
        if ('driver', d['id']) in absences_map:
            d['absence_status'] = absences_map[('driver', d['id'])]

    return jsonify({
        "month": mk,
        "clients": clients, "therapists": therapists, "drivers": drivers,
        "counts": {"clients": len(clients), "therapists": len(therapists), "drivers": len(drivers)}
    }), 200

# --- Trasy: TUS (Grupy, Sesje, Punkty) ---

@app.get("/api/tus/groups")
def get_tus_groups():
    with session_scope() as db_session:
        groups = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.therapist),
            joinedload(TUSGroup.members),
            joinedload(TUSGroup.sessions)
        ).order_by(TUSGroup.name).all()
        result = [{
            "id": group.id, "name": group.name,
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
            members=members
        )
        db_session.add(new_group)
        db_session.flush()
        return jsonify({"id": new_group.id, "name": new_group.name}), 201

@app.get("/api/tus/groups/<int:group_id>")
def get_tus_group_details(group_id: int):
    with session_scope() as db_session:
        group = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.therapist),
            joinedload(TUSGroup.assistant_therapist),
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client),
            selectinload(TUSGroup.sessions).joinedload(TUSSession.topic)
        ).filter(TUSGroup.id == group_id).first()

        if not group:
            return jsonify({"error": "Group not found"}), 404

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
            "id": group.id, "name": group.name,
            "therapist_id": group.therapist_id,
            "therapist_name": group.therapist.full_name if group.therapist else "Brak",
            "assistant_therapist_id": group.assistant_therapist_id,
            "assistant_therapist_name": group.assistant_therapist.full_name if group.assistant_therapist else None,
            "members": members_json,
            "sessions": sessions_json,
            "schedule_days": [d.isoformat() for d in group.schedule_days] if group.schedule_days else []
        }
        return jsonify(group_data)

@app.put("/api/tus/groups/<int:group_id>")
def update_tus_group(group_id):
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("therapist_id"):
        return jsonify({"error": "Nazwa grupy i terapeuta są wymagani."}), 400

    with session_scope() as db_session:
        group = db_session.get(TUSGroup, group_id)
        if not group:
            return jsonify({"error": "Nie znaleziono grupy."}), 404
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
        
        group.schedule_days = sorted([date.fromisoformat(d) for d in set(schedule_days_str)])
        return jsonify({"ok": True})

@app.get("/api/tus/groups-summary")
def get_tus_groups_summary():
    """Zwraca podsumowanie dla kart grup, bazując na bieżącym roku szkolnym."""
    with SessionLocal() as session:
        now = datetime.now(TZ).date()
        current_school_year_start = now.year if now.month >= 9 else now.year - 1
        current_semester = 1 if now.month >= 9 or now.month <= 1 else 2
        start_date, end_date = get_semester_dates(current_school_year_start, current_semester)

        session_bonuses_subq = select(TUSSession.group_id, func.sum(TUSMemberBonus.points).label("total_s")).join(TUSSession).where(TUSSession.session_date.between(start_date, end_date)).group_by(TUSSession.group_id).subquery()
        general_bonuses_subq = select(TUSGeneralBonus.group_id, func.sum(TUSGeneralBonus.points).label("total_g")).where(TUSGeneralBonus.awarded_at.between(start_date, end_date)).group_by(TUSGeneralBonus.group_id).subquery()
        last_session_subq = select(TUSSession.group_id, func.max(TUSSession.session_date).label("max_date")).group_by(TUSSession.group_id).subquery()
        targets_subq = select(TUSGroupTarget).where(TUSGroupTarget.school_year_start == current_school_year_start, TUSGroupTarget.semester == current_semester).subquery()

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
            .outerjoin(TUSSession, (TUSGroup.id == TUSSession.group_id) & (TUSSession.session_date == last_session_subq.c.max_date))
            .outerjoin(TUSTopic, TUSSession.topic_id == TUSTopic.id)
            .options(joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client), joinedload(TUSGroup.therapist))
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
            target_obj = db_session.query(TUSGroupTarget).filter_by(group_id=gid, school_year_start=school_year_start, semester=semester).first()
            session_bonus_q = select(func.sum(TUSMemberBonus.points)).join(TUSSession).where(TUSSession.group_id == gid, TUSSession.session_date.between(start_date, end_date))
            general_bonus_q = select(func.sum(TUSGeneralBonus.points)).where(TUSGeneralBonus.group_id == gid, TUSGeneralBonus.awarded_at.between(start_date, end_date))
            session_pts = db_session.execute(session_bonus_q).scalar() or 0
            general_pts = db_session.execute(general_bonus_q).scalar() or 0
            total_collected = int(session_pts) + int(general_pts)

            results[f"semester_{semester}"] = {
                "target_points": target_obj.target_points if target_obj else 0,
                "reward": target_obj.reward if target_obj else "Brak",
                "points_collected": total_collected,
                "points_remaining": max(0, (target_obj.target_points if target_obj else 0) - total_collected)
            }
    return jsonify({"school_year_start": school_year_start, "school_year_label": f"{school_year_start}/{school_year_start + 1}", **results})

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
            group_id=gid, school_year_start=school_year_start, semester=semester
        ).first()
        if target:
            target.target_points = points
            target.reward = reward
        else:
            target = TUSGroupTarget(
                group_id=gid,
                school_year_start=school_year_start,
                semester=semester,
                target_points=points,
                reward=reward
            )
            db_session.add(target)
    return jsonify({"ok": True})

@app.get("/api/tus/groups/<int:group_id>/topic-history")
def get_group_topic_history(group_id: int):
    with SessionLocal() as session:
        current_member_ids = session.execute(
            select(TUSGroupMember.client_id).where(TUSGroupMember.group_id == group_id)
        ).scalars().all()
        if not current_member_ids:
            return jsonify({})

        history_query = (
            select(
                TUSGroupMember.client_id, Client.full_name, TUSTopic.title,
                TUSSession.session_date, TUSGroup.name
            ).distinct()
            .join(Client, Client.id == TUSGroupMember.client_id)
            .join(TUSGroup, TUSGroup.id == TUSGroupMember.group_id)
            .join(TUSSession, TUSSession.group_id == TUSGroup.id)
            .join(TUSTopic, TUSTopic.id == TUSSession.topic_id)
            .where(TUSGroupMember.client_id.in_(current_member_ids))
            .order_by(Client.full_name, TUSSession.session_date.desc())
        )
        history_results = session.execute(history_query).all()

        history_by_client = {}
        for row in history_results:
            client_id, client_name, topic_title, session_date, group_name = row
            if client_id not in history_by_client:
                history_by_client[client_id] = {"client_name": client_name, "history": []}
            history_by_client[client_id]["history"].append({
                "topic": topic_title,
                "date": session_date.isoformat(),
                "group_name": group_name
            })
        return jsonify(history_by_client)

@app.get("/api/tus/groups/<int:group_id>/bonus-details")
def get_bonus_details(group_id: int):
    with session_scope() as db_session:
        group = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client)
        ).filter(TUSGroup.id == group_id).first()
        if not group:
            return jsonify({"error": "Group not found"}), 404

        member_ids = [member.id for member in group.members]
        if not member_ids:
            return jsonify([])

        behavior_scores_sq = db_session.query(TUSSessionMemberScore.client_id, func.sum(TUSSessionMemberScore.points).label("total_behavior")).join(TUSSession, TUSSession.id == TUSSessionMemberScore.session_id).filter(TUSSession.group_id == group_id).group_by(TUSSessionMemberScore.client_id).subquery()
        session_bonuses_sq = db_session.query(TUSMemberBonus.client_id, func.sum(TUSMemberBonus.points).label("total_session_bonus")).join(TUSSession, TUSSession.id == TUSMemberBonus.session_id).filter(TUSSession.group_id == group_id).group_by(TUSMemberBonus.client_id).subquery()
        general_bonuses_sq = db_session.query(TUSGeneralBonus.client_id, func.sum(TUSGeneralBonus.points).label("total_general_bonus")).filter(TUSGeneralBonus.group_id == group_id).group_by(TUSGeneralBonus.client_id).subquery()

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
            total_points = int(behavior_pts) + int(session_pts) + int(general_pts)
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
        if points <= 0: raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"error": "Points must be a positive integer"}), 400
    
    points *= 10 # Mnożymy przyznane punkty razy 10
    
    with session_scope() as db_session:
        is_member = db_session.query(TUSGroupMember).filter_by(group_id=group_id, client_id=client_id).first()
        if not is_member:
            return jsonify({"error": "Client is not a member of this group"}), 403
        
        new_bonus = TUSGeneralBonus(
            client_id=client_id, group_id=group_id,
            points=points, reason=reason
        )
        db_session.add(new_bonus)
    return jsonify({"ok": True}), 201

@app.get("/api/tus/groups/<int:group_id>/general-bonus-history")
def get_general_bonus_history(group_id: int):
    """Zwraca historię przyznanych bonusów ogólnych dla grupy."""
    with session_scope() as db_session:
        history = db_session.query(
            TUSGeneralBonus.awarded_at, TUSGeneralBonus.points,
            TUSGeneralBonus.reason, Client.full_name
        ).join(Client, Client.id == TUSGeneralBonus.client_id) \
         .filter(TUSGeneralBonus.group_id == group_id) \
         .order_by(TUSGeneralBonus.awarded_at.desc()).all()
        
        results = [{
            "awarded_at": h.awarded_at.isoformat(),
            "points": h.points, "reason": h.reason,
            "client_name": h.full_name
        } for h in history]
        return jsonify(results)

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
            db_session.flush()
            result = {"id": new_topic.id, "title": new_topic.title}
            return jsonify(result), 201
        except IntegrityError:
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

@app.get("/api/tus/schedule")
def get_tus_schedule():
    """Zwraca wszystkie sesje TUS w danym miesiącu wraz z uczestnikami."""
    month_key = request.args.get("month")
    if not month_key:
        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

    sql = text("""
            SELECT
                s.id AS session_id, s.session_date, s.session_time,
                g.id AS group_id, g.name AS group_name,
                COALESCE(t.title, 'Brak tematu') AS topic_title,
                COALESCE(th.full_name, 'Brak terapeuty') AS therapist_name,
                (SELECT json_agg(json_build_object('id', c.id, 'name', c.full_name))
                 FROM tus_group_members gm
                 JOIN clients c ON c.id = gm.client_id
                 WHERE gm.group_id = g.id) AS members
            FROM tus_sessions s
            JOIN tus_groups g ON s.group_id = g.id
            LEFT JOIN tus_topics t ON s.topic_id = t.id
            LEFT JOIN therapists th ON g.therapist_id = th.id
            WHERE to_char(s.session_date, 'YYYY-MM') = :month
            ORDER BY s.session_date, s.session_time;
        """)
    with engine.begin() as conn:
        rows = conn.execute(sql, {"month": month_key}).mappings().all()
        results = [{
             **row,
             'session_date': row['session_date'].isoformat(),
             'session_time': row['session_time'].strftime('%H:%M:%S') if row['session_time'] else None
        } for row in rows]
        return jsonify(results)

@app.post("/api/tus/sessions")
def create_tus_session():
    data = request.get_json(silent=True) or {}
    print(f"=== ROZPOCZĘCIE TWORZENIA SESJI (NOWA LOGIKA TEMATU) ===")
    print(f"Otrzymane dane: {data}")

    try:
        group_id = int(data["group_id"])
        topic_title = (data.get("topic_title") or "").strip()
        if not topic_title:
            return jsonify({"error": "Pole 'topic_title' jest wymagane."}), 400
        
        session_date_str = data["session_date"]
        try:
            dt_obj = datetime.fromisoformat(session_date_str)
            sess_date = dt_obj.date()
            sess_time = dt_obj.time()
        except (ValueError, TypeError):
            return jsonify({"error": f"Nieprawidłowy format daty/godziny: {session_date_str}"}), 400

        behavior_ids = [int(bid) for bid in data.get("behavior_ids", []) if bid]
        if len(behavior_ids) > 4:
            return jsonify({"error": "Można wybrać maksymalnie 4 zachowania."}), 400

        with session_scope() as db_session:
            topic = db_session.query(TUSTopic).filter(func.lower(TUSTopic.title) == func.lower(topic_title)).first()
            if not topic:
                print(f"Temat '{topic_title}' nie istnieje. Tworzę nowy wpis.")
                topic = TUSTopic(title=topic_title)
                db_session.add(topic)
                db_session.flush()
            else:
                print(f"Znaleziono istniejący temat: ID={topic.id}, Tytuł='{topic.title}'")

            topic_id_for_session = topic.id
            new_session = TUSSession(
                group_id=group_id,
                topic_id=topic_id_for_session,
                session_date=sess_date,
                session_time=sess_time,
            )
            db_session.add(new_session)
            db_session.flush()

            if behavior_ids:
                behaviors_map = {b.id: b.default_max_points for b in db_session.query(TUSBehavior).filter(TUSBehavior.id.in_(behavior_ids)).all()}
                for b_id in behavior_ids:
                    session_behavior = TUSSessionBehavior(
                        session_id=new_session.id,
                        behavior_id=b_id,
                        max_points=behaviors_map.get(b_id, 3)
                    )
                    db_session.add(session_behavior)
            
            print(f"UTWORZONO SESJĘ: ID={new_session.id}, Data={new_session.session_date}, Czas={new_session.session_time}, TopicID={topic_id_for_session}")
            return jsonify({"id": new_session.id}), 201

    except (KeyError, ValueError, TypeError) as e:
        print(f"BŁĄD: Nieprawidłowe lub brakujące dane w zapytaniu. Szczegóły: {str(e)}")
        return jsonify({"error": "Nieprawidłowe lub brakujące dane w zapytaniu.", "details": str(e)}), 400
    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": "Wewnętrzny błąd serwera."}), 500

@app.get("/api/tus/sessions/<int:session_id>")
def get_tus_session_details(session_id: int):
    """Zwraca szczegóły pojedynczej sesji TUS, w tym listę jej uczestników."""
    with session_scope() as db_session:
        session_obj = db_session.query(TUSSession).options(
            joinedload(TUSSession.topic)
        ).filter(TUSSession.id == session_id).first()
        if not session_obj:
            return jsonify({"error": "Session not found"}), 404

        group = db_session.query(TUSGroup).options(
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client)
        ).filter(TUSGroup.id == session_obj.group_id).first()
        
        members_json = []
        if group and group.members:
            members_json = [{"id": member.id, "full_name": member.full_name} for member in group.members]

        session_data = {
            "id": session_obj.id,
            "session_date": session_obj.session_date.isoformat(),
            "topic_title": session_obj.topic.title if session_obj.topic else "Brak tematu",
            "members": members_json
        }
        return jsonify(session_data)

@app.put("/api/tus/sessions/<int:session_id>")
def update_tus_session(session_id):
    data = request.get_json(silent=True) or {}
    with session_scope() as db_session:
        s = db_session.get(TUSSession, session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404

        if "topic_id" in data: s.topic_id = data["topic_id"]
        if "bonuses_awarded" in data: s.bonuses_awarded = int(data["bonuses_awarded"])
        if "session_date" in data:
            try:
                dt = datetime.fromisoformat(data["session_date"])
                s.session_date = dt.date()
                s.session_time = dt.time()
            except (ValueError, TypeError):
                return jsonify({"error": "Nieprawidłowy format daty."}), 400
        return jsonify({"ok": True}), 200

@app.delete("/api/tus/sessions/<int:session_id>")
def delete_tus_session(session_id):
    delete_all_bonuses = request.args.get('delete_all_bonuses', 'false').lower() == 'true'
    with session_scope() as db_session:
        session_to_delete = db_session.get(TUSSession, session_id)
        if not session_to_delete:
            return jsonify({"error": "Session not found"}), 404
        
        group_id = session_to_delete.group_id
        if delete_all_bonuses:
            print(f"DIAGNOSTYKA: Usuwanie wszystkich bonusów dla grupy ID: {group_id}")
            db_session.query(TUSGeneralBonus).filter(TUSGeneralBonus.group_id == group_id).delete()
            session_ids_in_group = db_session.query(TUSSession.id).filter(TUSSession.group_id == group_id)
            db_session.query(TUSMemberBonus).filter(TUSMemberBonus.session_id.in_(session_ids_in_group)).delete()
        
        db_session.delete(session_to_delete)
    return jsonify({"ok": True}), 200

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
            TUSSession.id, TUSSession.session_time, TUSGroup.name, TUSTopic.title
        ).join(TUSGroup).join(TUSTopic).filter(TUSSession.session_date == query_date).order_by(TUSSession.session_time).all()
        result = [{
            "session_id": s.id,
            "session_time": s.session_time.strftime('%H:%M:%S') if s.session_time else None,
            "group_name": s.name,
            "topic_title": s.title
        } for s in sessions]
        return jsonify(result)

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
    """Body: { behaviors: [ {behavior_id, max_points?}, ... ] }"""
    data = request.get_json(silent=True) or {}
    items = data.get("behaviors") or []
    if len(items) > 4:
        return jsonify({"error": "max 4 behaviors per session"}), 400
    with engine.begin() as conn:
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
        beh = conn.execute(text("""
              SELECT sb.behavior_id, b.title, sb.max_points
              FROM tus_session_behaviors sb
              JOIN tus_behaviors b ON b.id=sb.behavior_id
              WHERE sb.session_id=:sid ORDER BY b.title
            """), {"sid": sid}).mappings().all()
        
        grp = conn.execute(text("SELECT group_id FROM tus_sessions WHERE id=:sid"), {"sid": sid}).scalar()
        members = conn.execute(text("""
              SELECT c.id, c.full_name FROM tus_groups g
              JOIN tus_group_members gm ON gm.group_id=g.id
              JOIN clients c ON c.id=gm.client_id
              WHERE g.id=:gid ORDER BY c.full_name
            """), {"gid": grp}).mappings().all()
        
        sc_rows = conn.execute(text("SELECT client_id, behavior_id, points FROM tus_session_member_scores WHERE session_id=:sid"), {"sid": sid}).mappings().all()
        scores = {}
        for r in sc_rows:
            scores.setdefault(r["client_id"], {})[r["behavior_id"]] = r["points"]
        
        rw = conn.execute(text("SELECT client_id, awarded, note, points FROM tus_session_partial_rewards WHERE session_id=:sid"), {"sid": sid}).mappings().all()
        rewards = {r["client_id"]: {"awarded": r["awarded"], "note": r["note"], "points": r["points"]} for r in rw}
        
        return jsonify({
            "behaviors": [dict(b) for b in beh],
            "members": [dict(m) for m in members],
            "scores": scores, "rewards": rewards
        })

@app.post("/api/tus/sessions/<int:sid>/scores")
def save_session_scores(sid):
    """Zapisuje punkty i nagrody częściowe dla sesji."""
    data = request.get_json(silent=True) or {}
    items = data.get("scores") or []
    with engine.begin() as conn:
        limits = {r["behavior_id"]: r["max_points"] for r in conn.execute(text("SELECT behavior_id, max_points FROM tus_session_behaviors WHERE session_id=:sid"), {"sid": sid}).mappings().all()}
        for row in items:
            cid = int(row["client_id"])
            for it in (row.get("items") or []):
                bid = int(it["behavior_id"])
                pts = int(it.get("points", 0))
                if bid not in limits:
                    return jsonify({"error": f"behavior {bid} not attached to session"}), 400
                if pts < 0 or pts > limits[bid]:
                    return jsonify({"error": f"points {pts} out of range for behavior {bid} (max {limits[bid]})"}), 400
                conn.execute(text("""
                      INSERT INTO tus_session_member_scores(session_id, client_id, behavior_id, points)
                      VALUES (:sid,:cid,:bid,:pts)
                      ON CONFLICT (session_id, client_id, behavior_id)
                      DO UPDATE SET points = EXCLUDED.points
                    """), {"sid": sid, "cid": cid, "bid": bid, "pts": pts})

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
                           "pts": int(pr.get("points", 0))
                           })
    return jsonify({"ok": True}), 200

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
        row = conn.execute(text("SELECT id, group_id FROM tus_sessions WHERE id=:sid"), {"sid": session_id}).mappings().first()
        if not row:
            return jsonify({"error": "Sesja nie istnieje"}), 404
        gid = row["group_id"]

        member = conn.execute(text("SELECT 1 FROM tus_group_members WHERE group_id=:gid AND client_id=:cid"), {"gid": gid, "cid": client_id}).scalar()
        if not member:
            return jsonify({"error": "Klient nie należy do tej grupy"}), 400
        
        new_id = conn.execute(text("""
                INSERT INTO tus_member_bonuses (session_id, client_id, points)
                VALUES (:sid, :cid, :pts)
                RETURNING id
            """), {"sid": session_id, "cid": client_id, "pts": points}).scalar_one()

    return jsonify({"id": new_id, "ok": True}), 201

@app.get("/api/tus/sessions/<int:session_id>/bonuses")
def get_session_bonuses(session_id):
    """Pobiera listę bonusów indywidualnych przyznanych w danej sesji."""
    with session_scope() as db_session:
        bonuses = db_session.query(TUSMemberBonus).filter(TUSMemberBonus.session_id == session_id).all()
        result = {b.client_id: b.points for b in bonuses}
        return jsonify(result)

@app.post("/api/tus/sessions/<int:session_id>/bonuses")
def save_session_bonuses(session_id):
    """Zapisuje 'hurtowo' bonusy indywidualne dla uczestników sesji."""
    data = request.get_json(silent=True) or {}
    bonuses_data = data.get("bonuses", [])
    with session_scope() as db_session:
        db_session.query(TUSMemberBonus).filter(TUSMemberBonus.session_id == session_id).delete()
        for bonus in bonuses_data:
            if bonus.get("points", 0) > 0:
                new_bonus = TUSMemberBonus(
                    session_id=session_id,
                    client_id=bonus["client_id"],
                    points=bonus["points"]
                )
                db_session.add(new_bonus)
    return jsonify({"ok": True}), 200

# --- Trasy: Obecność (Attendance) ---

@app.get("/api/tus/sessions/<int:session_id>/attendance")
def get_attendance(session_id):
    """Pobiera listę uczestników i ich status obecności dla danej sesji TUS."""
    with session_scope() as db_session:
        session = db_session.query(TUSSession).filter_by(id=session_id).first()
        if not session:
            return jsonify({"error": "Sesja nie znaleziona"}), 404

        members = db_session.query(Client.id, Client.full_name) \
            .join(TUSGroupMember) \
            .filter(TUSGroupMember.group_id == session.group_id).order_by(Client.full_name).all()
        
        attendance_records = db_session.query(TUSSessionAttendance).filter_by(session_id=session_id).all()
        attendance_map = {rec.client_id: rec.status for rec in attendance_records}

        return jsonify({
            "group_name": session.group.name,
            "members": [{"id": m.id, "full_name": m.full_name} for m in members],
            "attendance": attendance_map
        })

@app.post("/api/tus/sessions/<int:session_id>/attendance")
def save_attendance(session_id):
    """Zapisuje listę obecności dla sesji TUS."""
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "Oczekiwano listy obiektów."}), 400

    with session_scope() as db_session:
        db_session.query(TUSSessionAttendance).filter_by(session_id=session_id).delete()
        for item in data:
            new_attendance = TUSSessionAttendance(
                session_id=session_id,
                client_id=item['client_id'],
                status=item['status']
            )
            db_session.add(new_attendance)
    return jsonify({"message": "Obecność zapisana pomyślnie."}), 200

@app.get("/api/individual-sessions-for-day")
def get_individual_sessions_for_day():
    """Zwraca listę indywidualnych sesji terapeutycznych dla podanej daty."""
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
        
        result = [{
            "slot_id": s.slot_id,
            "starts_at": s.starts_at.isoformat(),
            "client_name": s.client_name,
            "therapist_name": s.therapist_name,
            "attendance_status": s.attendance_status or 'obecny'
        } for s in sessions]
        return jsonify(result)

@app.patch("/api/individual-attendance/<int:slot_id>")
def update_individual_attendance(slot_id):
    """Aktualizuje lub tworzy (UPSERT) status obecności dla pojedynczego slotu."""
    data = request.get_json()
    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "Status jest wymagany."}), 400

    with session_scope() as db_session:
        attendance_record = db_session.query(IndividualSessionAttendance).filter_by(slot_id=slot_id).first()
        if attendance_record:
            attendance_record.status = new_status
        else:
            new_attendance = IndividualSessionAttendance(slot_id=slot_id, status=new_status)
            db_session.add(new_attendance)
    return jsonify({"message": "Status obecności zaktualizowany."})

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
        
        all_records.sort(key=lambda x: x['date'])
        return jsonify(all_records)

@app.route('/api/daily-attendance', methods=['GET'])
def get_daily_attendance():
    """Pobiera obecność indywidualną dla danego dnia."""
    try:
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({'error': 'Date parameter is required'}), 400

        with session_scope() as db_session:
            attendance_data = db_session.query(
                IndividualSessionAttendance, ScheduleSlot, Client
            ).join(ScheduleSlot, IndividualSessionAttendance.slot_id == ScheduleSlot.id) \
             .join(Client, ScheduleSlot.client_id == Client.id) \
             .filter(func.date(ScheduleSlot.starts_at) == date_str) \
             .all()

            result = []
            for attendance, slot, client in attendance_data:
                result.append({
                    'client_id': client.id, 'status': attendance.status, 'notes': '',
                    'session_time': slot.starts_at.strftime('%H:%M') if slot.starts_at else '09:00',
                    'service_type': slot.kind, 'therapist_id': slot.therapist_id
                })
            return jsonify(result)
    except Exception as e:
        print(f"Błąd w /api/daily-attendance: {str(e)}")
        return jsonify([])

# UWAGA: Poniższe dwie trasy są na różnych URL, ale robią to samo.
# Rozważ skonsolidowanie ich w przyszłości.
@app.route('/api/attendance/bulk', methods=['POST'])
def save_bulk_attendance():
    """Zapisuje masowo obecność (wersja 1)."""
    try:
        data = request.get_json()
        date_str = data.get('date')
        attendance_list = data.get('attendance', [])
        if not date_str: return jsonify({'error': 'Date is required'}), 400
        
        query_date = date.fromisoformat(date_str)
        print(f"Zapisuję BULK obecność dla daty {query_date}, liczba wpisów: {len(attendance_list)}")
        
        saved_count = 0
        with session_scope() as db_session:
            for attendance_data in attendance_list:
                client_id = attendance_data.get('client_id')
                status = attendance_data.get('status')
                if not client_id or not status: continue

                slot = db_session.query(ScheduleSlot).filter(
                    ScheduleSlot.client_id == client_id,
                    func.date(ScheduleSlot.starts_at.op('AT TIME ZONE')('Europe/Warsaw')) == query_date,
                    ScheduleSlot.kind == 'therapy'
                ).first()

                if not slot:
                    print(f"OSTRZEŻENIE: Nie znaleziono slotu dla klienta {client_id} w dniu {query_date}. Tworzę nowy slot.")
                    session_time = attendance_data.get('session_time', '09:00')
                    therapist_id = attendance_data.get('therapist_id', 1)
                    starts_at = datetime.strptime(f"{date_str} {session_time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                    ends_at = starts_at + timedelta(hours=1)
                    slot = ScheduleSlot(
                        client_id=client_id, therapist_id=therapist_id, kind='therapy',
                        starts_at=starts_at, ends_at=ends_at, status='planned'
                    )
                    db_session.add(slot)
                    db_session.flush()
                
                attendance_record = db_session.query(IndividualSessionAttendance).filter_by(slot_id=slot.id).first()
                if attendance_record:
                    attendance_record.status = status
                else:
                    new_attendance = IndividualSessionAttendance(slot_id=slot.id, status=status)
                    db_session.add(new_attendance)
                saved_count += 1
            
            print(f"Zatwierdzam {saved_count} zmian w bazie danych...")
        
        return jsonify({'message': 'Obecność zapisana pomyślnie', 'count': saved_count, 'date': date_str})
    except Exception as e:
        print(f"Błąd w /api/attendance/bulk: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/daily-attendance/bulk', methods=['POST'])
def save_daily_attendance_bulk():
    """Zapisuje masowo obecność (wersja 2)."""
    try:
        data = request.get_json()
        date_str = data.get('date')
        attendance_list = data.get('attendance', [])
        if not date_str: return jsonify({'error': 'Date is required'}), 400

        query_date = date.fromisoformat(date_str)
        print(f"Zapisuję DAILY-BULK obecność dla daty {query_date}, liczba wpisów: {len(attendance_list)}")

        saved_count = 0
        with session_scope() as db_session:
            for attendance_data in attendance_list:
                client_id = attendance_data.get('client_id')
                status = attendance_data.get('status')
                if not client_id or not status: continue
                
                slot = db_session.query(ScheduleSlot).filter(
                    ScheduleSlot.client_id == client_id,
                    func.date(ScheduleSlot.starts_at.op('AT TIME ZONE')('Europe/Warsaw')) == query_date,
                    ScheduleSlot.kind == 'therapy'
                ).first()

                if not slot:
                    print(f"OSTRZEŻENIE: (Daily) Nie znaleziono slotu dla klienta {client_id} w dniu {query_date}. Tworzę nowy slot.")
                    session_time = attendance_data.get('session_time', '09:00')
                    therapist_id = attendance_data.get('therapist_id', 1)
                    starts_at = datetime.strptime(f"{date_str} {session_time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                    ends_at = starts_at + timedelta(hours=1)
                    slot = ScheduleSlot(
                        client_id=client_id, therapist_id=therapist_id, kind='therapy',
                        starts_at=starts_at, ends_at=ends_at, status='planned'
                    )
                    db_session.add(slot)
                    db_session.flush()
                
                attendance_record = db_session.query(IndividualSessionAttendance).filter_by(slot_id=slot.id).first()
                if attendance_record:
                    attendance_record.status = status
                else:
                    new_attendance = IndividualSessionAttendance(slot_id=slot.id, status=status)
                    db_session.add(new_attendance)
                saved_count += 1
        
        return jsonify({'message': 'Obecność zapisana pomyślnie', 'count': saved_count, 'date': date_str})
    except Exception as e:
        print(f"Błąd w /api/daily-attendance/bulk: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/attendance', methods=['GET'])
def get_attendance_by_date():
    """Pobiera obecność dla daty i klienta ZE WSZYSTKICH ŹRÓDEŁ."""
    try:
        date_str = request.args.get('date')
        client_id = request.args.get('client_id', type=int)

        if not date_str: return jsonify({'error': 'Date parameter is required'}), 400
        if not client_id: return jsonify({'error': 'client_id parameter is required'}), 400
        
        try:
            query_date = date.fromisoformat(date_str)
        except ValueError:
            return jsonify({'error': f'Invalid date format: {date_str}. Expected YYYY-MM-DD.'}), 400
        
        print(f"📅 Pobieram obecność (ALL) dla daty: {query_date}, klient: {client_id}")
        
        with session_scope() as db_session:
            attendance_list = []
            
            # 1. Sesje Indywidualne (SUO)
            query_individual = db_session.query(
                ScheduleSlot.client_id, IndividualSessionAttendance.status,
                ScheduleSlot.starts_at, ScheduleSlot.therapist_id, ScheduleSlot.kind
            ).join(IndividualSessionAttendance, ScheduleSlot.id == IndividualSessionAttendance.slot_id) \
             .filter(
                func.date(ScheduleSlot.starts_at) == query_date,
                ScheduleSlot.kind == 'therapy',
                ScheduleSlot.client_id == client_id
            )
            results_individual = query_individual.all()
            for row in results_individual:
                attendance_list.append({
                    'client_id': row.client_id, 'status': row.status,
                    'session_time': row.starts_at.strftime('%H:%M') if row.starts_at else '09:00',
                    'service_type': row.kind, 'therapist_id': row.therapist_id,
                    'notes': 'Sesja indywidualna SUO'
                })

            # 2. Sesje Grupowe (TUS)
            query_tus = db_session.query(
                TUSSessionAttendance.client_id, TUSSessionAttendance.status,
                TUSSession.session_time, TUSGroup.therapist_id
            ).join(TUSSession, TUSSession.id == TUSSessionAttendance.session_id) \
             .join(TUSGroup, TUSGroup.id == TUSSession.group_id) \
             .filter(
                TUSSession.session_date == query_date,
                TUSSessionAttendance.client_id == client_id
            )
            results_tus = query_tus.all()
            for row in results_tus:
                attendance_list.append({
                    'client_id': row.client_id, 'status': row.status,
                    'session_time': row.session_time.strftime('%H:%M') if row.session_time else '12:00',
                    'service_type': 'tus', 'therapist_id': row.therapist_id,
                    'notes': 'Sesja grupowa TUS'
                })

            # 3. Wpisy w Dzienniku
            query_journal = db_session.query(
                JournalEntry.client_id, JournalEntry.therapist_id, JournalEntry.temat
            ).filter(
                JournalEntry.data == query_date,
                JournalEntry.client_id == client_id
            )
            results_journal = query_journal.all()
            for row in results_journal:
                if not any(a['client_id'] == row.client_id for a in attendance_list):
                    attendance_list.append({
                        'client_id': row.client_id, 'status': 'obecny',
                        'session_time': '10:00', 'service_type': 'journal',
                        'therapist_id': row.therapist_id,
                        'notes': f"Wpis w dzienniku: {row.temat or ''}"
                    })
            
            print(f"✅ Znaleziono łącznie {len(attendance_list)} wpisów (Ind: {len(results_individual)}, TUS: {len(results_tus)}, Journal: {len(results_journal)})")
            return jsonify(attendance_list), 200

    except Exception as e:
        print(f"❌ Błąd w /api/attendance: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# --- Trasy: Historia i Notatki Klienta ---

@app.get("/api/clients/<int:client_id>/history")
def get_client_history(client_id: int):
    """Pobiera historię sesji indywidualnych i TUS dla klienta."""
    try:
        with engine.begin() as conn:
            individual_sql = text('''
                    SELECT 
                        ss.id as slot_id, ss.starts_at, ss.ends_at, ss.status,
                        th.full_name as therapist_name, eg.label as topic, ss.place_to as place,
                        EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes
                    FROM schedule_slots ss
                    LEFT JOIN therapists th ON th.id = ss.therapist_id
                    LEFT JOIN event_groups eg ON eg.id = ss.group_id
                    WHERE ss.client_id = :cid AND ss.kind = 'therapy'
                    ORDER BY ss.starts_at DESC
                ''')
            individual_rows = conn.execute(individual_sql, {"cid": client_id}).mappings().all()

            notes_sql = text('''
                    SELECT DISTINCT ON (DATE(created_at))
                        id, content, created_at, category
                    FROM client_notes
                    WHERE client_id = :cid AND category = 'session'
                    ORDER BY DATE(created_at) DESC, created_at DESC
                ''')
            notes_rows = conn.execute(notes_sql, {"cid": client_id}).mappings().all()
            
            notes_map = {}
            note_ids_map = {}
            for note in notes_rows:
                note_date = note['created_at'].date()
                notes_map[note_date] = note['content']
                note_ids_map[note_date] = note['id']

            tus_sql = text('''
                    SELECT 
                        ts.session_date, ts.session_time,
                        tt.title as topic_title, tg.name as group_name
                    FROM tus_sessions ts
                    JOIN tus_groups tg ON tg.id = ts.group_id
                    JOIN tus_group_members tgm ON tgm.group_id = tg.id
                    LEFT JOIN tus_topics tt ON tt.id = ts.topic_id
                    WHERE tgm.client_id = :cid
                    ORDER BY ts.session_date DESC
                ''')
            tus_rows = conn.execute(tus_sql, {"cid": client_id}).mappings().all()

            history = {
                "individual": [{
                    "date": row['starts_at'].isoformat() if row['starts_at'] else None,
                    "status": row['status'] or "unknown",
                    "therapist": row['therapist_name'] or "Nieznany",
                    "topic": row['topic'] or "Bez tematu",
                    "notes": notes_map.get(row['starts_at'].date(), "") if row['starts_at'] else "",
                    "note_id": note_ids_map.get(row['starts_at'].date()) if row['starts_at'] else None,
                    "place": row['place'] or "",
                    "duration": int(row['duration_minutes']) if row['duration_minutes'] else 60,
                } for row in individual_rows],
                "tus_group": [{
                    "date": row['session_date'].isoformat() if row['session_date'] else None,
                    "time": row['session_time'].strftime('%H:%M') if row['session_time'] else None,
                    "topic": row['topic_title'] or "Brak tematu",
                    "group": row['group_name'] or "Nieznana grupa"
                } for row in tus_rows]
            }
            return jsonify(history), 200
    except Exception as e:
        print(f"❌ BŁĄD w get_client_history: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.get("/api/clients/<int:client_id>/all-sessions")
def get_client_all_sessions(client_id: int):
    """Zwraca ujednoliconą historię (Indywidualne + Dziennik)."""
    try:
        with engine.begin() as conn:
            sql = text('''
                SELECT 
                    ss.id as source_id, 'individual' as source_type, ss.starts_at, ss.ends_at,
                    ss.status, th.full_name as therapist_name, eg.label as topic_or_temat,
                    ss.place_to as place, EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes,
                    cn.content as notes, cn.id as note_id
                FROM schedule_slots ss
                LEFT JOIN therapists th ON th.id = ss.therapist_id
                LEFT JOIN event_groups eg ON eg.id = ss.group_id
                LEFT JOIN client_notes cn ON cn.client_id = ss.client_id 
                    AND DATE(cn.created_at) = DATE(ss.starts_at)
                    AND cn.category = 'session'
                WHERE ss.client_id = :cid AND ss.kind = 'therapy'
                UNION ALL
                SELECT 
                    d.id as source_id, 'journal' as source_type,
                    d.data::timestamp with time zone AS starts_at,
                    (d.data + interval '60 minutes')::timestamp with time zone AS ends_at,
                    'done' as status, th.full_name as therapist_name,
                    d.temat as topic_or_temat, 'Dziennik' as place, 60 as duration_minutes,
                    d.cele as notes, NULL as note_id
                FROM dziennik d
                JOIN therapists th ON th.id = d.therapist_id
                WHERE d.client_id = :cid
                ORDER BY starts_at DESC
            ''')
            rows = conn.execute(sql, {"cid": client_id}).mappings().all()

            history = []
            for row in rows:
                row_dict = dict(row)
                if row_dict['starts_at']: row_dict['starts_at'] = row_dict['starts_at'].isoformat()
                if row_dict['ends_at']: row_dict['ends_at'] = row_dict['ends_at'].isoformat()
                if row_dict['duration_minutes']: row_dict['duration_minutes'] = int(row_dict['duration_minutes'])
                history.append(row_dict)
            return jsonify(history), 200
    except Exception as e:
        print(f"❌ BŁĄD w get_client_all_sessions: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.get("/api/clients/<int:client_id>/notes")
def get_client_notes(client_id):
    """Pobiera notatki dla danego klienta."""
    category = request.args.get('category')
    try:
        with engine.begin() as conn:
            exists = conn.execute(text('SELECT 1 FROM clients WHERE id = :cid'), {"cid": client_id}).scalar()
            if not exists: return jsonify({'error': 'Klient nie istnieje'}), 404

            if category and category != 'all':
                sql = text('''
                        SELECT id, client_id, content, category, created_by_name, created_at, updated_at
                        FROM client_notes
                        WHERE client_id = :cid AND category = :cat
                        ORDER BY created_at DESC
                    ''')
                result = conn.execute(sql, {"cid": client_id, "cat": category})
            else:
                sql = text('''
                        SELECT id, client_id, content, category, created_by_name, created_at, updated_at
                        FROM client_notes
                        WHERE client_id = :cid
                        ORDER BY created_at DESC
                    ''')
                result = conn.execute(sql, {"cid": client_id})

            notes = []
            for row in result.mappings().all():
                note = dict(row)
                if note['created_at']: note['created_at'] = note['created_at'].isoformat()
                if note['updated_at']: note['updated_at'] = note['updated_at'].isoformat()
                notes.append(note)
            return jsonify(notes), 200
    except Exception as e:
        print(f"Błąd w get_client_notes: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.post("/api/clients/<int:client_id>/notes")
def add_client_note(client_id):
    """Dodaje nową notatkę dla klienta"""
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    category = data.get('category', 'general')
    created_by_name = data.get('created_by_name', 'System')

    if not content:
        return jsonify({'error': 'Treść notatki jest wymagana'}), 400
    try:
        with engine.begin() as conn:
            exists = conn.execute(text('SELECT 1 FROM clients WHERE id = :cid'), {"cid": client_id}).scalar()
            if not exists: return jsonify({'error': 'Klient nie istnieje'}), 404

            result = conn.execute(text('''
                    INSERT INTO client_notes (client_id, content, category, created_by_name)
                    VALUES (:cid, :content, :category, :created_by)
                    RETURNING id, client_id, content, category, created_by_name, created_at, updated_at
                '''), {
                "cid": client_id, "content": content,
                "category": category, "created_by": created_by_name
            })
            note = dict(result.mappings().first())
            note['created_at'] = note['created_at'].isoformat()
            note['updated_at'] = note['updated_at'].isoformat()
            return jsonify(note), 201
    except Exception as e:
        print(f"Błąd w add_client_note: {str(e)}")
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
            exists = conn.execute(text('SELECT 1 FROM client_notes WHERE id = :nid AND client_id = :cid'), {"nid": note_id, "cid": client_id}).scalar()
            if not exists:
                return jsonify({'error': 'Notatka nie istnieje lub nie należy do tego klienta'}), 404
            
            result = conn.execute(text('''
                    UPDATE client_notes
                    SET content = :content, category = :category, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :nid AND client_id = :cid
                    RETURNING id, client_id, content, category, created_by_name, created_at, updated_at
                '''), {
                "nid": note_id, "cid": client_id,
                "content": content, "category": category
            })
            note = dict(result.mappings().first())
            note['created_at'] = note['created_at'].isoformat()
            note['updated_at'] = note['updated_at'].isoformat()
            return jsonify(note), 200
    except Exception as e:
        print(f"Błąd w update_client_note: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.delete("/api/clients/<int:client_id>/notes/<int:note_id>")
def delete_client_note(client_id, note_id):
    """Usuwa notatkę"""
    try:
        with engine.begin() as conn:
            exists = conn.execute(text('SELECT 1 FROM client_notes WHERE id = :nid AND client_id = :cid'), {"nid": note_id, "cid": client_id}).scalar()
            if not exists:
                return jsonify({'error': 'Notatka nie istnieje lub nie należy do tego klienta'}), 404
            
            conn.execute(text('DELETE FROM client_notes WHERE id = :nid AND client_id = :cid'), {"nid": note_id, "cid": client_id})
            return jsonify({'message': 'Notatka usunięta pomyślnie'}), 200
    except Exception as e:
        print(f"Błąd w delete_client_note: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.get("/api/clients/<int:client_id>/sessions")
def get_client_sessions(client_id):
    """Pobiera sesje terapii (indywidualne) dla klienta."""
    month = request.args.get('month')
    try:
        with engine.begin() as conn:
            exists = conn.execute(text('SELECT 1 FROM clients WHERE id = :cid'), {"cid": client_id}).scalar()
            if not exists: return jsonify({'error': 'Klient nie istnieje'}), 404

            if month:
                sql = text('''
                        SELECT ss.id, eg.label, ss.starts_at, ss.ends_at, ss.place_to,
                               EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes,
                               th.full_name as therapist_name, cn.content as notes, cn.id as note_id
                        FROM schedule_slots ss
                        LEFT JOIN event_groups eg ON eg.id = ss.group_id::uuid
                        LEFT JOIN therapists th ON th.id = ss.therapist_id
                        LEFT JOIN client_notes cn ON cn.client_id = ss.client_id 
                            AND DATE(cn.created_at) = DATE(ss.starts_at) AND cn.category = 'session'
                        WHERE ss.client_id = :cid AND ss.kind = 'therapy' AND ss.starts_at IS NOT NULL
                            AND DATE_TRUNC('month', ss.starts_at) = DATE_TRUNC('month', TO_DATE(:month, 'YYYY-MM'))
                        ORDER BY ss.starts_at DESC
                    ''')
                result = conn.execute(sql, {"cid": client_id, "month": month + "-01"})
            else:
                sql = text('''
                        SELECT ss.id, eg.label, ss.starts_at, ss.ends_at, ss.place_to,
                               EXTRACT(EPOCH FROM (ss.ends_at - ss.starts_at))/60 as duration_minutes,
                               th.full_name as therapist_name, cn.content as notes, cn.id as note_id
                        FROM schedule_slots ss
                        LEFT JOIN event_groups eg ON eg.id = ss.group_id::uuid
                        LEFT JOIN therapists th ON th.id = ss.therapist_id
                        LEFT JOIN client_notes cn ON cn.client_id = ss.client_id 
                            AND DATE(cn.created_at) = DATE(ss.starts_at) AND cn.category = 'session'
                        WHERE ss.client_id = :cid AND ss.kind = 'therapy' AND ss.starts_at IS NOT NULL
                        ORDER BY ss.starts_at DESC
                        LIMIT 100
                    ''')
                result = conn.execute(sql, {"cid": client_id})

            sessions = []
            for row in result.mappings().all():
                session = dict(row)
                if session['starts_at']: session['starts_at'] = session['starts_at'].isoformat()
                if session['ends_at']: session['ends_at'] = session['ends_at'].isoformat()
                if session['duration_minutes']: session['duration_minutes'] = int(session['duration_minutes'])
                sessions.append(session)
            return jsonify(sessions), 200
    except Exception as e:
        print(f"Błąd w get_client_sessions: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
            "cid": client_id, "dow": data['day_of_week'],
            "start": data['start_time'], "end": data['end_time'],
            "notes": data.get('notes')
        }).scalar_one()
    return jsonify({"id":new_id}), 201
        
        # === SEKCJA 10: URUCHOMIENIE APLIKACJI I INICJALIZACJA BAZY DANYCH ===

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("ROZPOCZYNANIE INICJALIZACJI BAZY DANYCH...")
    print("=" * 60)
    
    # 1. Tworzy tabele zdefiniowane przez ORM (SQLAlchemy Base)
    #    Dotyczy to klas takich jak: Client, Therapist, TUSGroup, ScheduleSlot itp.
    try:
        # Base.metadata.create_all() tworzy tabele, jeśli nie istnieją.
        # Nie usuwa istniejących danych ani tabel.
        Base.metadata.create_all(bind=engine)
        print("✓ Tabele zdefiniowane w ORM (Base.metadata) zostały pomyślnie utworzone/sprawdzone.")
    except Exception as e:
        print(f"✗ KRYTYCZNY BŁĄD podczas tworzenia tabel ORM (Base.metadata): {e}")
        print(traceback.format_exc())
        sys.exit(1) # Przerwij, jeśli podstawowe tabele ORM nie mogą powstać

    # 2. Wywołuje funkcję tworzącą tabele zdefiniowane ręcznie (z SEKCJI 5)
    #    Dotyczy to tabel: dziennik, client_notes, projects itp.
    #    Ta funkcja (init_all_tables) ma już własne komunikaty o błędach.
    if not init_all_tables():
        print("✗ Wystąpił błąd podczas inicjalizacji tabel ręcznych (patrz logi powyżej).")
        # Można zdecydować, czy kontynuować, ale prawdopodobnie lepiej przerwać
        sys.exit(1)

    print("\n" + "=" * 60)
    print("INICJALIZACJA ZAKOŃCZONA. URUCHAMIANIE SERWERA FLASK...")
    print("=" * 60)
    
    # Pobranie portu ze zmiennej środowiskowej (np. dla Heroku/Render)
    # lub użycie domyślnego portu 5000 dla lokalnego dewelopmentu.
    port = int(os.getenv("PORT", 5000))
    
    # app.run() uruchamia wbudowany serwer deweloperski Flaska.
    # host='0.0.0.0' sprawia, że serwer jest dostępny z zewnątrz
    # (np. z innego komputera w tej samej sieci).
    # debug=True włącza tryb debugowania (automatyczne przeładowanie przy zmianach).
    app.run(debug=True, host='0.0.0.0', port=port)
