Add a new Data Quality feature — a quality check, normalization option, similarity algorithm, or analysis metric.

$ARGUMENTS describes the feature — e.g., "add URL format validation as a pattern check in the profile module".

Steps:
1. Read `backend/app/data_quality/router.py` to understand the full pipeline
2. Identify the right module: profile, stats, normalize, similarity, cluster, cross, annotator, or recommend
3. Implement the logic in that module
4. Expose via a new or extended endpoint in `router.py`
5. If it's a **normalization option**: add to `normalize.py` AND update `DataQualityConfigPage` in the frontend
6. If it's a **new algorithm**: register it in `recommend.py` for auto-selection
7. If it produces a visible **metric or score**: add a chart/section in `DataQualityDashboard`
8. Add tests in `backend/tests/test_data_quality_<module>.py`
9. Run `cd backend && pytest tests/test_data_quality*.py` to verify

Pipeline flow for reference: `upload → profile → normalize → similarity → cluster → annotate`
