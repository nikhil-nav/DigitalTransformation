# backward-compat shim — redirect to pipeline/similarity.py
import sys
import importlib

_pipeline_mod = importlib.import_module("app.data_quality.pipeline.similarity")
sys.modules[__name__] = _pipeline_mod
