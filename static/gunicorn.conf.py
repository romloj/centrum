# gunicorn.conf.py
import multiprocessing

# Bind
bind = f"0.0.0.0:{os.environ.get('PORT', 10000)}"

# Workers
workers = 1
worker_class = "sync"

# Timeouts
timeout = 120  # Zwiększ timeout do 120 sekund
graceful_timeout = 120
keepalive = 5

# Logging
accesslog = "-"

errorlog = "-"
