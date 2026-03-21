"""
Background work placeholders.

Prefer FastAPI `BackgroundTasks` for quick jobs on Pi; migrate to Celery/ARQ when you
need durable queues across reboots.
"""

# Example (not wired by default):
# def enqueue_thumbnail_job(file_id: str) -> None:
#     ...
