# backward-compat shim — redirect to pipeline/inspect.py
import sys
import importlib

_pipeline_mod = importlib.import_module("app.data_quality.pipeline.inspect")
sys.modules[__name__] = _pipeline_mod
