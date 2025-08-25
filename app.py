# app.py
import math
from math import exp

import pandas as pd
import psycopg2
from psycopg2 import errorcodes

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, text, bindparam, TIMESTAMP
from sqlalchemy.exc import IntegrityError
import uuid
import os
import joblib





TZ = ZoneInfo("Europe/Warsaw")

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:EDUQ@localhost:5432/suo?client_encoding=utf8")
engine = create_engine(DATABASE_URL, future=True)

# === WCZYTANIE MODELI AI ===
# Upewnij się, że ścieżki są poprawne względem lokalizacji app.py
CT_MODEL_PATH = "models/ct_recommender.pkl"
CD_MODEL_PATH = "models/cd_recommender.pkl" # Dla kierowców

ct_model = None
cd_model = None

try:
    if os.path.exists(CT_MODEL_PATH):
        ct_model = joblib.load(CT_MODEL_PATH)
        print("Model rekomendacji terapeutów został pomyślnie wczytany.")
except Exception as e:
    print(f"BŁĄD: Nie można wczytać modelu terapeutów: {e}")

try:
    if os.path.exists(CD_MODEL_PATH):
        cd_model = joblib.load(CD_MODEL_PATH)
        print("Model rekomendacji kierowców został pomyślnie wczytany.")
except Exception as e:
    print(f"BŁĄD: Nie można wczytać modelu kierowców: {e}")

def _time_bucket(hhmm: str) -> str:
    # zaokrąglanie do 30 minut (np. 09:10 -> 09:00; 09:40 -> 09:30)
    h, m = map(int, hhmm.split(":"))
    m = 0 if m < 30 else 30
    return f"{h:02d}:{m:02d}"

def _date_str(dt):  # pomocniczo
    return dt.strftime("%Y-%m-%d")

def _score(freq, maxfreq, recency_days):
    """
    Prosty „Bayes-lite”: częstość + delikatny bonus za świeżość.
    Skala ~0-1. Smoothing, żeby nie faworyzować jednokrotnych zdarzeń.
    """
    if maxfreq <= 0:
        base = 0.0
    else:
        base = (freq + 1.0) / (maxfreq + 2.0)  # Laplace-like smoothing
    # recency bonus: im świeższe, tym większy (zanik wykładniczy)
    # 0 dni -> ~0.3, 30 dni -> ~0.11, 90 dni -> ~0.04
    rec_bonus = 0.3 * exp(-recency_days / 30.0) if recency_days is not None else 0.0
    return min(1.0, base + rec_bonus)

def _parse_time(s: str):
    h, m = map(int, s.split(":"))
    return h, m

def _to_tstz(date_yyyy_mm_dd: str, hhmm: str, tz=TZ):
    h, m = _parse_time(hhmm)
    d = datetime.fromisoformat(date_yyyy_mm_dd)  # na północy lokalnie
    return d.replace(hour=h, minute=m, second=0, tzinfo=tz)

def _availability_conflicts(conn, therapist_id=None, driver_id=None, starts_at=None, ends_at=None):
    return find_overlaps(conn,
                         therapist_id=therapist_id,
                         driver_id=driver_id,
                         starts_at=starts_at, ends_at=ends_at)


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
    data = request.get_json(force=True)
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

@app.get("/")
def index():
    return app.send_static_file("index.html")

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

@app.put("/api/clients/<int:cid>", endpoint="clients_update")
def update_client_api(cid):
    data = request.get_json(force=True)
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
        if getattr(e.orig, "pgcode", None) == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki klient już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409


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
    data = request.get_json(force=True)
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
    data = request.get_json(force=True)
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

