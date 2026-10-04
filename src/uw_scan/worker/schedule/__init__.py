"""Scheduler job families (Phase 6a).

Each module registers one family's jobs with ``register(sched, settings)``;
``worker/scheduler.py`` decides which process calls it. The golden in
``tests/unit/worker/test_scheduler_jobs_golden.py`` pins the result.
"""
