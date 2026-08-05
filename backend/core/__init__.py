"""Core infrastructure: configuration, logging, telemetry, security, DI container.

This package contains only framework-agnostic infrastructure that any host
application (FastAPI, CLI, worker) can reuse. Nothing here imports from
``agents``, ``database``, ``prompts`` etc. so it stays fully reusable.
"""
