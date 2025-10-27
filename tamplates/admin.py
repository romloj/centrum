# Plik: create_admin.py
import os

from werkzeug.security import generate_password_hash
import psycopg2

# Uzupełnij DOKŁADNIE takie same dane, jakich używa Twoja aplikacja na Render
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:EDUQ@localhost:5432/suo")

# Uzupełnij dane dla nowego admina
ADMIN_FULL_NAME = "Roman Łojek"  # WAŻNE: Musi to być imię i nazwisko istniejącego terapeuty
ADMIN_PASSWORD = "bardzotrudnehaslo"

# Konwersja URL-a dla psycopg2
db_url_psycopg2 = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")

try:
    conn = psycopg2.connect(db_url_psycopg2)
    cur = conn.cursor()

    password_hash = generate_password_hash(ADMIN_PASSWORD)

    # Aktualizujemy istniejącego terapeutę, nadając mu rolę admina i hasło
    cur.execute(
        "UPDATE therapists SET password_hash = %s, role = %s WHERE full_name = %s",
        (password_hash, 'admin', ADMIN_FULL_NAME)
    )
    conn.commit()

    print(f"Pomyślnie zaktualizowano użytkownika '{ADMIN_FULL_NAME}' i nadano mu rolę admina.")

    cur.close()
    conn.close()

except Exception as e:
    print(f"Wystąpił błąd: {e}")