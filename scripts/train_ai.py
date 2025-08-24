# scripts/train_ai.py
import pandas as pd
import joblib
from sqlalchemy import create_engine, text
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split

DATABASE_URL = "postgresql+psycopg2://postgres:EDUQ@localhost:5432/suo"
engine = create_engine(DATABASE_URL, future=True)

def load_ct_pairs(conn):
    # pozytywne pary: historycznie razem
    pos = pd.read_sql(text("""
        SELECT client_id, therapist_id,
               n_sessions, minutes_sum, done_ratio, days_since_last, recency_weight,
               1 AS y
        FROM v_ct_features
    """), conn)
    # negatywne: klient x terapeuta aktywny, którzy nigdy razem
    all_t = pd.read_sql(text("SELECT id AS therapist_id FROM therapists WHERE active=true"), conn)
    all_c = pd.read_sql(text("SELECT id AS client_id FROM clients"), conn)
    pos_key = set(zip(pos.client_id, pos.therapist_id))
    neg = []
    # proste negatywne próbkowanie (po 2 na pozytyw)
    target_neg = len(pos) * 2
    for _, c in all_c.iterrows():
        for _, t in all_t.iterrows():
            if (c.client_id, t.therapist_id) not in pos_key:
                neg.append((c.client_id, t.therapist_id))
                if len(neg) >= target_neg:
                    break
        if len(neg) >= target_neg:
            break
    if not neg:
        return pos, None
    neg_df = pd.DataFrame(neg, columns=["client_id","therapist_id"])
    neg_df["n_sessions"] = 0
    neg_df["minutes_sum"] = 0
    neg_df["done_ratio"] = 0.0
    neg_df["days_since_last"] = 9999
    neg_df["recency_weight"] = 0.0
    neg_df["y"] = 0
    return pos, neg_df

def train_and_save():
    with engine.begin() as conn:
        pos, neg = load_ct_pairs(conn)
    df = pd.concat([pos, neg], ignore_index=True)
    X = df[["n_sessions","minutes_sum","done_ratio","days_since_last","recency_weight"]]
    y = df["y"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    clf = GradientBoostingClassifier(random_state=42)
    clf.fit(Xtr, ytr)
    print("AUC-like score:", clf.score(Xte, yte))
    joblib.dump(clf, "models/ct_recommender.pkl")

if __name__ == "__main__":
    train_and_save()
