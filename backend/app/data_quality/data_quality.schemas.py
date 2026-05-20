"""Data Quality Pydantic schemas — no ORM, no FastAPI imports.

These are the canonical schema definitions for the data_quality module.
app.schemas re-exports them for backward compatibility.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DqRag = Literal["green", "amber", "red"]
DqSeverity = Literal["low", "medium", "high", "critical"]
DqDimension = Literal[
    "completeness",
    "consistency",
    "uniqueness",
    "validity",
    "accuracy",
    "redundancy",
]
DqAiStatus = Literal["pending", "running", "done", "failed"]
DqRelationshipStatus = Literal["suggested", "confirmed", "dismissed"]
DqCardinality = Literal["one_to_one", "many_to_one", "unknown"]
DqAlgorithm = Literal[
    "exact",
    "levenshtein",
    "jaro_winkler",
    "jaccard_tokens",
    "cosine_tokens",
    "soundex",
    "metaphone",
    "ngram",
    "numeric_tolerance",
    "date_proximity",
]
DqParser = Literal["phone", "email", "date"]
DqRecommendedBy = Literal["heuristic", "llm", "user"]
DqRunStatus = Literal["running", "done", "failed"]


class DataQualitySheetSummary(BaseModel):
    name: str
    row_count: int
    column_count: int


class DataQualityDatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    original_filename: str
    file_sha256: str
    size_bytes: int
    sheets: list[DataQualitySheetSummary]
    engine_version: str
    uploaded_at: datetime
    profiled_at: datetime | None
    annotation_status: Literal["pending", "running", "done", "failed"]
    annotation_error: str | None = None
    annotated_at: datetime | None = None
    config_completed_at: datetime | None = None


class DataQualityTopValue(BaseModel):
    value: str
    count: int


class DataQualityColumnProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    ordinal: int
    inferred_dtype: str
    semantic_type: str
    type_mismatch_count: int
    null_count: int
    null_pct: float
    distinct_count: int
    distinct_pct: float
    top_values: list[DataQualityTopValue]
    numeric_min: float | None
    numeric_max: float | None
    numeric_mean: float | None
    numeric_median: float | None
    numeric_std: float | None
    numeric_p25: float | None
    numeric_p75: float | None
    date_min: str | None
    date_max: str | None
    pattern_label: str | None
    pattern_conformance_pct: float | None
    outlier_iqr_count: int | None
    outlier_mad_count: int | None
    range_min: float | None
    range_max: float | None
    range_violation_count: int | None
    rag: DqRag
    computed_at: datetime


class DataQualitySheetProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sheet_name: str
    row_count: int
    column_count: int
    exact_duplicate_row_count: int
    completeness_pct: float
    rag: DqRag
    engine_version: str
    computed_at: datetime
    columns: list[DataQualityColumnProfileOut]


class DataQualityIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sheet_name: str
    column_name: str | None
    dimension: DqDimension
    severity: DqSeverity
    description: str
    sample_value_count: int
    sample_values: list[str]
    engine_version: str
    ai_narrative: str | None
    ai_fix: str | None
    ai_status: DqAiStatus
    created_at: datetime


class DataQualityBoundsUpdate(BaseModel):
    range_min: float | None = None
    range_max: float | None = None


class DataQualityFunctionalDependencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sheet_name: str
    determinant_column: str
    dependent_column: str
    confidence_pct: float
    counter_example_count: int
    sample_counter_examples: list[str]
    engine_version: str
    computed_at: datetime


class DataQualityRelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_sheet: str
    parent_column: str
    child_sheet: str
    child_column: str
    type_match: bool
    name_similarity: float
    subset_coverage: float
    cardinality: DqCardinality
    confidence_pct: float
    status: DqRelationshipStatus
    engine_version: str
    suggested_at: datetime
    confirmed_at: datetime | None
    dismissed_at: datetime | None


class DataQualityRelationshipStatusUpdate(BaseModel):
    status: Literal["confirmed", "dismissed"]


class DataQualityColumnMappingIn(BaseModel):
    column_a: str = Field(min_length=1)
    column_b: str = Field(min_length=1)
    algorithm: DqAlgorithm
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    is_important: bool = False
    parser: DqParser | None = None
    recommended_by: DqRecommendedBy = "user"


class DataQualityColumnMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    column_a: str
    column_b: str
    algorithm: DqAlgorithm
    weight: float
    is_important: bool
    parser: DqParser | None
    recommended_by: DqRecommendedBy


class DataQualityProfileConfigIn(BaseModel):
    sheet_a: str = Field(min_length=1)
    sheet_b: str = Field(min_length=1)
    normalization: dict[str, bool] = Field(default_factory=dict)
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    mappings: list[DataQualityColumnMappingIn] = Field(default_factory=list)


class DataQualityProfileConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sheet_a: str | None
    sheet_b: str | None
    normalization: dict[str, bool]
    threshold: float
    engine_version: str
    created_at: datetime
    updated_at: datetime
    mappings: list[DataQualityColumnMappingOut]


class DataQualityConfigDraftOut(BaseModel):
    saved: bool = False
    available_sheets: list[str]
    suggested_sheet_a: str | None
    suggested_sheet_b: str | None
    normalization: dict[str, bool]
    threshold: float
    mappings: list[DataQualityColumnMappingIn]


class DataQualitySimilarityRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dataset_id: int
    config_id: int
    sheet_a: str
    sheet_b: str
    threshold: float
    status: DqRunStatus
    candidate_pair_count: int
    passing_pair_count: int
    cluster_count: int
    blocking_column: str | None
    error: str | None
    engine_version: str
    started_at: datetime
    finished_at: datetime | None


class DataQualityRecordClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    cluster_index: int
    a_member_count: int
    b_member_count: int
    top_score: float
    min_score: float
    canonical_key: dict[str, str | int | float | None]
    a_members: list[int]
    b_members: list[int]


class DataQualityRecordPairOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cluster_id: int | None
    row_a_index: int
    row_b_index: int
    score: float
    per_column_scores: dict[str, float]


class DataQualityClusterDetailOut(BaseModel):
    cluster: DataQualityRecordClusterOut
    pairs: list[DataQualityRecordPairOut]
    a_rows: list[dict[str, str | int | float | None]]
    b_rows: list[dict[str, str | int | float | None]]


class DataQualitySkipConfigOut(BaseModel):
    config_completed_at: datetime


class DataQualityRecommendIn(BaseModel):
    sheet_a: str = Field(min_length=1)
    sheet_b: str = Field(min_length=1)
    existing_mappings: list[DataQualityColumnMappingIn] = Field(default_factory=list)


class DataQualityRecommendOut(BaseModel):
    normalization: dict[str, bool]
    threshold: float
    mappings: list[DataQualityColumnMappingIn]
    llm_error: str | None = None
