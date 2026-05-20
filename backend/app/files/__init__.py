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
_models_mod = _load("_files_models", "files.models.py")

BcmFile = _models_mod.BcmFile

# Register layer modules under importable names.
_schemas_mod = _load("app.files.files_schemas", "files.schemas.py")
_repo_mod = _load("app.files.files_repository", "files.repository.py")
_service_mod = _load("app.files.files_service", "files.service.py")
_controller_mod = _load("app.files.files_controller", "files.controller.py")


def __getattr__(name: str):
    """Lazy access for router and layer modules."""
    if name == "router":
        _router_mod = _load("_files_router", "files.router.py")
        import app.files as _self
        _self.router = _router_mod.router
        return _router_mod.router
    if name == "files_schemas":
        return _schemas_mod
    if name == "files_repository":
        return _repo_mod
    if name == "files_service":
        return _service_mod
    if name == "files_controller":
        return _controller_mod
    raise AttributeError(f"module 'app.files' has no attribute {name!r}")
