# backward-compat shim — redirect to pipeline/similarity_llm.py
import sys
import importlib

_pipeline_mod = importlib.import_module("app.data_quality.pipeline.similarity_llm")
sys.modules[__name__] = _pipeline_mod