@app.get("/api/groups/<string:gid>")
def get_group(gid):
    # Zwraca strukturę zgodną z payloadem do create_group_with_slots
    sql = """
    SELECT
      eg.id AS group_id,
      eg.label,
      ss.id AS slot_id,
      ss.kind,
      ss.therapist_id,
      ss.driver_id,
      ss.vehicle_id,
      to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM-DD"T"HH24:MI:SS') AS starts_at,
      to_char(ss.ends_at   AT TIME ZONE 'Europe/Warsaw','YYYY-MM-DD"T"HH24:MI:SS') AS ends_at,
      ss.place_from, ss.place_to, ss.status
    FROM event_groups eg
    LEFT JOIN schedule_slots ss ON ss.group_id = eg.id
    WHERE eg.id = :gid
    ORDER BY ss.starts_at NULLS FIRST;
    """
    with engine.begin() as conn:
        rows = conn.execute(text(sql), {"gid": gid}).mappings().all()
        if not rows:
            return jsonify({"error": "Nie znaleziono grupy."}), 404

        # zbuduj payload
        label = rows[0]["label"]
        status = None
        therapy = None
        pickup = None
        dropoff = None
        for r in rows:
            if not r["kind"]:
                continue
            status = status or r["status"]
            if r["kind"] == "therapy":
                therapy = {
                    "slot_id": r["slot_id"],
                    "therapist_id": r["therapist_id"],
                    "starts_at": r["starts_at"],
                    "ends_at": r["ends_at"],
                    "place": r["place_to"]
                }
            elif r["kind"] == "pickup":
                pickup = {
                    "slot_id": r["slot_id"],
                    "driver_id": r["driver_id"],
                    "vehicle_id": r["vehicle_id"],
                    "starts_at": r["starts_at"],
                    "ends_at": r["ends_at"],
                    "from": r["place_from"],
                    "to": r["place_to"]
                }
            elif r["kind"] == "dropoff":
                dropoff = {
                    "slot_id": r["slot_id"],
                    "driver_id": r["driver_id"],
                    "vehicle_id": r["vehicle_id"],
                    "starts_at": r["starts_at"],
                    "ends_at": r["ends_at"],
                    "from": r["place_from"],
                    "to": r["place_to"]
                }

        # client_id nie jest wprost w selekcie; dociągnij z jednego ze slotów
        get_client_sql = "SELECT client_id FROM schedule_slots WHERE group_id=:gid LIMIT 1"
        client_id = None
        with engine.begin() as conn2:
            row = conn2.execute(text(get_client_sql), {"gid": gid}).mappings().first()
            client_id = row["client_id"] if row else None

        return jsonify({
            "group_id": gid,
            "client_id": client_id,
            "label": label,
            "status": status or "planned",
            "therapy": therapy,
            "pickup": pickup,
            "dropoff": dropoff
        }), 200

