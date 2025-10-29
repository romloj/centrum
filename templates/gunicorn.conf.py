import multiprocessing
import os # <-- Dodaj ten import

# Odczytaj port ze zmiennej środowiskowej PORT, domyślnie użyj 8000
# Platformy takie jak Render ustawią zmienną PORT automatycznie.
port = os.environ.get("PORT", "8000")

# Bind
bind = f"0.0.0.0:{port}" # <-- Użyj f-stringa z odczytaną wartością

# Workers
workers = 1
worker_class = "sync"

# Timeouts
timeout = 120
graceful_timeout = 120
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"

print(f"--- Gunicorn binding to: {bind} ---") # Opcjonalny log dla potwierdzenia
