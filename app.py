# Wersja po refaktoryzacji, poprawkach błędów i ujednoliceniu dostępu do bazy danych.
import math
import os
import uuid
from datetime import datetime, timedelta, date
from functools import wraps
from math import exp
from zoneinfo import ZoneInfo

import joblib
import pandas as pd
import psycopg2
import requests
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from contextlib import contextmanager
from psycopg2 import errorcodes

from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Table,
                        Boolean, Float, Time, create_engine, func, text, bindparam, TIMESTAMP, Date,desc,
                        UniqueConstraint,select)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base, relationship, joinedload, aliased
from sqlalchemy.exc import IntegrityError


# === KONFIGURACJA APLIKACJI ===
TZ = ZoneInfo("Europe/Warsaw")
app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# Wczytywanie konfiguracji ze zmiennych środowiskowych
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:EDUQ@localhost:5432/suo")
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

# === MODELE BAZY DANYCH (SQLALCHEMY ORM) ===

# Tabela pośrednicząca dla relacji TUSGroup <-> Client
#tus_group_members = Table('tus_group_members', Base.metadata,
#                          Column('group_id', Integer, ForeignKey('tus_groups.id', ondelete="CASCADE"),
#                                 primary_key=True),
#                          Column('client_id', Integer, ForeignKey('clients.id', ondelete="CASCADE"), primary_key=True)

#                         )


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
    group_id = Column(String, ForeignKey('event_groups.id', ondelete="CASCADE"))
    client_id = Column(Integer, ForeignKey('clients.id'))
    therapist_id = Column(Integer, ForeignKey('therapists.id'))
    driver_id = Column(Integer, ForeignKey('drivers.id'))
    kind = Column(String, nullable=False)
    starts_at = Column(DateTime(timezone=True))
    ends_at = Column(DateTime(timezone=True))
    status = Column(String, default='planned')
    distance_km = Column(Float)
    session_id = Column(String)  # Do łączenia sesji grupowych
    run_id = Column(String)  # Do łączenia kursów

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
    sessions = relationship("TUSSession", back_populates="group", cascade="all, delete-orphan", lazy="selectin")

    # POPRAWKA: Definiujemy relację do obiektu pośredniczącego
    member_associations = relationship("TUSGroupMember", back_populates="group", cascade="all, delete-orphan")

    # "Proxy" sprawia, że group.members jest wygodną listą klientów
    # Association proxy z dodanym creatorem
    members = association_proxy(
        'member_associations',  # <-- ZMIANA Z 'group_members' NA 'member_associations'
        'client',
        creator=_create_member_association
    )

    # POPRAWKA: Dodano brakującą relację many-to-many do Client
    #members = relationship(
    #    "Client",
    #    secondary='tus_group_members',
    #   backref="tus_groups",  # Umożliwia dostęp client.tus_groups
    #    lazy="selectin"
    #)
    # Dodatkowe pola na cele punktowe
    halfyear_target_points = Column(Integer)
    halfyear_reward = Column(String)
    annual_target_points = Column(Integer)
    annual_reward = Column(String)


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
    school_year_start = Column(Integer, nullable=False) # Np. 2025 dla roku 2025/2026
    semester = Column(Integer, nullable=False) # 1 lub 2
    target_points = Column(Integer, nullable=False, default=0)
    reward = Column(String)

    __table_args__ = (UniqueConstraint('group_id', 'school_year_start', 'semester'),)

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


Session = sessionmaker(bind=engine)
with Session() as session:
    # Pobieramy pierwszego terapeutę z bazy
    pierwszy_terapeuta = session.query(Therapist).first()

    if pierwszy_terapeuta:
        print(f"Znaleziono terapeutę: {pierwszy_terapeuta.full_name}")


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


def get_route_distance(origin, destination):
    """Oblicza dystans między dwoma punktami za pomocą Google Maps API."""
    # POPRAWKA: Użycie klucza z konfiguracji
    api_key = GOOGLE_MAPS_API_KEY

    if not api_key:
        print("OSTRZEŻENIE: Brak klucza GOOGLE_MAPS_API_KEY. Obliczanie dystansu nie zadziała.")
        return None

    if not origin or not destination:
        return None

    origin_safe = requests.utils.quote(origin)
    destination_safe = requests.utils.quote(destination)
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin_safe}&destination={destination_safe}&key={api_key}"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get('status') == 'OK':
            distance_meters = data['routes'][0]['legs'][0]['distance']['value']
            return round(distance_meters / 1000, 2)
    except requests.exceptions.RequestException as e:
        print(f"Błąd połączenia z Google Maps API: {e}")
    except (KeyError, IndexError):
        print(f"Nie udało się przetworzyć odpowiedzi z Google Maps dla trasy {origin} -> {destination}")
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
    return [v/s for v in exps]

