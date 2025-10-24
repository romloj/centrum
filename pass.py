import os

# 1. Ustal nazwę zmiennej, której będziesz szukać (np. 'ADMIN_PASSWORD')
#    Ta nazwa to "Klucz" (Key), który ustawisz na Render.com.
KLUCZ_HASLA = 'centrum'

# 2. Użyj os.environ.get(), aby bezpiecznie pobrać wartość zmiennej
#    Metoda .get() zwróci 'None', jeśli zmienna nie zostanie znaleziona
#    (zamiast powodować błąd aplikacji).
haslo = os.environ.get(KLUCZ_HASLA)

# 3. Sprawdź, czy hasło zostało wczytane
if haslo:
    print(f"Pomyślnie wczytano hasło ze zmiennej środowiskowej '{KLUCZ_HASLA}'.")
    
    # W tym miejscu Twoja aplikacja może użyć hasła, np.:
    # db_connect(user="admin", password=haslo)
    
    # WAŻNE: Nigdy nie wypisuj samego hasła w logach produkcyjnych!
    # print(f"Wczytane hasło to: {haslo}") # <-- ZŁA PRAKTYKA (RYZYKO WYCIEKU)
    print("Aplikacja jest gotowa do użycia hasła.")

else:
    # Jeśli aplikacja nie znajdzie hasła, poinformuj o tym.
    print(f"BŁĄD: Nie można znaleźć wymaganego hasła w zmiennych środowiskowych.")
    print(f"Upewnij się, że ustawiłeś zmienną o nazwie: {KLUCZ_HASLA}")
