# backward compat re-export shim — do not add logic here
from app.common.db import Base
from app.auth import User
from app.projects import Project, ProjectType, ValueDiscoveryOpportunity
from app.threads import ChatThread, ChatMessage, CHAT_SCOPES
from app.files import BcmFile
from app.bcm import BcmCapability
from app.data_quality import (
    DataQualityDataset,
    DataQualitySheetProfile,
    DataQualityColumnProfile,
    DataQualityIssue,
    DataQualityFunctionalDependency,
    DataQualityRelationship,
    DataQualityProfileConfig,
    DataQualityColumnMapping,
    DataQualitySimilarityRun,
    DataQualityRecordCluster,
    DataQualityRecordPair,
    DataQualityClusterGoldenValue,
    DQ_RAG_VALUES,
    DQ_SEVERITY_VALUES,
    DQ_ISSUE_DIMENSIONS,
    DQ_AI_STATUSES,
    DQ_RELATIONSHIP_STATUSES,
    DQ_RELATIONSHIP_CARDINALITIES,
)
from app.it_map.models import (
    ApplicationInventory,
    ApplicationInventorySchema,
    Application,
    ApplicationCapabilityMapping,
    ITMapAgentRun,
)

__all__ = [
    "Base",
    "User",
    "Project",
    "ProjectType",
    "ValueDiscoveryOpportunity",
    "ChatThread",
    "ChatMessage",
    "CHAT_SCOPES",
    "BcmFile",
    "BcmCapability",
    "DataQualityDataset",
    "DataQualitySheetProfile",
    "DataQualityColumnProfile",
    "DataQualityIssue",
    "DataQualityFunctionalDependency",
    "DataQualityRelationship",
    "DataQualityProfileConfig",
    "DataQualityColumnMapping",
    "DataQualitySimilarityRun",
    "DataQualityRecordCluster",
    "DataQualityRecordPair",
    "DataQualityClusterGoldenValue",
    "DQ_RAG_VALUES",
    "DQ_SEVERITY_VALUES",
    "DQ_ISSUE_DIMENSIONS",
    "DQ_AI_STATUSES",
    "DQ_RELATIONSHIP_STATUSES",
    "DQ_RELATIONSHIP_CARDINALITIES",
    "ApplicationInventory",
    "ApplicationInventorySchema",
    "Application",
    "ApplicationCapabilityMapping",
    "ITMapAgentRun",
]
