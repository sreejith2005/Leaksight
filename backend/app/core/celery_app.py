"""
LeakSight V1 — Celery Application Configuration

Source: docs/ARCHITECTURE.md (Celery configuration, Section 6.2, 7.1)
       backend/app/core/config.py (CELERY_BROKER_URL, CELERY_RESULT_BACKEND)
       docker-compose.prod.yml (worker service definition, internal network only)

Configuration:
  - Broker: Redis DB 0 (CELERY_BROKER_URL)
  - Result Backend: Redis DB 1 (CELERY_RESULT_BACKEND)
  - Serializer: JSON only — never pickle (security risk)
  - Hard time limit: 3600s (1 hour) — stuck tasks are killed
  - Soft time limit: 3000s — 10 min cleanup window before hard kill
  - Max tasks per child: 50 — forces worker restart to release PaddleOCR memory
  - Timezone: Asia/Kolkata (matches server timezone per infra guide)
"""

import os

from celery import Celery

from backend.app.core.config import get_settings

settings = get_settings()

celery_app = Celery("leaksight")

# --- Core broker / backend ---
celery_app.conf.broker_url = settings.celery_broker_url
celery_app.conf.result_backend = settings.celery_result_backend

# --- Serialization: JSON only — never pickle (security risk) ---
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]

# --- Time limits ---
celery_app.conf.task_time_limit = 3600       # Hard kill after 1 hour
celery_app.conf.task_soft_time_limit = 3000  # Soft limit: 50 min, 10 min cleanup

# --- Reliability: acknowledge after task completes, re-queue on worker loss ---
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True

# --- Worker memory management ---
# Forces worker process restart after 50 tasks, releasing PaddleOCR memory
celery_app.conf.worker_max_tasks_per_child = 50

# --- Task always eager: False in production, configurable for testing ---
celery_app.conf.task_always_eager = os.environ.get(
    "CELERY_TASK_ALWAYS_EAGER", "false"
).lower() == "true"

# --- Timezone: Asia/Kolkata (matches server per infra guide) ---
celery_app.conf.timezone = "Asia/Kolkata"
celery_app.conf.enable_utc = True

# --- Task routes: separate queues for parse and analysis tasks ---
celery_app.conf.task_routes = {
    "backend.app.tasks.parse_task.parse_document": {"queue": "parse"},
    "backend.app.tasks.normalize_task.normalize_document": {"queue": "parse"},
    "backend.app.tasks.analysis_run_task.run_analysis": {"queue": "analysis"},
}

# --- Default queue for any unrouted tasks ---
celery_app.conf.task_default_queue = "default"

# --- Explicitly import and register task modules ---
celery_app.conf.include = [
    "backend.app.tasks.parse_task",
    "backend.app.tasks.normalize_task",
    "backend.app.tasks.analysis_run_task",
]