@app.put("/api/groups/<string:gid>")
def update_group(gid):
    """
    Payload jak przy tworzeniu:
    {
      "label": "...",
      "status": "planned|done|cancelled",
      "therapy":  {"slot_id"?, "therapist_id", "starts_at", "ends_at", "place"},
      "pickup":   null lub {"slot_id"?, "driver_id", "vehicle_id"?, "starts_at","ends_at","from","to"},
      "dropoff":  null lub jw.
    }
    """
    data = request.get_json(force=True)
    label = data.get("label")
    status = data.get("status", "planned")
    therapy = data.get("therapy")
    pickup  = data.get("pickup")
    dropoff = data.get("dropoff")

    if not therapy or not therapy.get("therapist_id"):
        return jsonify({"error": "Pakiet musi zawierać terapię z terapeutą."}), 400

    try:
        with engine.begin() as conn:
            # 0) upewnij się, że grupa istnieje
            ok = conn.execute(text("SELECT 1 FROM event_groups WHERE id=:gid"), {"gid": gid}).scalar()
            if not ok:
                return jsonify({"error": "Nie znaleziono grupy."}), 404

            # 1) nazwa grupy
            conn.execute(text("UPDATE event_groups SET label=:label WHERE id=:gid"),
                         {"label": label, "gid": gid})

            # 2) THERAPY (update istniejącego slotu po slot_id albo po kind)
            ts = datetime.fromisoformat(therapy["starts_at"]).replace(tzinfo=TZ)
            te = datetime.fromisoformat(therapy["ends_at"]).replace(tzinfo=TZ)
            session_id = ensure_shared_session_id_for_therapist(
                conn, int(therapy["therapist_id"]), ts, te
            )

            if therapy.get("slot_id"):
                conn.execute(text("""
                    UPDATE schedule_slots
                       SET therapist_id=:tid, starts_at=:s, ends_at=:e,
                           place_from=NULL, place_to=:place, status=:status,
                           session_id=:sid, kind='therapy'
                     WHERE id=:sid_slot AND group_id=:gid
                """), {
                    "tid": therapy["therapist_id"], "s": ts, "e": te,
                    "place": therapy.get("place"),
                    "status": status, "sid": session_id,
                    "sid_slot": therapy["slot_id"], "gid": gid
                })
            else:
                # znajdź istniejący slot terapii w grupie (gdy brak slot_id)
                ex = conn.execute(text("""
                    SELECT id FROM schedule_slots
                     WHERE group_id=:gid AND kind='therapy' LIMIT 1
                """), {"gid": gid}).mappings().first()
                if ex:
                    conn.execute(text("""
                        UPDATE schedule_slots
                           SET therapist_id=:tid, starts_at=:s, ends_at=:e,
                               place_from=NULL, place_to=:place, status=:status,
                               session_id=:sid
                         WHERE id=:id
                    """), {
                        "tid": therapy["therapist_id"], "s": ts, "e": te,
                        "place": therapy.get("place"),
                        "status": status, "sid": session_id,
                        "id": ex["id"]
                    })
                else:
                    # brak – wstaw
                    conn.execute(text("""
                        INSERT INTO schedule_slots (
                          group_id, client_id, therapist_id, kind,
                          starts_at, ends_at, place_from, place_to, status, session_id
                        )
                        SELECT :gid, client_id, :tid, 'therapy', :s, :e, NULL, :place, :status, :sid
                          FROM schedule_slots WHERE group_id=:gid LIMIT 1
                    """), {
                        "gid": gid, "tid": therapy["therapist_id"],
                        "s": ts, "e": te, "place": therapy.get("place"),
                        "status": status, "sid": session_id
                    })

            # helper do PICKUP/DROPOFF
            def upsert_run(kind, block):
                ex = conn.execute(text("""
                    SELECT id FROM schedule_slots
                     WHERE group_id=:gid AND kind=:kind LIMIT 1
                """), {"gid": gid, "kind": kind}).mappings().first()

                if block is None:
                    # usuwanie sekcji
                    if ex:
                        conn.execute(text("DELETE FROM schedule_slots WHERE id=:id"), {"id": ex["id"]})
                    return

                s = datetime.fromisoformat(block["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(block["ends_at"]).replace(tzinfo=TZ)
                rid = ensure_shared_run_id_for_driver(conn, int(block["driver_id"]), s, e)
                payload = {
                    "did": block["driver_id"],
                    "veh": block.get("vehicle_id"),
                    "s": s, "e": e,
                    "from": block.get("from"), "to": block.get("to"),
                    "status": status, "rid": rid,
                    "gid": gid, "kind": kind
                }
                if ex:
                    conn.execute(text(f"""
                        UPDATE schedule_slots
                           SET driver_id=:did, vehicle_id=:veh,
                               starts_at=:s, ends_at=:e,
                               place_from=:from, place_to=:to,
                               status=:status, run_id=:rid
                         WHERE id=:id
                    """), {**payload, "id": ex["id"]})
                else:
                    # klient_id bierzemy z terapii w tej grupie
                    conn.execute(text(f"""
                        INSERT INTO schedule_slots (
                          group_id, client_id, driver_id, vehicle_id, kind,
                          starts_at, ends_at, place_from, place_to, status, run_id
                        )
                        SELECT :gid, client_id, :did, :veh, :kind,
                               :s, :e, :from, :to, :status, :rid
                          FROM schedule_slots
                         WHERE group_id=:gid AND kind='therapy'
                         LIMIT 1
                    """), payload)

            upsert_run("pickup",  pickup)
            upsert_run("dropoff", dropoff)

        return jsonify({"ok": True, "group_id": gid}), 200

    except IntegrityError as e:
        if getattr(e.orig, "pgcode", None) == errorcodes.EXCLUSION_VIOLATION:
            return jsonify({"error": "Konflikt czasowy (zasób zajęty)."}), 409
        if getattr(e.orig, "pgcode", None) == psycopg2.errorcodes.FOREIGN_KEY_VIOLATION:
            return jsonify({"error": "Naruszenie FK – sprawdź ID osób/pojazdu."}), 400
        return jsonify({"error": "Błąd bazy", "details": str(e.orig)}), 400



@app.post("/api/therapists")
def create_therapist():
    data = request.get_json(force=True)
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    sql = """
    INSERT INTO therapists (full_name, specialization,phone, active)
    VALUES (:full_name, :specialization,:phone, COALESCE(:active,true))
    RETURNING id, full_name, specialization, phone, active;
    """
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {
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

@app.post("/api/suo/allocation")
def upsert_suo_allocation():
    """
    JSON body:
    {
      "client_id": 1,
      "month_key": "2025-08",
      "minutes_quota": 1200
    }
    """
    data = request.get_json(force=True)
    client_id = data.get("client_id")
    month_key = data.get("month_key")
    minutes_quota = data.get("minutes_quota")

    if not client_id or not month_key or minutes_quota is None:
        return jsonify({"error": "client_id, month_key, minutes_quota are required"}), 400

    sql = """
    INSERT INTO suo_allocations (client_id, month_key, minutes_quota)
    VALUES (:cid, :mk, :q)
    ON CONFLICT (client_id, month_key)
    DO UPDATE SET minutes_quota = EXCLUDED.minutes_quota
    RETURNING client_id, month_key, minutes_quota;
    """
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(sql), {"cid": client_id, "mk": month_key, "q": minutes_quota}
            ).mappings().first()
            return jsonify(dict(row)), 200
    except Exception as e:
        # typowo złapie np. naruszenie FK, gdy nie ma klienta w `clients`
        return jsonify({"error": str(e)}), 400

# === THERAPISTS ===
@app.get("/api/therapists")
def list_therapists():
    include_inactive = request.args.get("include_inactive") in ("1","true","yes")
    where = "" if include_inactive else "WHERE active IS TRUE"
    sql = f"""
    SELECT id, full_name, specialization, phone, active
    FROM therapists
    {where}
    ORDER BY active DESC, full_name
    """
    with engine.begin() as conn:
        rows = conn.execute(text(sql)).mappings().all()
        return jsonify([dict(r) for r in rows]), 200

@app.delete("/api/therapists/<int:tid>")
def delete_therapist(tid):
    """Trwale usuwa terapeutę i wszystkie jego powiązania (kaskadowo)."""
    with engine.begin() as conn:
        # Zawsze wykonuj twarde usuwanie
        res = conn.execute(text("DELETE FROM therapists WHERE id=:id"), {"id": tid})

    if res.rowcount == 0:
        return jsonify({"error": "Therapist not found"}), 404

    return "", 204

@app.put("/api/therapists/<int:tid>")
def update_therapist(tid):
    data = request.get_json(force=True)
    sql = """
    UPDATE therapists
    SET full_name = COALESCE(:full_name, full_name),
        specialization = COALESCE(:specialization, specialization),
        phone = COALESCE(:phone, phone),
        active = COALESCE(:active, active)
    WHERE id = :id
    RETURNING id, full_name, specialization, phone, active;
    """
    with engine.begin() as conn:
        row = conn.execute(text(sql), {
            "id": tid,
            "full_name": (data.get("full_name") or None),
            "specialization": (data.get("specialization") or None),
            "phone": (data.get("phone") or None),
            "active": data.get("active") if data.get("active") is not None else None
        }).mappings().first()
        if not row:
            return jsonify({"error": "Therapist not found"}), 404
        return jsonify(dict(row)), 200

# === DRIVERS ===
@app.get("/api/drivers")
def list_drivers():
    include_inactive = request.args.get("include_inactive") in ("1","true","yes")
    where = "" if include_inactive else "WHERE active IS TRUE"
    sql = f"""
    SELECT id, full_name, phone, active
    FROM drivers
    {where}
    ORDER BY active DESC, full_name
    """
    with engine.begin() as conn:
        rows = conn.execute(text(sql)).mappings().all()
        return jsonify([dict(r) for r in rows]), 200

@app.delete("/api/drivers/<int:did>")
def delete_driver(did):
    """Trwale usuwa kierowcę i wszystkie jego powiązania (kaskadowo)."""
    with engine.begin() as conn:
        # Zawsze wykonuj twarde usuwanie
        res = conn.execute(text("DELETE FROM drivers WHERE id=:id"), {"id": did})

    if res.rowcount == 0:
        return jsonify({"error": "Driver not found"}), 404

    return "", 204

@app.put("/api/drivers/<int:did>", endpoint="drivers_update")
def update_driver_api(did):
    data = request.get_json(force=True)
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    sql = """
    UPDATE drivers
       SET full_name = :full_name,
           phone     = :phone,
           active    = COALESCE(:active, true)
     WHERE id = :id
    RETURNING id, full_name, phone, active;
    """
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {
                "id": did,
                "full_name": full_name,
                "phone": (data.get("phone") or None),
                "active": data.get("active", True),
            }).mappings().first()
            if not row:
                return jsonify({"error": "Kierowca nie istnieje."}), 404
            return jsonify(dict(row)), 200
    except IntegrityError as e:
        # duplikat imienia i nazwiska
        if getattr(e.orig, "pgcode", None) == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409



@app.get("/api/suo/balance/<int:client_id>/<string:month_key>")
def get_suo_balance(client_id, month_key):
    sql = """
    SELECT * FROM suo_balance
    WHERE client_id = :cid AND month_key = :mk
    """
    with engine.begin() as conn:
        row = conn.execute(text(sql), {"cid": client_id, "mk": month_key}).mappings().first()
        if not row:
            return jsonify({"client_id": client_id, "month_key": month_key, "minutes_left": None,
                            "minutes_quota": None, "minutes_used": None}), 200
        return jsonify(dict(row)), 200

@app.post("/api/drivers")
def create_driver():
    data = request.get_json(force=True)
    full_name = (data.get("full_name") or "").strip()
    if not full_name:
        return jsonify({"error": "Pole 'full_name' jest wymagane."}), 400

    sql = """
    INSERT INTO drivers (full_name, phone, active)
    VALUES (:full_name, :phone, COALESCE(:active,true))
    RETURNING id, full_name, phone, active;
    """
    try:
        with engine.begin() as conn:
            row = conn.execute(text(sql), {
                "full_name": full_name,
                "phone": (data.get("phone") or None),
                "active": bool(data.get("active", True)),
            }).mappings().first()
            return jsonify(dict(row)), 201
    except IntegrityError as e:
        # Duplikat (unikalny indeks) -> 409 Conflict
        if hasattr(e.orig, "pgcode") and e.orig.pgcode == psycopg2.errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Taki kierowca już istnieje (imię i nazwisko)."}), 409
        # Inne błędy integralności
        return jsonify({"error": "Błąd integralności bazy.", "details": str(e.orig)}), 409

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
    data = request.get_json(force=True)
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
                s = datetime.fromisoformat(p["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(p["ends_at"]).replace(tzinfo=TZ)
                run_id = ensure_shared_run_id_for_driver(conn, int(p["driver_id"]), s, e)

                conn.execute(text("""
                  INSERT INTO schedule_slots (
                    group_id, client_id, therapist_id, driver_id, vehicle_id,
                    kind, starts_at, ends_at, place_from, place_to, status, run_id
                  )
                  VALUES (
                    :group_id, :client_id, NULL, :driver_id, :vehicle_id,
                    'pickup', :starts_at, :ends_at, :from, :to, :status, :run_id
                  )
                """), {
                    "group_id": gid,
                    "client_id": data["client_id"],
                    "driver_id": p["driver_id"],
                    "vehicle_id": p.get("vehicle_id"),
                    "starts_at": s, "ends_at": e,
                    "from": p.get("from"), "to": p.get("to"),
                    "status": status,
                    "run_id": run_id
                })

            # 4) DROPOFF (opcjonalnie) – wspólny kurs -> run_id
            if data.get("dropoff"):
                d = data["dropoff"]
                s = datetime.fromisoformat(d["starts_at"]).replace(tzinfo=TZ)
                e = datetime.fromisoformat(d["ends_at"]).replace(tzinfo=TZ)
                run_id = ensure_shared_run_id_for_driver(conn, int(d["driver_id"]), s, e)

                conn.execute(text("""
                  INSERT INTO schedule_slots (
                    group_id, client_id, therapist_id, driver_id, vehicle_id,
                    kind, starts_at, ends_at, place_from, place_to, status, run_id
                  )
                  VALUES (
                    :group_id, :client_id, NULL, :driver_id, :vehicle_id,
                    'dropoff', :starts_at, :ends_at, :from, :to, :status, :run_id
                  )
                """), {
                    "group_id": gid,
                    "client_id": data["client_id"],
                    "driver_id": d["driver_id"],
                    "vehicle_id": d.get("vehicle_id"),
                    "starts_at": s, "ends_at": e,
                    "from": d.get("from"), "to": d.get("to"),
                    "status": status,
                    "run_id": run_id
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


# === CLIENT PACKAGES (grupy+sloty klienta) ===
@app.get("/api/client/<int:cid>/packages")
def client_packages(cid):
    mk = request.args.get("month")  # 'YYYY-MM' albo None
    sql = """
    SELECT
      eg.id AS group_id,
      eg.label,
      ss.id AS slot_id,
      ss.kind,
      to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM-DD"T"HH24:MI:SS') AS starts_at,
      to_char(ss.ends_at   AT TIME ZONE 'Europe/Warsaw','YYYY-MM-DD"T"HH24:MI:SS') AS ends_at,
      ss.status,
      ss.therapist_id,
      t.full_name AS therapist_name,
      ss.driver_id,
      d.full_name AS driver_name,
      ss.vehicle_id,
      ss.place_from,
      ss.place_to
    FROM event_groups eg
    LEFT JOIN schedule_slots ss ON ss.group_id = eg.id
    LEFT JOIN therapists t ON t.id = ss.therapist_id
    LEFT JOIN drivers d    ON d.id = ss.driver_id
    WHERE eg.client_id = :cid
      AND (
        :mk IS NULL OR
        (ss.starts_at IS NOT NULL AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk)
      )
    ORDER BY COALESCE(ss.starts_at, 'epoch'::timestamp);
    """
    with engine.begin() as conn:
        rows = conn.execute(text(sql), {"cid": cid, "mk": mk}).mappings().all()
        return jsonify([dict(r) for r in rows]), 200


# === THERAPIST SCHEDULE (sloty terapeuty z klientami) ===
@app.get("/api/therapists/<int:tid>/schedule")
def therapist_schedule(tid):
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
      ss.group_id
    FROM schedule_slots ss
    JOIN clients c ON c.id = ss.client_id
    WHERE ss.therapist_id = :tid
      AND (
        :mk IS NULL OR
        (ss.starts_at IS NOT NULL AND to_char(ss.starts_at AT TIME ZONE 'Europe/Warsaw','YYYY-MM') = :mk)
      )
    ORDER BY ss.starts_at;
    """
    with engine.begin() as conn:
        rows = conn.execute(text(sql), {"tid": tid, "mk": mk}).mappings().all()
        return jsonify([dict(r) for r in rows]), 200


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
    data = request.get_json(force=True)
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
    data = request.get_json(force=True)
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
    data = request.get_json(force=True) or {}
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
    data = request.get_json(force=True)
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


@app.delete("/api/groups/<string:gid>")
def delete_group(gid):
    """
    Usuwa całą grupę zdarzeń (pakiet).
    Zakłada, że FK `schedule_slots.group_id` ma `ON DELETE CASCADE` w bazie danych,
    co spowoduje automatyczne usunięcie wszystkich powiązanych slotów.
    """
    with engine.begin() as conn:
        res = conn.execute(text("DELETE FROM event_groups WHERE id = :gid"), {"gid": gid})

    if res.rowcount == 0:
        return jsonify({"error": "Nie znaleziono grupy (pakietu)."}), 404

    return jsonify({"ok": True, "message": "Pakiet został pomyślnie usunięty."}), 200


# === ABSENCES (Nieobecności) ===

@app.post("/api/absences")
def add_absence():
    """Dodaje nową nieobecność dla terapeuty lub kierowcy."""
    data = request.get_json()
    # Walidacja danych wejściowych
    required_fields = ["person_type", "person_id", "status", "start_date", "end_date"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Brak wszystkich wymaganych pól."}), 400

    sql = text("""
        INSERT INTO absences (person_type, person_id, status, start_date, end_date, notes)
        VALUES (:person_type, :person_id, :status, :start_date, :end_date, :notes)
        RETURNING id;
    """)
    with engine.begin() as conn:
        result = conn.execute(sql, data)
        new_id = result.scalar_one()
    return jsonify({"id": new_id, **data}), 201

@app.get("/api/absences")
def get_absences():
    """Pobiera nieobecności dla danego miesiąca."""
    month_key = request.args.get("month") # format YYYY-MM
    if not month_key:
        return jsonify({"error": "Parametr 'month' jest wymagany."}), 400

    sql = text("""
        SELECT id, person_type, person_id, status, start_date, end_date, notes 
        FROM absences
        WHERE to_char(start_date, 'YYYY-MM') = :month OR to_char(end_date, 'YYYY-MM') = :month
    """)
    with engine.begin() as conn:
        rows = conn.execute(sql, {"month": month_key}).mappings().all()
        return jsonify([dict(r) for r in rows])

@app.delete("/api/absences/<int:absence_id>")
def delete_absence(absence_id):
    """Usuwa nieobecność."""
    sql = text("DELETE FROM absences WHERE id = :id")
    with engine.begin() as conn:
        result = conn.execute(sql, {"id": absence_id})
    if result.rowcount == 0:
        return jsonify({"error": "Nie znaleziono nieobecności."}), 404
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
    data = request.get_json()
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




