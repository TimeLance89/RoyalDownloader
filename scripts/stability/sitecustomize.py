"""Carry the test-only egress boundary into ordinary Python subprocesses."""
import os

if os.environ.get('ROYAL_STABILITY_OFFLINE') == '1':
    import offline_guard
    offline_guard.pytest_configure(None)
