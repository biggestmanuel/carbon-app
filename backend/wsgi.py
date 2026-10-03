"""Production entrypoint and worker settings.

    gunicorn wsgi:app

Flask's built-in server is single-threaded and says so itself; it is not for
production. This module exposes a plain WSGI callable plus the settings that
matter, so the same command works under any process manager.

Migrations must be applied before traffic is served:

    flask db upgrade
"""

import os

from app import create_app

app = create_app()

# --- Worker settings ------------------------------------------------------
# Bound to loopback by default. Behind a reverse proxy that is correct, since
# the proxy should be the only thing reaching the socket. Set BIND=0.0.0.0 only
# when there is no other network boundary, such as inside a private container.
bind = os.environ.get("BIND", "127.0.0.1:8000")

# Threads, not extra processes: the workload is I/O bound, and threads share one
# database connection pool instead of each process opening its own.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("WEB_THREADS", "4"))

# Recycle workers periodically to bound the effect of any slow leak.
timeout = int(os.environ.get("WEB_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

accesslog = "-" if os.environ.get("WEB_ACCESS_LOG", "1") == "1" else None
errorlog = "-"
loglevel = os.environ.get("WEB_LOG_LEVEL", "info")

# Trust the proxy's X-Forwarded-* for this many hops. Keep this equal to the
# number of proxies actually in front of the app: over-trusting lets any client
# claim a different scheme or IP, and PROXY_FIX_X_FOR must match it.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
