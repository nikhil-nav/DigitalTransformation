import importlib.util
import sys
from pathlib import Path

_d = Path(__file__).parent


def _load(alias: str, filename: str):
    spec = importlib.util.spec_from_file_location(alias, _d / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod  # register BEFORE exec to allow cross-file refs
    spec.loader.exec_module(mod)
    return mod


# Load models eagerly — User model only depends on app.common.db (no circular deps)
_models_mod = _load("_auth_models", "auth.models.py")
User = _models_mod.User

# Register service, repository, schemas, and controller under importable names
# so that other layer files can do `from app.auth.auth_service import ...`.
_service_mod = _load("app.auth.auth_service", "auth.service.py")
_repo_mod = _load("app.auth.auth_repository", "auth.repository.py")
_schemas_mod = _load("app.auth.auth_schemas", "auth.schemas.py")
_controller_mod = _load("app.auth.auth_controller", "auth.controller.py")


def __getattr__(name: str):
    """Lazy access for router, service, repository, and auth helpers to avoid circular imports."""
    _router_names = {
        "router", "SESSION_COOKIE", "sessions", "get_current_user",
        "get_current_user_row", "LoginRequest", "UserResponse",
        "LlmKeysRequest", "LlmKeysStatus",
    }
    _service_names = {
        "handle_login", "handle_logout", "handle_set_llm_keys",
        "handle_get_llm_keys", "handle_clear_llm_keys",
    }
    _repository_names = {
        "get_or_create_user",
    }

    if name in _router_names:
        _router_mod = _load("_auth_router", "auth.router.py")
        import app.auth as _self
        _self.router = _router_mod.router
        _self.SESSION_COOKIE = _router_mod.SESSION_COOKIE
        _self.sessions = _router_mod.sessions
        _self.get_current_user = _router_mod.get_current_user
        _self.get_current_user_row = _router_mod.get_current_user_row
        _self.LoginRequest = _router_mod.LoginRequest
        _self.UserResponse = _router_mod.UserResponse
        _self.LlmKeysRequest = _router_mod.LlmKeysRequest
        _self.LlmKeysStatus = _router_mod.LlmKeysStatus
        return getattr(_router_mod, name)

    if name in _service_names:
        return getattr(_service_mod, name)

    if name in _repository_names:
        return getattr(_repo_mod, name)

    if name == "auth_service":
        return _service_mod
    if name == "auth_repository":
        return _repo_mod
    if name == "auth_schemas":
        return _schemas_mod
    if name == "auth_controller":
        return _controller_mod

    raise AttributeError(f"module 'app.auth' has no attribute {name!r}")
