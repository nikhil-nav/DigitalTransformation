import importlib.util
import sys
from pathlib import Path

_d = Path(__file__).parent


def _load(alias: str, filename: str):
    spec = importlib.util.spec_from_file_location(alias, _d / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


# Load models eagerly — no cross-package circular deps
_models_mod = _load("_threads_models", "threads.models.py")

ChatThread = _models_mod.ChatThread
ChatMessage = _models_mod.ChatMessage
CHAT_SCOPES = _models_mod.CHAT_SCOPES

# Register layer modules under importable names.
_schemas_mod = _load("app.threads.threads_schemas", "threads.schemas.py")
_repo_mod = _load("app.threads.threads_repository", "threads.repository.py")
_service_mod = _load("app.threads.threads_service", "threads.service.py")
_controller_mod = _load("app.threads.threads_controller", "threads.controller.py")


def __getattr__(name: str):
    """Lazy access for router and helpers to avoid circular imports at package init time."""
    if name == "router":
        _router_mod = _load("_threads_router", "threads.router.py")
        import app.threads as _self
        _self.router = _router_mod.router
        _self.ensure_default_thread = _router_mod.ensure_default_thread
        return _router_mod.router
    if name == "ensure_default_thread":
        _router_mod = _load("_threads_router", "threads.router.py")
        import app.threads as _self
        _self.router = _router_mod.router
        _self.ensure_default_thread = _router_mod.ensure_default_thread
        return _router_mod.ensure_default_thread
    if name == "threads_repository":
        return _repo_mod
    if name == "threads_service":
        return _service_mod
    if name == "threads_schemas":
        return _schemas_mod
    if name == "threads_controller":
        return _controller_mod
    raise AttributeError(f"module 'app.threads' has no attribute {name!r}")
