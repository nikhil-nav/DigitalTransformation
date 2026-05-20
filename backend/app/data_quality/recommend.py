# backward-compat shim — redirect to pipeline/recommend.py
import sys
import importlib

_pipeline_mod = importlib.import_module("app.data_quality.pipeline.recommend")
sys.modules[__name__] = _pipeline_mod
