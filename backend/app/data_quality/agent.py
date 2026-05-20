# backward-compat shim — redirect to pipeline/agent.py
# This replaces the shim module itself in sys.modules so that all attributes
# (including private ones like _tool_describe_dataset) are accessible.
import sys
import importlib

_pipeline_mod = importlib.import_module("app.data_quality.pipeline.agent")
sys.modules[__name__] = _pipeline_mod
