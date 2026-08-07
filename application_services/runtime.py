"""Transitional runtime binding for extracted application services.

The service modules are imported while :mod:`server` is assembled.  This
bridge publishes their public compatibility symbols back to that composition
root and keeps calls dynamic so existing integrations and tests can replace a
service seam without re-importing the application.
"""

from __future__ import annotations

import importlib
import inspect
from functools import wraps
from types import ModuleType
from typing import Any


_backend: ModuleType | None = None
_service_namespaces: list[dict[str, Any]] = []
_POST_SERVICE_MODULES = (
    "application_services.trailer_policy",
    "application_services.movie_search_availability",
    "application_services.content_language_policy",
    "application_services.media_identity",
    "application_services.media_identity_series_alias",
    "application_services.movie_fallback_policy",
    "application_services.movie_subscription_quality",
)


def register_backend(backend: ModuleType) -> None:
    global _backend
    if _backend is not None and _backend is not backend:
        raise RuntimeError("Application service backend is already registered")
    _backend = backend


def _registered_backend() -> ModuleType:
    if _backend is None:
        raise RuntimeError("Application service backend is not registered")
    return _backend


def backend_value(name: str) -> Any:
    """Read a runtime value that the composition root may replace."""
    return getattr(_registered_backend(), name)


def _dynamic_function(name: str, original):
    if inspect.iscoroutinefunction(original):
        @wraps(original)
        async def async_call(*args, **kwargs):
            return await getattr(_registered_backend(), name)(*args, **kwargs)

        return async_call

    @wraps(original)
    def call(*args, **kwargs):
        return getattr(_registered_backend(), name)(*args, **kwargs)

    return call


def import_backend_namespace() -> dict[str, Any]:
    """Return runtime dependencies without copying module metadata."""
    backend = _registered_backend()
    namespace: dict[str, Any] = {}
    for name, value in vars(backend).items():
        if name.startswith("__"):
            continue
        namespace[name] = (
            _dynamic_function(name, value)
            if inspect.isfunction(value)
            else value
        )
    return namespace


def publish_service(module_globals: dict[str, Any], names: tuple[str, ...]) -> None:
    """Publish service symbols and preserve dynamic composition-root seams."""
    backend = _registered_backend()
    _service_namespaces.append(module_globals)
    originals = {name: module_globals[name] for name in names}
    for name, value in originals.items():
        setattr(backend, name, value)
    for name, value in originals.items():
        if inspect.isfunction(value):
            module_globals[name] = _dynamic_function(name, value)


def refresh_services() -> None:
    """Bind dependencies published by services imported later in the chain."""
    for module_name in _POST_SERVICE_MODULES:
        importlib.import_module(module_name)
    available = import_backend_namespace()
    for namespace in _service_namespaces:
        for name, value in available.items():
            namespace.setdefault(name, value)

    # Queue performance policy depends on the complete service graph (queue
    # persistence, lifecycle callbacks, and physical scheduler), so install it
    # only after every runtime dependency has been published.  The installer is
    # idempotent and uses the same dynamic backend seam as the service modules.
    from queue_performance import install_queue_performance

    backend = _registered_backend()
    controller = install_queue_performance(backend)
    optimized_persist = backend._persist_queue_state

    def persist_queue_state_with_claim_guard() -> bool:
        # ``_persist_new_queue_claims`` is intentionally fail-closed.  During
        # automatic scheduling a claim can briefly exist before its logical
        # queue job is materialized.  Such an incomplete claim has no durable
        # signature yet, so it must still exercise the real persistence path;
        # otherwise a storage failure could be mistaken for a successful save.
        with backend.state.queue_claim_lock:
            unbacked_claim = any(
                slug not in backend.state.queue_job_by_slug
                for slug in backend.state.picked
            )
        if unbacked_claim:
            return bool(controller._persist_delegate())
        return bool(optimized_persist())

    backend._persist_queue_state = persist_queue_state_with_claim_guard