def _score_ct_row(r):
    """Heurystyka oceny dopasowania klient-terapeuta (fallback dla AI)."""
    n = r.get("n_sessions", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5*rec + 0.3*done + 0.2*min(1.0, n/10.0) + 0.1*min(1.0, mins/600.0)

def _score_cd_row(r):
    """Heurystyka oceny dopasowania klient-kierowca (fallback dla AI)."""
    n = r.get("n_runs", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5*rec + 0.3*done + 0.2*min(1.0, n/10.0) + 0.1*min(1.0, mins/600.0)


def find_overlaps(conn, *, driver_id=None, therapist_id=None, starts_at=None, ends_at=None):
    """
    Zwraca listę kolidujących slotów dla driver_id/therapist_id i podanego zakresu czasu,
    sprawdzając ZARÓWNO kalendarz indywidualny, jak i grupowy TUS.
    """
    if starts_at is None or ends_at is None:
        return []

    # --- POCZĄTEK POPRAWKI ---
    # Jeśli sprawdzamy terapeutę, musimy przeszukać oba kalendarze.
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

    # Dla kierowców logika pozostaje bez zmian (sprawdzamy tylko schedule_slots)
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

    stmt = text(sql).bindparams(
        bindparam("s", type_=TIMESTAMP(timezone=True)),
        bindparam("e", type_=TIMESTAMP(timezone=True)),
    )
    return [dict(r) for r in conn.execute(stmt, params).mappings().all()]

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


# === DEKORATORY I HOOKI FLASK ===
@app.before_request
def parse_json_only_when_needed():
    if request.method in ('POST', 'PUT', 'PATCH'):
        g.json = request.get_json(silent=True) or {}
    else:
        g.json = None

# === GŁÓWNE ENDPOINTY APLIKACJI ===

@app.get("/")
def index():
    return app.send_static_file("index.html")


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
        nxt = first.replace(year=first.year+1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month+1, day=1)
    days = []
    d = first
    while d < nxt:
        days.append(d)
        d += timedelta(days=1)

    with engine.begin() as conn:
        # Klienci aktywni
        clients = conn.execute(text("SELECT id, full_name FROM clients WHERE active=true")).mappings().all()
        therapists = conn.execute(text("SELECT id, full_name FROM therapists WHERE active=true")).mappings().all()
        drivers    = conn.execute(text("SELECT id, full_name FROM drivers WHERE active=true")).mappings().all()

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
    th_worked   = {(r["therapist_id"], r["d"]) for r in rows if r["therapist_id"] and r["kind"]=='therapy'}
    dr_worked   = {(r["driver_id"], r["d"]) for r in rows if r["driver_id"] and r["kind"] in ('pickup','dropoff')}

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
    window = data.get("therapy_window") or ["08:00","16:00"]
    pk_off = int(data.get("pickup_offset_min", 30))
    dp_off = int(data.get("dropoff_offset_min", 30))

    start_bucket = _time_bucket(window[0])
    end_bucket   = _time_bucket(window[1])

    # przygotuj wiadra półgodzinne w zakresie okna
    all_buckets = []
    sh, sm = _parse_time(start_bucket)
    eh, em = _parse_time(end_bucket)
    cur_h, cur_m = sh, sm
    while (cur_h, cur_m) <= (eh, em):
        all_buckets.append(f"{cur_h:02d}:{cur_m:02d}")
        if cur_m == 0: cur_h, cur_m = cur_h, 30
        else: cur_h, cur_m = cur_h+1, 0

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
            best_bucket = max(all_buckets, key=lambda b: hours_pref.get(b, 0)) if hours_pref else all_buckets[len(all_buckets)//2]

            # sugerowany 60-min slot terapii (możesz zmienić)
            th_start = _to_tstz(date_str, best_bucket)
            th_end   = th_start + timedelta(minutes=60)

            # sprawdź kolizje terapeuty
            col = _availability_conflicts(conn, therapist_id=r["id"], starts_at=th_start, ends_at=th_end)
            if col:
                # jeśli koliduje, spróbuj przesuwać po bucketach (do 4 prób)
                tried = set([best_bucket])
                ok = False
                for b in all_buckets:
                    if b in tried: continue
                    s2 = _to_tstz(date_str, b); e2 = s2 + timedelta(minutes=60)
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
            buckets_needed = list({ _time_bucket(pk_start.strftime("%H:%M")),
                                    _time_bucket(dp_start.strftime("%H:%M")) })
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
                base_pk = base + (0.05 if dr_pref.get(r["id"],{}).get(bpk,0) > 0 else 0.0)

                col = _availability_conflicts(conn, driver_id=r["id"], starts_at=pk_start, ends_at=pk_end)
                if not col:
                    drivers_pickup.append({
                        "driver_id": r["id"], "full_name": r["full_name"],
                        "score": round(base_pk,3),
                        "suggested_start": pk_start.isoformat(),
                        "suggested_end": pk_end.isoformat()
                    })

                # dropoff
                bdp = _time_bucket(dp_start.strftime("%H:%M"))
                base_dp = base + (0.05 if dr_pref.get(r["id"],{}).get(bdp,0) > 0 else 0.0)
                col2 = _availability_conflicts(conn, driver_id=r["id"], starts_at=dp_start, ends_at=dp_end)
                if not col2:
                    drivers_dropoff.append({
                        "driver_id": r["id"], "full_name": r["full_name"],
                        "score": round(base_dp,3),
                        "suggested_start": dp_start.isoformat(),
                        "suggested_end": dp_end.isoformat()
                    })

            drivers_pickup.sort(key=lambda x: x["score"], reverse=True)
            drivers_dropoff.sort(key=lambda x: x["score"], reverse=True)
            drivers_pickup  = drivers_pickup[:5]
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
    return [v/s for v in exps]

def _score_ct_row(r):
    # prosta, działająca od ręki heurystyka
    # wagi możesz potem zgrać z modelem ML
    n = r.get("n_sessions", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5*rec + 0.3*done + 0.2*min(1.0, n/10.0) + 0.1*min(1.0, mins/600.0)

def _score_cd_row(r):
    n = r.get("n_runs", 0) or 0
    mins = r.get("minutes_sum", 0) or 0
    done = r.get("done_ratio", 0.0) or 0.0
    rec = r.get("recency_weight", 0.0) or 0.0
    return 0.5*rec + 0.3*done + 0.2*min(1.0, n/10.0) + 0.1*min(1.0, mins/600.0)

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
    else: # Fallback do starej logiki, jeśli model nie jest dostępny
        for r in ct_rows:
            r["score"] = round(_score_ct_row(r), 4)

    # Użyj modelu AI do oceny kierowców, jeśli jest wczytany
    if cd_model and cd_rows:
        features = ["n_runs", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
        X_cd = pd.DataFrame(cd_rows)[features]
        scores = cd_model.predict_proba(X_cd)[:, 1]
        for r, score in zip(cd_rows, scores):
            r["score"] = round(score, 4)
    else: # Fallback
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
def list_clients_with_suo():
    mk = request.args.get("month") or datetime.now(TZ).strftime("%Y-%m")
    q = (request.args.get("q") or "").strip()
    therapist_id = request.args.get("therapist_id", type=int)
    include_inactive = request.args.get("include_inactive") in ("1","true","yes")

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
      -- NOWA LINIA: Sprawdza, czy klient ma jakikolwiek wpis w planie niedostępności
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


@app.get("/api/clients/<int:cid>")
def get_client(cid):
    sql = """
    SELECT id, full_name, phone, address, active
    FROM clients
    WHERE id = :cid
    """
    with engine.begin() as conn:
        row = conn.execute(text(sql), {"cid": cid}).mappings().first()
        if not row:
            return jsonify({"error": "Nie znaleziono klienta"}), 404
        return jsonify(dict(row)), 200

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
           active    = COALESCE(:active, true)
     WHERE id = :id
    RETURNING id, full_name, phone, address, active;
    """
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {
                "id": cid,
                "full_name": full_name,
                "phone": (data.get("phone") or None),
                "address": (data.get("address") or None),
                "active": data.get("active", True),
            }).mappings().first()
            if not row:
                return jsonify({"error": "Klient nie istnieje."}), 404
            return jsonify(dict(row)), 200
    except IntegrityError as e:
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki klient już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409

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
    with Session() as session:
        therapist = session.query(Therapist).filter_by(id=tid).first()
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
    with Session() as session:
        therapist = session.query(Therapist).filter_by(id=tid).first()
        if not therapist:
            return jsonify({"error": "Therapist not found"}), 404
        session.delete(therapist)
        session.commit()
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

    with Session() as session:
        new_driver = Driver(
            full_name=data["full_name"],
            phone=data.get("phone"),
            active=data.get("active", True)
        )
        session.add(new_driver)
        try:
            session.commit()
            return jsonify({"id": new_driver.id, "full_name": new_driver.full_name}), 201
        except IntegrityError:
            session.rollback()
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409


@app.put("/api/drivers/<int:did>")
def update_driver(did):
    """Aktualizuje dane kierowcy."""
    with Session() as session:
        driver = session.query(Driver).filter_by(id=did).first()
        if not driver:
            return jsonify({"error": "Kierowca nie istnieje."}), 404

        data = request.get_json(silent=True) or {}
        driver.full_name = data.get("full_name", driver.full_name)
        driver.phone = data.get("phone", driver.phone)
        driver.active = data.get("active", driver.active)
        try:
            session.commit()
            return jsonify({"id": driver.id, "full_name": driver.full_name}), 200
        except IntegrityError:
            session.rollback()
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409


@app.delete("/api/drivers/<int:did>")
def delete_driver(did):
    """Usuwa kierowcę."""
    with Session() as session:
        driver = session.query(Driver).filter_by(id=did).first()
        if not driver:
            return jsonify({"error": "Driver not found"}), 404
        session.delete(driver)
        session.commit()
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
        return jsonify({"error":"date and clients[] required"}), 400

    # dla każdego klienta: TOP1 terapeuta i TOP1 kierowca z /api/ai/recommend
    # + szybka kontrola kolizji godzinowej (tu: ta sama godzina)
    plans = []
    hour_start = 9
    for cid in clients:
        rec = app.test_client().get(f"/api/ai/recommend?client_id={cid}&date={date}").get_json()
        th = (rec.get("therapists") or [{}])[0]
        dr = (rec.get("drivers") or [{}])[0]
        start = f"{date}T{str(hour_start).zfill(2)}:00:00"
        end   = f"{date}T{str(hour_start+1).zfill(2)}:00:00"
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

                distance = get_route_distance(block.get("from"), block.get("to"))
                s = datetime.fromisoformat(block["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(block["ends_at"]).replace(tzinfo=TZ)
                payload = {"did": block["driver_id"], "veh": block.get("vehicle_id"), "s": s, "e": e,
                           "from": block.get("from"), "to": block.get("to"), "status": status, "gid": gid, "kind": kind,
                           "distance": distance}

                if ex:
                    conn.execute(text(
                        "UPDATE schedule_slots SET driver_id=:did, vehicle_id=:veh, starts_at=:s, ends_at=:e, place_from=:from, place_to=:to, status=:status, distance_km=:distance WHERE id=:id"),
                                 {**payload, "id": ex["id"]})
                else:
                    conn.execute(text("""
                        INSERT INTO schedule_slots (group_id, client_id, driver_id, vehicle_id, kind, starts_at, ends_at, place_from, place_to, status, distance_km)
                        SELECT :gid, client_id, :did, :veh, :kind, :s, :e, :from, :to, :status, :distance FROM schedule_slots WHERE group_id=:gid AND kind='therapy' LIMIT 1
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
    if semester == 1: # I Półrocze (Wrzesień - Styczeń)
        start_date = date(school_year_start, 9, 1)
        end_date = date(school_year_start + 1, 2, 1) # Kończy się przed 1 lutego
    elif semester == 2: # II Półrocze (Luty - Czerwiec)
        start_date = date(school_year_start + 1, 2, 1)
        end_date = date(school_year_start + 1, 7, 1) # Kończy się przed 1 lipca
    else:
        raise ValueError("Semester must be 1 or 2")
    return start_date, end_date

@app.get("/tus")
def tus_page():
    return app.send_static_file("tus.html")


@app.get("/api/tus/groups")
def get_tus_groups():
    with session_scope() as session:
        groups = session.query(TUSGroup).options(
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

    with session_scope() as session:
        if session.query(TUSGroup).filter_by(name=data["name"]).first():
            return jsonify({"error": f"Grupa o nazwie '{data['name']}' już istnieje."}), 409

        client_ids = [int(cid) for cid in data.get("client_ids", []) if cid is not None]
        members = []
        if client_ids:
            members = session.query(Client).filter(Client.id.in_(client_ids)).all()

        new_group = TUSGroup(
            name=data["name"],
            therapist_id=data["therapist_id"],
            assistant_therapist_id=data.get("assistant_therapist_id"),
            members=members  # POPRAWKA: To zadziała dzięki poprawionej relacji w modelu
        )
        session.add(new_group)
        session.flush()  # Aby uzyskać ID nowej grupy
        return jsonify({"id": new_group.id, "name": new_group.name}), 201


@app.put("/api/tus/groups/<int:group_id>")
def update_tus_group(group_id):
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("therapist_id"):
        return jsonify({"error": "Nazwa grupy i terapeuta są wymagani."}), 400

    with session_scope() as session:
        group = session.get(TUSGroup, group_id)
        if not group:
            return jsonify({"error": "Nie znaleziono grupy."}), 404

        # Sprawdzenie unikalności nowej nazwy
        if session.query(TUSGroup).filter(TUSGroup.name == data["name"], TUSGroup.id != group_id).first():
            return jsonify({"error": f"Grupa o nazwie '{data['name']}' już istnieje."}), 409

        group.name = data["name"]
        group.therapist_id = data["therapist_id"]
        group.assistant_therapist_id = data.get("assistant_therapist_id")

        client_ids = [int(cid) for cid in data.get("client_ids", []) if cid is not None]
        if client_ids:
            group.members = session.query(Client).filter(Client.id.in_(client_ids)).all()
        else:
            group.members = []

        return jsonify({"id": group.id, "name": group.name}), 200


@app.post("/api/tus/sessions")
def create_tus_session():
    data = request.get_json(silent=True) or {}
    try:
        group_id = int(data["group_id"])
        topic_id = int(data["topic_id"])
        dt_raw = data["session_date"]
        # --- POCZĄTEK POPRAWKI ---
        # Odczytujemy listę ID zachowań z frontendu
        behavior_ids = [int(bid) for bid in data.get("behavior_ids", []) if bid]
        if len(behavior_ids) > 4:
            return jsonify({"error": "Można wybrać maksymalnie 4 zachowania."}), 400
        # --- KONIEC POPRAWKI ---

        if "T" in dt_raw:
            dt = datetime.fromisoformat(dt_raw)
            sess_date = dt.date()
            sess_time = dt.time().replace(second=0, microsecond=0)
        else:
            sess_date = date.fromisoformat(dt_raw)
            sess_time = None

    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"error": "Nieprawidłowe lub brakujące dane w zapytaniu.", "details": str(e)}), 400

    with session_scope() as session:
        if not session.get(TUSGroup, group_id):
            return jsonify({"error": f"Grupa o ID {group_id} nie istnieje."}), 404

        # Tworzymy główny obiekt sesji
        new_session = TUSSession(
            group_id=group_id,
            topic_id=topic_id,
            session_date=sess_date,
            session_time=sess_time,
        )
        session.add(new_session)
        session.flush()  # Ważne, aby uzyskać ID nowej sesji (new_session.id)

        # --- POCZĄTEK POPRAWKI ---
        # Teraz, mając ID sesji, zapisujemy powiązane z nią zachowania
        if behavior_ids:
            # Pobieramy domyślne maksymalne punkty dla wybranych zachowań
            behaviors_map = {b.id: b.default_max_points for b in
                             session.query(TUSBehavior).filter(TUSBehavior.id.in_(behavior_ids)).all()}

            for b_id in behavior_ids:
                session_behavior = TUSSessionBehavior(
                    session_id=new_session.id,
                    behavior_id=b_id,
                    # Używamy domyślnej wartości z tabeli `tus_behaviors`
                    max_points=behaviors_map.get(b_id, 3)
                )
                session.add(session_behavior)
        # --- KONIEC POPRAWKI ---

        return jsonify({"id": new_session.id}), 201


@app.put("/api/tus/sessions/<int:session_id>")
def update_tus_session(session_id):
    data = request.get_json(silent=True) or {}
    with session_scope() as session:
        s = session.get(TUSSession, session_id)
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

    with session_scope() as session:
        # Znajdź sesję, którą chcemy usunąć
        session_to_delete = session.get(TUSSession, session_id)
        if not session_to_delete:
            return jsonify({"error": "Session not found"}), 404

        group_id = session_to_delete.group_id

        # --- NOWA LOGIKA DECYZYJNA ---
        if delete_all_bonuses:
            # Użytkownik wybrał "TAK": usuń WSZYSTKIE bonusy w tej grupie
            print(f"DIAGNOSTYKA: Usuwanie wszystkich bonusów dla grupy ID: {group_id}")

            # 1. Usuń bonusy ogólne
            session.query(TUSGeneralBonus).filter(TUSGeneralBonus.group_id == group_id).delete()

            # 2. Usuń bonusy sesyjne (ze wszystkich sesji w tej grupie)
            session_ids_in_group = session.query(TUSSession.id).filter(TUSSession.group_id == group_id)
            session.query(TUSMemberBonus).filter(TUSMemberBonus.session_id.in_(session_ids_in_group)).delete()

        # Niezależnie od decyzji, ZAWSZE usuwamy sesję.
        # Jeśli użytkownik wybrał "NIE", kaskada w bazie danych usunie
        # bonusy i punkty TYLKO dla tej jednej usuwanej sesji.
        session.delete(session_to_delete)

    return jsonify({"ok": True}), 200


@app.put("/api/tus/groups/<int:gid>/target")
def tus_update_targets(gid):
    """Zapisuje lub aktualizuje cel dla grupy w nowej tabeli."""
    data = request.get_json(silent=True) or {}
    try:
        school_year_start = int(data["school_year_start"])  # np. 2025
        semester = int(data["semester"])  # 1 lub 2
        points = int(data["points"])
        reward = (data.get("reward") or "").strip()
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "Brakujące lub nieprawidłowe dane."}), 400

    with session_scope() as session:
        target = session.query(TUSGroupTarget).filter_by(
            group_id=gid,
            school_year_start=school_year_start,
            semester=semester
        ).first()

        if target:  # Aktualizuj istniejący
            target.target_points = points
            target.reward = reward
        else:  # Stwórz nowy
            target = TUSGroupTarget(
                group_id=gid,
                school_year_start=school_year_start,
                semester=semester,
                target_points=points,
                reward=reward
            )
            session.add(target)

    return jsonify({"ok": True})


@app.get("/api/tus/groups/<int:group_id>")
def get_tus_group_details(group_id: int):
    with SessionLocal() as session:
        # Używamy opcji `selectinload` dla lepszej wydajności i uniknięcia duplikatów
        group = session.query(TUSGroup).options(
            joinedload(TUSGroup.therapist),
            joinedload(TUSGroup.assistant_therapist),
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client),
            joinedload(TUSGroup.sessions).joinedload(TUSSession.topic)
        ).filter(TUSGroup.id == group_id).first()

        if not group:
            return jsonify({"error": "Group not found"}), 404

        # POPRAWKA: Ręczne usunięcie duplikatów przed wysłaniem do frontendu
        unique_sessions = {sess.id: sess for sess in group.sessions}.values()

        sessions_json = sorted([
            {
                "id": s.id,
                "session_date": s.session_date.isoformat(),
                "session_time": s.session_time.strftime('%H:%M') if s.session_time else None,
                "topic_title": s.topic.title if s.topic else "bez tematu",
                "bonuses_awarded": s.bonuses_awarded or 0
            } for s in unique_sessions
        ], key=lambda x: (x.get('session_date'), x.get('session_time')), reverse=True)

        # Usunięcie duplikatów członków (na wszelki wypadek)
        # POPRAWIONA, JEDNA LINIA
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
    with session_scope() as session:
        group = session.get(TUSGroup, gid)
        if not group: return jsonify({"error": "Not found"}), 404

        for semester in [1, 2]:
            start_date, end_date = get_semester_dates(school_year_start, semester)

            # Pobierz cel dla tego semestru
            target_obj = session.query(TUSGroupTarget).filter_by(
                group_id=gid, school_year_start=school_year_start, semester=semester
            ).first()

            # Zlicz punkty bonusowe w zakresie dat
            session_bonus_q = select(func.sum(TUSMemberBonus.points)).join(TUSSession).where(
                TUSSession.group_id == gid, TUSSession.session_date.between(start_date, end_date)
            )
            general_bonus_q = select(func.sum(TUSGeneralBonus.points)).where(
                TUSGeneralBonus.group_id == gid, TUSGeneralBonus.awarded_at.between(start_date, end_date)
            )
            session_pts = session.execute(session_bonus_q).scalar() or 0
            general_pts = session.execute(general_bonus_q).scalar() or 0
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
        client_id  = int(data.get("client_id"))
        points     = int(data.get("points"))
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




def _half_bounds(year:int, half:int):
    if half == 1:
        a = datetime(year,1,1,tzinfo=TZ); b = datetime(year,7,1,tzinfo=TZ)
    else:
        a = datetime(year,7,1,tzinfo=TZ); b = datetime(year+1,1,1,tzinfo=TZ)
    return a,b

# CRUD dla tematów (prosty przykład)
@app.get("/api/tus/topics")
def get_tus_topics():
    session = Session()
    topics = session.query(TUSTopic).all()
    result = [{"id": t.id, "title": t.title} for t in topics]
    session.close()
    return jsonify(result)


@app.post("/api/tus/topics")
def create_tus_topic():
    data = request.get_json(silent=True) or {}
    session = Session()
    try:
        new_topic = TUSTopic(title=data["title"])
        session.add(new_topic)
        session.commit()
        result = {"id": new_topic.id, "title": new_topic.title}
        session.close()
        return jsonify(result), 201
    except IntegrityError:  # Obsługa duplikatów
        session.rollback()
        session.close()
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
        return jsonify({"error":"title required"}), 400
    with Session() as s:
        b = TUSBehavior(title=title, default_max_points=dmp)
        s.add(b)
        try:
            s.commit()
            return jsonify({"id": b.id, "title": b.title, "default_max_points": b.default_max_points}), 201
        except IntegrityError:
            s.rollback()
            return jsonify({"error":"behavior already exists"}), 409

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
        return jsonify({"error":"max 4 behaviors per session"}), 400
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

def _half_bounds(year:int, half:int):
    if half == 1:
        a = datetime(year,1,1,tzinfo=TZ); b = datetime(year,7,1,tzinfo=TZ)
    else:
        a = datetime(year,7,1,tzinfo=TZ); b = datetime(year+1,1,1,tzinfo=TZ)
    return a,b

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

# === CLIENT PACKAGES (grupy+sloty klienta) ===
@app.get("/api/client/<int:cid>/packages")
def client_packages(cid):
    mk = request.args.get("month")  # 'YYYY-MM' albo None

    sql = text("""
        -- 1. ZAJĘCIA INDYWIDUALNE
        SELECT
          'individual' as type,
          -- POCZĄTEK POPRAWKI: Konwertujemy UUID na TEXT
          eg.id::text AS group_id,
          -- KONIEC POPRAWKI
          eg.label,
          ss.id AS slot_id,
          ss.kind,
          ss.starts_at,
          ss.ends_at,
          ss.status,
          ss.therapist_id,
          t.full_name AS therapist_name,
          ss.driver_id,
          d.full_name AS driver_name,
          ss.place_from,
          ss.place_to
        FROM event_groups eg
        JOIN schedule_slots ss ON ss.group_id = eg.id
        LEFT JOIN therapists t ON t.id = ss.therapist_id
        LEFT JOIN drivers d    ON d.id = ss.driver_id
        WHERE eg.client_id = :cid
          AND (:mk IS NULL OR to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk)

        UNION ALL

        -- 2. ZAJĘCIA GRUPOWE TUS
        SELECT
          'tus' as type,
          -- POCZĄTEK POPRAWKI: Konwertujemy INTEGER na TEXT
          g.id::text AS group_id,
          -- KONIEC POPRAWKI
          g.name AS label,
          s.id AS slot_id,
          'therapy' as kind,
          (s.session_date + COALESCE(s.session_time, '00:00:00'::time)) AT TIME ZONE 'Europe/Warsaw' AS starts_at,
          (s.session_date + COALESCE(s.session_time, '00:00:00'::time) + INTERVAL '60 minutes') AT TIME ZONE 'Europe/Warsaw' AS ends_at,
          'planned' as status,
          g.therapist_id,
          th.full_name AS therapist_name,
          NULL AS driver_id,
          NULL AS driver_name,
          'Poradnia' AS place_from,
          'Poradnia' AS place_to
        FROM tus_sessions s
        JOIN tus_groups g ON s.group_id = g.id
        JOIN tus_group_members gm ON gm.group_id = g.id
        LEFT JOIN therapists th ON g.therapist_id = th.id
        WHERE gm.client_id = :cid
          AND (:mk IS NULL OR to_char(s.session_date, 'YYYY-MM') = :mk)

        ORDER BY starts_at;
    """)

    with engine.begin() as conn:
        rows = conn.execute(sql, {"cid": cid, "mk": mk}).mappings().all()
        results = [
            {**r,
             'starts_at': r['starts_at'].isoformat() if r.get('starts_at') else None,
             'ends_at': r['ends_at'].isoformat() if r.get('ends_at') else None
             } for r in rows
        ]
        return jsonify(results)

# === DRIVER SCHEDULE (kursy kierowcy z klientami) ===
@app.get("/api/drivers/<int:did>/schedule")
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
      ss.group_id
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

def find_overlaps(conn, *, driver_id=None, therapist_id=None, starts_at=None, ends_at=None):
    """
    Zwraca listę kolidujących slotów dla driver_id/therapist_id i podanego zakresu czasu.
    """
    # jeśli nie mamy pełnego zakresu – nic nie sprawdzamy (zapobiega błędowi z ':s')
    if starts_at is None or ends_at is None:
        return []

    where, params = [], {"s": starts_at, "e": ends_at}
    if driver_id is not None:
        where.append("ss.driver_id = :driver_id")
        params["driver_id"] = driver_id
    if therapist_id is not None:
        where.append("ss.therapist_id = :therapist_id")
        params["therapist_id"] = therapist_id
    if not where:
        return []

    sql = f"""
    SELECT
      ss.id, ss.kind, ss.starts_at, ss.ends_at, ss.status,
      ss.driver_id, d.full_name AS driver_name,
      ss.therapist_id, t.full_name AS therapist_name,
      ss.client_id, c.full_name AS client_name
    FROM schedule_slots ss
    LEFT JOIN drivers d    ON d.id = ss.driver_id
    LEFT JOIN therapists t ON t.id = ss.therapist_id
    LEFT JOIN clients c    ON c.id = ss.client_id
    WHERE {" AND ".join(where)}
      AND tstzrange(ss.starts_at, ss.ends_at, '[)') &&
          tstzrange(:s, :e, '[)')
    ORDER BY ss.starts_at
    """
    stmt = text(sql).bindparams(
        bindparam("s", type_=TIMESTAMP(timezone=True)),
        bindparam("e", type_=TIMESTAMP(timezone=True)),
    )
    return [dict(r) for r in conn.execute(stmt, params).mappings().all()]

@app.post("/api/schedule/check")
def check_schedule_conflicts():
    """
    JSON (jak przy zapisie pakietu), zwraca { conflicts: {...} } bez zapisu:
    {
      "therapy": {...}, "pickup": {...?}, "dropoff": {...?}
    }
    """
    data = request.get_json(silent=True) or {}
    therapy = data.get("therapy") or {}
    pickup  = data.get("pickup") or None
    dropoff = data.get("dropoff") or None

    result = {"therapy": [], "pickup": [], "dropoff": []}

    with engine.begin() as conn:
      # terapeuta
      if therapy and therapy.get("therapist_id"):
          s = datetime.fromisoformat(therapy["starts_at"]).replace(tzinfo=TZ)
          e = datetime.fromisoformat(therapy["ends_at"]).replace(tzinfo=TZ)
          result["therapy"] = find_overlaps(conn,
                              therapist_id=int(therapy["therapist_id"]),
                              starts_at=s, ends_at=e)

      # pickup kierowca
      if pickup and pickup.get("driver_id"):
          s = datetime.fromisoformat(pickup["starts_at"]).replace(tzinfo=TZ)
          e = datetime.fromisoformat(pickup["ends_at"]).replace(tzinfo=TZ)
          result["pickup"] = find_overlaps(conn,
                              driver_id=int(pickup["driver_id"]),
                              starts_at=s, ends_at=e)

      # dropoff kierowca
      if dropoff and dropoff.get("driver_id"):
          s = datetime.fromisoformat(dropoff["starts_at"]).replace(tzinfo=TZ)
          e = datetime.fromisoformat(dropoff["ends_at"]).replace(tzinfo=TZ)
          result["dropoff"] = find_overlaps(conn,
                               driver_id=int(dropoff["driver_id"]),
                               starts_at=s, ends_at=e)

    # policz łączną liczbę kolizji
    total = sum(len(v) for v in result.values())
    return jsonify({"conflicts": result, "total": total}), 200

def ensure_shared_run_id_for_driver(conn, driver_id, starts_at, ends_at):
    """
    Jeżeli u kierowcy istnieje slot dokładnie o tym samym oknie czasu,
    to zwróć jego run_id (a gdy go nie ma, ustaw nowy na obu slotach).
    Jeśli brak takiego slotu – zwróć None (pojedynczy kurs).
    """
    q = text("""
      SELECT id, run_id
      FROM schedule_slots
      WHERE driver_id = :did
        AND starts_at = :s
        AND ends_at   = :e
      LIMIT 1
    """)
    row = conn.execute(q, {"did": driver_id, "s": starts_at, "e": ends_at}).mappings().first()
    if not row:
        return None

    # jeśli tamten slot nie ma run_id – nadaj nowy i zwróć go
    if row["run_id"] is None:
        new_run = str(uuid.uuid4())
        conn.execute(
            text("UPDATE schedule_slots SET run_id = :rid WHERE id = :id"),
            {"rid": new_run, "id": row["id"]}
        )
        return new_run

    return row["run_id"]

def ensure_shared_session_id_for_therapist(conn, therapist_id, starts_at, ends_at):
    """
    Jeśli istnieje slot terapeuty o tym samym oknie czasu, zwróć jego session_id.
    Gdy brak session_id → ustaw nowe (UUID) na tamtym slocie i zwróć je.
    Gdy brak takiego slotu → zwróć None (zajęcia indywidualne).
    """
    q = text("""
      SELECT id, session_id
      FROM schedule_slots
      WHERE therapist_id = :tid
        AND starts_at = :s
        AND ends_at   = :e
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
      return jsonify({"error":"No fields"}), 400
    sql = f"UPDATE schedule_slots SET {', '.join(fields)} WHERE id=:sid RETURNING id;"
    with engine.begin() as conn:
        row = conn.execute(text(sql), params).mappings().first()
        if not row: return jsonify({"error":"Not found"}), 404
        return jsonify({"ok": True, "id": row["id"]}), 200


# === SLOT STATUS ===
@app.patch("/api/slots/<int:sid>/status")
def update_slot_status(sid):
    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in ("planned", "done", "cancelled"):
        return jsonify({"error": "Invalid status"}), 400

    sql = """
    UPDATE schedule_slots
    SET status = :st
    WHERE id = :sid
    RETURNING id, status;
    """
    with engine.begin() as conn:
        row = conn.execute(text(sql), {"st": new_status, "sid": sid}).mappings().first()
        if not row:
            return jsonify({"error": "Slot not found"}), 404
        return jsonify({"id": row["id"], "status": row["status"]}), 200

#zmiana widkou kart grup
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
    with SessionLocal() as session:
        # 1. Spotkania indywidualne (ze schedule_slots)
        individual_sessions = session.execute(
            select(
                ScheduleSlot.starts_at,
                ScheduleSlot.status,
                Therapist.full_name.label("therapist_name")
            )
            .join(Therapist, Therapist.id == ScheduleSlot.therapist_id)
            .where(
                ScheduleSlot.client_id == client_id,
                ScheduleSlot.kind == 'therapy',
                ScheduleSlot.session_id.is_(None)  # Kluczowe: tylko sesje bez session_id są indywidualne
            )
        ).all()

        # 2. Spotkania grupowe TUS
        tus_sessions = session.execute(
            select(
                TUSSession.session_date,
                TUSSession.session_time,
                TUSTopic.title.label("topic_title"),
                TUSGroup.name.label("group_name")
            )
            .join(TUSGroup, TUSGroup.id == TUSSession.group_id)
            .join(TUSGroupMember, TUSGroupMember.group_id == TUSGroup.id)
            .join(TUSTopic, TUSTopic.id == TUSSession.topic_id, isouter=True)
            .where(TUSGroupMember.client_id == client_id)
        ).all()

        # 3. Formatowanie danych
        history = {
            "individual": [
                {
                    "date": s.starts_at.isoformat(),
                    "status": s.status,
                    "therapist": s.therapist_name
                } for s in individual_sessions
            ],
            "tus_group": [
                {
                    "date": s.session_date.isoformat(),
                    "time": s.session_time.strftime('%H:%M') if s.session_time else None,
                    "topic": s.topic_title or "Brak tematu",
                    "group": s.group_name
                } for s in tus_sessions
            ]
        }

        return jsonify(history)


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


@app.get("/api/therapists/<int:tid>/schedule")
def therapist_schedule(tid):
    mk = request.args.get("month")
    if not mk:
        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

    all_results = []

    with engine.begin() as conn:
        # --- ZAPYTANIE 1: Zajęcia indywidualne ---
        sql_individual = text("""
            SELECT
                ss.id AS slot_id, 'individual' as type, ss.kind,
                ss.starts_at, ss.ends_at, ss.status, c.full_name AS client_name,
                ss.place_to, g.label AS group_name
            FROM schedule_slots ss
            JOIN clients c ON c.id = ss.client_id
            LEFT JOIN event_groups g ON g.id = ss.group_id
            WHERE ss.therapist_id = :tid
              AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM') = :mk
        """)
        individual_rows = conn.execute(sql_individual, {"tid": tid, "mk": mk}).mappings().all()
        all_results.extend(individual_rows)
        # --- LINIA DIAGNOSTYCZNA ---
        print(
            f"DIAGNOSTYKA: Znaleziono {len(individual_rows)} wpisów indywidualnych dla terapeuty ID {tid} w miesiącu {mk}.")

        # --- ZAPYTANIE 2: Zajęcia grupowe TUS ---
        sql_tus = text("""
            SELECT
                s.id AS slot_id, 'tus' as type, 'therapy' as kind,
                (s.session_date + COALESCE(s.session_time, '00:00:00'::time)) AT TIME ZONE 'Europe/Warsaw' AS starts_at,
                (s.session_date + COALESCE(s.session_time, '00:00:00'::time) + INTERVAL '60 minutes') AT TIME ZONE 'Europe/Warsaw' AS ends_at,
                'planned' as status, g.name AS client_name,
                'Poradnia' as place_to, g.name AS group_name
            FROM tus_sessions s
            JOIN tus_groups g ON s.group_id = g.id
            WHERE (g.therapist_id = :tid OR g.assistant_therapist_id = :tid)
              AND to_char(s.session_date, 'YYYY-MM') = :mk
        """)
        tus_rows = conn.execute(sql_tus, {"tid": tid, "mk": mk}).mappings().all()
        all_results.extend(tus_rows)
        # --- LINIA DIAGNOSTYCZNA ---
        print(f"DIAGNOSTYKA: Znaleziono {len(tus_rows)} wpisów TUS dla terapeuty ID {tid} w miesiącu {mk}.")

    # Sortowanie wyników w Pythonie
    all_results.sort(key=lambda r: r.get('starts_at') or datetime.min.replace(tzinfo=ZoneInfo("Europe/Warsaw")))

    # Formatowanie dat na stringi
    results = [
        {**r,
         'starts_at': r['starts_at'].isoformat() if r.get('starts_at') else None,
         'ends_at': r['ends_at'].isoformat() if r.get('ends_at') else None
         } for r in all_results
    ]
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
    gid = uuid.uuid4()                      # OBIEKT UUID (nie string)
    status = data.get("status", "planned")

    try:
        with engine.begin() as conn:
            # 1) event_groups (MUSI być najpierw – FK)
            conn.execute(text("""
                INSERT INTO event_groups (id, client_id, label)
                VALUES (:id, :client_id, :label)
            """), {
                "id": gid,
                "client_id": data["client_id"],
                "label": data.get("label")
            })

            # 2) THERAPY (z obsługą zajęć grupowych -> session_id)
            t = data["therapy"]
            ts = datetime.fromisoformat(t["starts_at"]).replace(tzinfo=TZ)
            te = datetime.fromisoformat(t["ends_at"]).replace(tzinfo=TZ)

            session_id = ensure_shared_session_id_for_therapist(
                conn, int(t["therapist_id"]), ts, te
            )

            conn.execute(text("""
              INSERT INTO schedule_slots (
                group_id, client_id, therapist_id, driver_id, vehicle_id,
                kind, starts_at, ends_at, place_from, place_to, status, session_id
              )
              VALUES (
                :group_id, :client_id, :therapist_id, NULL, NULL,
                'therapy', :starts_at, :ends_at, NULL, :place, :status, :session_id
              )
            """), {
                "group_id": gid,
                "client_id": data["client_id"],
                "therapist_id": t["therapist_id"],
                "starts_at": ts, "ends_at": te,
                "place": t.get("place"),
                "status": status,
                "session_id": session_id  # None = indywidualne; UUID = grupa
            })

            # 3) PICKUP (opcjonalnie) – wspólny kurs -> run_id
            if data.get("pickup"):
                p = data["pickup"]
                # NOWOŚĆ: Oblicz dystans
                distance = get_route_distance(p.get("from"), p.get("to"))

                s = datetime.fromisoformat(p["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(p["ends_at"]).replace(tzinfo=TZ)
                run_id = ensure_shared_run_id_for_driver(conn, int(p["driver_id"]), s, e)

                conn.execute(text("""
                                 INSERT INTO schedule_slots (
                                   group_id, client_id, driver_id, vehicle_id, kind, 
                                   starts_at, ends_at, place_from, place_to, status, run_id, distance_km
                                 )
                                 VALUES (
                                   :group_id, :client_id, :driver_id, :vehicle_id, 'pickup', 
                                   :starts_at, :ends_at, :from, :to, :status, :run_id, :distance
                                 )
                               """), {
                    "group_id": gid,
                    "client_id": data["client_id"],
                    "driver_id": p["driver_id"],
                    "vehicle_id": p.get("vehicle_id"),
                    "starts_at": s, "ends_at": e,
                    "from": p.get("from"), "to": p.get("to"),
                    "status": status,
                    "run_id": run_id,
                    "distance": distance
                })

            # 4) DROPOFF (opcjonalnie) – wspólny kurs -> run_id
            if data.get("dropoff"):
                d = data["dropoff"]
                distance = get_route_distance(d.get("from"), d.get("to"))
                s = datetime.fromisoformat(d["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(d["ends_at"]).replace(tzinfo=TZ)
                run_id = ensure_shared_run_id_for_driver(conn, int(d["driver_id"]), s, e)

                conn.execute(text("""
                                  INSERT INTO schedule_slots (
                                    group_id, client_id, driver_id, vehicle_id, kind, 
                                    starts_at, ends_at, place_from, place_to, status, run_id, distance_km
                                  )
                                  VALUES (
                                    :group_id, :client_id, :driver_id, :vehicle_id, 'dropoff', 
                                    :starts_at, :ends_at, :from, :to, :status, :run_id, :distance
                                  )
                                """), {
                    "group_id": gid,
                    "client_id": data["client_id"],
                    "driver_id": d["driver_id"],
                    "vehicle_id": d.get("vehicle_id"),
                    "starts_at": s, "ends_at": e,
                    "from": d.get("from"), "to": d.get("to"),
                    "status": status,
                    "run_id": run_id,
                    "distance": distance
                })

        return jsonify({"group_id": str(gid), "ok": True}), 201

    except IntegrityError as e:
        # 23503: FOREIGN_KEY_VIOLATION (np. nieistniejący client_id/therapist_id/driver_id)
        if getattr(e.orig, "pgcode", None) == errorcodes.FOREIGN_KEY_VIOLATION:
            return jsonify({"error": "Naruszenie klucza obcego (sprawdź ID klienta/terapeuty/kierowcy/pojazdu).",
                            "details": str(e.orig)}), 400
        # 23P01: EXCLUSION_VIOLATION (gdyby jednak overlapy bez session_id/run_id)
        if getattr(e.orig, "pgcode", None) == errorcodes.EXCLUSION_VIOLATION:
            return jsonify({"error": "Konflikt czasowy (zasób zajęty)."}), 409
        return jsonify({"error": "Błąd bazy danych", "details": str(e.orig)}), 400


# NOWY ENDPOINT W odnowa.py
@app.get("/api/clients/<int:client_id>/tus-groups")
def get_client_tus_groups(client_id):
    """Zwraca listę grup TUS, do których należy dany klient."""
    with session_scope() as session:
        groups = session.query(TUSGroup) \
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
    with session_scope() as session:
        bonuses = session.query(TUSMemberBonus) \
            .filter(TUSMemberBonus.session_id == session_id).all()

        result = {b.client_id: b.points for b in bonuses}
        return jsonify(result)


@app.post("/api/tus/sessions/<int:session_id>/bonuses")
def save_session_bonuses(session_id):
    """Zapisuje 'hurtowo' bonusy indywidualne dla uczestników sesji."""
    data = request.get_json(silent=True) or {}
    bonuses_data = data.get("bonuses", [])  # Oczekujemy listy: [{"client_id": 1, "points": 5}, ...]

    with session_scope() as session:
        # 1. Usuń stare bonusy dla tej sesji, aby uniknąć duplikatów
        session.query(TUSMemberBonus).filter(TUSMemberBonus.session_id == session_id).delete()

        # 2. Dodaj nowe bonusy
        for bonus in bonuses_data:
            if bonus.get("points", 0) > 0:  # Zapisuj tylko, jeśli punkty są większe od 0
                new_bonus = TUSMemberBonus(
                    session_id=session_id,
                    client_id=bonus["client_id"],
                    points=bonus["points"]
                )
                session.add(new_bonus)

    return jsonify({"ok": True}), 200


# NOWY ENDPOINT DO WKLEJENIA W odnowa.py

@app.get("/api/tus/sessions/<int:session_id>")
def get_tus_session_details(session_id: int):
    """Zwraca szczegóły pojedynczej sesji TUS, w tym listę jej uczestników."""
    with session_scope() as session:
        # Krok 1: Pobierz sesję i od razu jej temat (prosta relacja)
        session_obj = session.query(TUSSession).options(
            joinedload(TUSSession.topic)
        ).filter(TUSSession.id == session_id).first()

        if not session_obj:
            return jsonify({"error": "Session not found"}), 404

        # Krok 2: Pobierz grupę tej sesji i jej członków
        # To zapytanie jest bezpieczniejsze i korzysta z poprawnie skonfigurowanej relacji
        group = session.query(TUSGroup).options(
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

    with session_scope() as session:
        group = session.query(TUSGroup).options(
            joinedload(TUSGroup.member_associations).joinedload(TUSGroupMember.client)
        ).filter(TUSGroup.id == group_id).first()

        if not group:
            print("!!! BŁĄD: Nie znaleziono grupy.")
            return jsonify({"error": "Group not found"}), 404

        member_ids = [member.id for member in group.members]
        print(f"Znaleziono członków o ID: {member_ids}")
        if not member_ids:
            return jsonify([])

        # Subzapytania... (bez zmian)
        behavior_scores_sq = session.query(TUSSessionMemberScore.client_id,
                                           func.sum(TUSSessionMemberScore.points).label("total_behavior")).join(
            TUSSession, TUSSession.id == TUSSessionMemberScore.session_id).filter(
            TUSSession.group_id == group_id).group_by(TUSSessionMemberScore.client_id).subquery()
        session_bonuses_sq = session.query(TUSMemberBonus.client_id,
                                           func.sum(TUSMemberBonus.points).label("total_session_bonus")).join(
            TUSSession, TUSSession.id == TUSMemberBonus.session_id).filter(TUSSession.group_id == group_id).group_by(
            TUSMemberBonus.client_id).subquery()
        general_bonuses_sq = session.query(TUSGeneralBonus.client_id,
                                           func.sum(TUSGeneralBonus.points).label("total_general_bonus")).filter(
            TUSGeneralBonus.group_id == group_id).group_by(TUSGeneralBonus.client_id).subquery()

        results_query = session.query(
            Client.id, Client.full_name,
            func.coalesce(behavior_scores_sq.c.total_behavior, 0),
            func.coalesce(session_bonuses_sq.c.total_session_bonus, 0),
            func.coalesce(general_bonuses_sq.c.total_general_bonus, 0)
        ).outerjoin(behavior_scores_sq, Client.id == behavior_scores_sq.c.client_id) \
            .outerjoin(session_bonuses_sq, Client.id == session_bonuses_sq.c.client_id) \
            .outerjoin(general_bonuses_sq, Client.id == general_bonuses_sq.c.client_id) \
            .filter(Client.id.in_(member_ids)).order_by(Client.full_name)

        final_results = []
        print("\n--- Rozpoczynam obliczenia dla każdego członka: ---")
        for client_id, full_name, behavior_pts, session_pts, general_pts in results_query.all():
            print(f"\n  Obliczam dla: {full_name} (ID: {client_id})")
            print(f"    - Pobrane pkt. za zachowania: {behavior_pts}")
            print(f"    - Pobrane bonusy z sesji: {session_pts}")
            print(f"    - Pobrane bonusy ogólne: {general_pts}")

            total_points = int(session_pts) + int(general_pts)

            print(f"    - Obliczona suma (sesja + ogólne): {session_pts} + {general_pts} = {total_points}")

            final_results.append({
                "client_id": client_id, "full_name": full_name,
                "behavior_points": int(behavior_pts),
                "session_bonus_points": int(session_pts),
                "general_bonus_points": int(general_pts),
                "total_points": total_points
            })

        print("\n--- Zakończono obliczenia. Wynik końcowy zostanie wysłany do przeglądarki. ---")
        return jsonify(final_results)


@app.post("/api/tus/groups/<int:group_id>/award-general-bonus")
def award_general_bonus(group_id: int):
    """
    Przyznaje bonus ogólny (niepowiązany z sesją) dla członka grupy.
    """
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

    with session_scope() as session:
        # Sprawdź, czy klient należy do grupy (dla bezpieczeństwa)
        is_member = session.query(TUSGroupMember).filter_by(
            group_id=group_id, client_id=client_id
        ).first()

        if not is_member:
            return jsonify({"error": "Client is not a member of this group"}), 403

        # Dodaj nowy bonus ogólny
        new_bonus = TUSGeneralBonus(
            client_id=client_id,
            group_id=group_id,
            points=points,
            reason=reason
        )
        session.add(new_bonus)

    return jsonify({"ok": True}), 201


@app.get("/api/tus/groups/<int:group_id>/general-bonus-history")
def get_general_bonus_history(group_id: int):
    """Zwraca historię przyznanych bonusów ogólnych dla grupy."""
    with session_scope() as session:
        history = session.query(
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





