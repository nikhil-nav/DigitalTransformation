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
_models_mod = _load("_bcm_models", "bcm.models.py")

BcmCapability = _models_mod.BcmCapability

# Register layer modules under importable names so service/controller can import them.
_repo_mod = _load("app.bcm.bcm_repository", "bcm.repository.py")
_schemas_mod = _load("app.bcm.bcm_schemas", "bcm.schemas.py")
_service_mod = _load("app.bcm.bcm_service", "bcm.service.py")
_controller_mod = _load("app.bcm.bcm_controller", "bcm.controller.py")


def __getattr__(name: str):
    """Lazy access for router and helpers to avoid circular imports at package init time."""
    if name == "router":
        _router_mod = _load("_bcm_router", "bcm.router.py")
        import app.bcm as _self
        _self.router = _router_mod.router
        _self._user_value_discovery_project_or_404 = _router_mod._user_value_discovery_project_or_404
        return _router_mod.router
    if name == "_user_value_discovery_project_or_404":
        _router_mod = _load("_bcm_router", "bcm.router.py")
        import app.bcm as _self
        _self.router = _router_mod.router
        _self._user_value_discovery_project_or_404 = _router_mod._user_value_discovery_project_or_404
        return _router_mod._user_value_discovery_project_or_404
    if name == "bcm_repository":
        return _repo_mod
    if name == "bcm_schemas":
        return _schemas_mod
    if name == "bcm_service":
        return _service_mod
    if name == "bcm_controller":
        return _controller_mod
    raise AttributeError(f"module 'app.bcm' has no attribute {name!r}")
