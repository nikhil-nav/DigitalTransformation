"""Data Quality Assessment module.

Excel-workbook ingestion, per-sheet statistical profiling, cross-sheet
referential checks, and AI-driven annotation. Each submodule has a single
narrow responsibility; the router wires them together at HTTP boundaries.
"""
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


_models_mod = _load("_dq_models", "data_quality.models.py")

# Re-export ORM models and constants
DataQualityDataset = _models_mod.DataQualityDataset
DataQualitySheetProfile = _models_mod.DataQualitySheetProfile
DataQualityColumnProfile = _models_mod.DataQualityColumnProfile
DataQualityIssue = _models_mod.DataQualityIssue
DataQualityFunctionalDependency = _models_mod.DataQualityFunctionalDependency
DataQualityRelationship = _models_mod.DataQualityRelationship
DataQualityProfileConfig = _models_mod.DataQualityProfileConfig
DataQualityColumnMapping = _models_mod.DataQualityColumnMapping
DataQualitySimilarityRun = _models_mod.DataQualitySimilarityRun
DataQualityRecordCluster = _models_mod.DataQualityRecordCluster
DataQualityRecordPair = _models_mod.DataQualityRecordPair
DQ_RAG_VALUES = _models_mod.DQ_RAG_VALUES
DQ_SEVERITY_VALUES = _models_mod.DQ_SEVERITY_VALUES
DQ_ISSUE_DIMENSIONS = _models_mod.DQ_ISSUE_DIMENSIONS
DQ_AI_STATUSES = _models_mod.DQ_AI_STATUSES
DQ_RELATIONSHIP_STATUSES = _models_mod.DQ_RELATIONSHIP_STATUSES
DQ_RELATIONSHIP_CARDINALITIES = _models_mod.DQ_RELATIONSHIP_CARDINALITIES

# Register layer modules under importable names.
_schemas_mod = _load("app.data_quality.data_quality_schemas", "data_quality.schemas.py")
_repo_mod = _load("app.data_quality.data_quality_repository", "data_quality.repository.py")
_service_mod = _load("app.data_quality.data_quality_service", "data_quality.service.py")
_controller_mod = _load("app.data_quality.data_quality_controller", "data_quality.controller.py")


def __getattr__(name: str):
    """Lazy attribute access for router and pipeline modules (avoids circular import at package init)."""
    if name == "router":
        from app.data_quality.router import router
        import app.data_quality as _self
        _self.router = router
        return router
    # Pipeline module access: e.g. `from app.data_quality import agent`
    _pipeline_modules = {
        "agent", "annotator", "cluster", "cross", "inspect",
        "normalize", "parsers", "profile", "recommend",
        "similarity", "similarity_llm", "stats",
    }
    if name in _pipeline_modules:
        mod = importlib.import_module(f"app.data_quality.{name}")
        import app.data_quality as _self
        setattr(_self, name, mod)
        return mod
    if name == "data_quality_schemas":
        return _schemas_mod
    if name == "data_quality_repository":
        return _repo_mod
    if name == "data_quality_service":
        return _service_mod
    if name == "data_quality_controller":
        return _controller_mod
    raise AttributeError(f"module 'app.data_quality' has no attribute {name!r}")
