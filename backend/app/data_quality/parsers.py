# backward-compat shim — redirect to pipeline/parsers.py
import sys
import importlib

_pipeline_mod = importlib.import_module("app.data_quality.pipeline.parsers")
sys.modules[__name__] = _pipeline_mod
