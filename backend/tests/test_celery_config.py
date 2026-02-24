"""
LeakSight V1 — Celery Configuration Tests

Verifies:
  - Celery app initializes with correct broker and backend URLs
  - Task serializer is json, not pickle
  - Worker max tasks per child is 50
  - Time limits are set correctly
  - Task routes are defined for parse and analysis queues
"""

import os
from unittest.mock import patch

import pytest


def test_celery_app_initializes_with_correct_broker_and_backend():
    """Celery app uses CELERY_BROKER_URL (Redis DB 0) and CELERY_RESULT_BACKEND (Redis DB 1)."""
    from backend.app.core.celery_app import celery_app
    from backend.app.core.config import get_settings

    settings = get_settings()
    assert celery_app.conf.broker_url == settings.celery_broker_url
    assert celery_app.conf.result_backend == settings.celery_result_backend


def test_celery_task_serializer_is_json_not_pickle():
    """Task serializer must be json — pickle is a security risk."""
    from backend.app.core.celery_app import celery_app

    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    # Explicitly verify pickle is not accepted
    assert "pickle" not in celery_app.conf.accept_content


def test_celery_worker_max_tasks_per_child():
    """Worker max tasks per child must be 50 (PaddleOCR memory management)."""
    from backend.app.core.celery_app import celery_app

    assert celery_app.conf.worker_max_tasks_per_child == 50


def test_celery_time_limits():
    """Hard limit 3600s, soft limit 3000s."""
    from backend.app.core.celery_app import celery_app

    assert celery_app.conf.task_time_limit == 3600
    assert celery_app.conf.task_soft_time_limit == 3000


def test_celery_timezone():
    """Timezone must be Asia/Kolkata per infra guide."""
    from backend.app.core.celery_app import celery_app

    assert celery_app.conf.timezone == "Asia/Kolkata"


def test_celery_task_routes_defined():
    """Task routes define separate parse and analysis queues."""
    from backend.app.core.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert "backend.app.tasks.parse_task.parse_document" in routes
    assert routes["backend.app.tasks.parse_task.parse_document"]["queue"] == "parse"
    assert "backend.app.tasks.normalize_task.normalize_document" in routes
    assert routes["backend.app.tasks.normalize_task.normalize_document"]["queue"] == "parse"
    assert "backend.app.tasks.analysis_run_task.run_analysis" in routes
    assert routes["backend.app.tasks.analysis_run_task.run_analysis"]["queue"] == "analysis"


def test_celery_task_modules_registered():
    """All three task modules must be in the include list."""
    from backend.app.core.celery_app import celery_app

    include = celery_app.conf.include
    assert "backend.app.tasks.parse_task" in include
    assert "backend.app.tasks.normalize_task" in include
    assert "backend.app.tasks.analysis_run_task" in include

