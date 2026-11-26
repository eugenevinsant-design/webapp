"""
Точка входа для Vercel (serverless FastAPI).

Vercel Python runtime ищет ASGI-приложение в переменной `app` внутри
api/index.py. Всё остальное — тот же app.main, что и локально/в Docker.

Здесь только:
- добавляем корень репозитория в sys.path (на случай другого CWD);
- фиксируем SIGNALS_DIR абсолютным путём (относительный './data/signals'
  зависел бы от CWD функции).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SIGNALS_DIR", str(ROOT / "data" / "signals"))

from app.main import app  # noqa: E402,F401  (экспортируется для Vercel)
