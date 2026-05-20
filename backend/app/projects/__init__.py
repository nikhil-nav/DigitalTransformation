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
_models_mod = _load("_projects_models", "projects.models.py")

Project = _models_mod.Project
ProjectType = _models_mod.ProjectType
ValueDiscoveryOpportunity = _models_mod.ValueDiscoveryOpportunity

# Load layer modules eagerly and register under importable names.
_repo_mod = _load("app.projects.projects_repository", "projects.repository.py")
_schemas_mod = _load("app.projects.projects_schemas", "projects.schemas.py")
_service_mod = _load("app.projects.projects_service", "projects.service.py")
_controller_mod = _load("app.projects.projects_controller", "projects.controller.py")


def __getattr__(name: str):
    """Lazy access for router, service, schemas to avoid circular imports at package init time."""
    if name == "router":
        _router_mod = _load("_projects_router", "projects.router.py")
        import app.projects as _self
        _self.router = _router_mod.router
        return _router_mod.router
    if name == "projects_repository":
        return _repo_mod
    if name == "projects_schemas":
        return _schemas_mod
    if name == "projects_service":
        return _service_mod
    if name == "projects_controller":
        return _controller_mod
    raise AttributeError(f"module 'app.projects' has no attribute {name!r}")
