import pandas as pd
import joblib
from sqlalchemy import create_engine, text
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
import os

# Upewnij się, że ta zmienna jest zgodna z Twoją konfiguracją
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:EDUQ@localhost:5432/suo")
engine = create_engine(DATABASE_URL, future=True)


def load_cd_pairs(conn):
    """ Wczytuje pozytywne i negatywne pary klient-kierowca """
    # Pozytywne pary: historycznie razem
    pos = pd.read_sql(text("""
        SELECT client_id, driver_id,
               n_runs, minutes_sum, done_ratio, days_since_last, recency_weight,
               1 AS y
        FROM v_cd_features
    """), conn)

    # Negatywne pary: klient x aktywny kierowca, którzy nigdy razem nie jeździli
    all_d = pd.read_sql(text("SELECT id AS driver_id FROM drivers WHERE active=true"), conn)
    all_c = pd.read_sql(text("SELECT id AS client_id FROM clients WHERE active=true"), conn)

    if all_d.empty or all_c.empty:
        return pos, None

    pos_key = set(zip(pos.client_id, pos.driver_id))
    neg = []

    # Proste negatywne próbkowanie (po 2 na każdą parę pozytywną)
    target_neg = len(pos) * 2

    # Aby uniknąć nieskończonej pętli, jeśli jest mało kombinacji
    max_attempts = target_neg * 10
    attempts = 0

    while len(neg) < target_neg and attempts < max_attempts:
        c = all_c.sample(1).iloc[0]
        d = all_d.sample(1).iloc[0]
        if (c.client_id, d.driver_id) not in pos_key:
            neg.append((c.client_id, d.driver_id))
        attempts += 1

    if not neg:
        return pos, None

    neg_df = pd.DataFrame(list(set(neg)), columns=["client_id", "driver_id"])
    neg_df["n_runs"] = 0
    neg_df["minutes_sum"] = 0
    neg_df["done_ratio"] = 0.0
    neg_df["days_since_last"] = 9999
    neg_df["recency_weight"] = 0.0
    neg_df["y"] = 0

    return pos, neg_df


def train_and_save():
    """ Główna funkcja trenująca i zapisująca model """
    print("Ładowanie par klient-kierowca...")
    with engine.begin() as conn:
        pos, neg = load_cd_pairs(conn)

    if neg is None or neg.empty:
        print("Brak wystarczającej ilości danych do wygenerowania par negatywnych. Przerywam trening.")
        return

    df = pd.concat([pos, neg], ignore_index=True)

    # === NOWY KOD - ZABEZPIECZENIE PRZED BŁĘDEM ===
    y = df["y"]

    # Sprawdź, czy każda klasa (0 i 1) ma co najmniej 2 próbki
    if y.value_counts().min() < 2:
        print("\nUWAGA: Za mało zróżnicowanych danych do przeprowadzenia stratyfikacji. Model nie będzie trenowany.")
        print(
            "Aby trenować model, dodaj więcej historycznych kursów (potrzebne są co najmniej 2 różne pary klient-kierowca).\n")
        return  # Bezpiecznie zakończ funkcję
    # === KONIEC NOWEGO KODU ===

    features = ["n_runs", "minutes_sum", "done_ratio", "days_since_last", "recency_weight"]
    X = df[features]

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    print("Trenowanie modelu GradientBoostingClassifier...")
    clf = GradientBoostingClassifier(random_state=42)
    clf.fit(Xtr, ytr)

    score = clf.score(Xte, yte)
    print(f"Dokładność modelu na zbiorze testowym: {score:.2%}")

    output_path = "models/cd_recommender.pkl"
    print(f"Zapisywanie modelu do {output_path}...")
    joblib.dump(clf, output_path)
    print("Model został pomyślnie zapisany.")


if __name__ == "__main__":
    # Upewnij się, że folder 'models' istnieje
    if not os.path.exists('models'):
        os.makedirs('models')
    train_and_save()