"""Data Quality pipeline subpackage.

All analysis modules live here. Import paths:
    from app.data_quality.pipeline.normalize import ...
    from app.data_quality.pipeline.cluster import ...
    etc.

For backward compatibility, the parent package re-exports each module so that
    from app.data_quality.normalize import ...
    from app.data_quality import annotator
    from app.data_quality import cluster
continue to work without modification.
"""
