"""Data Quality repository — SQLAlchemy queries only. No FastAPI imports allowed."""
from __future__ import annotations

from sqlalchemy.orm import Session


def get_project(db: Session, project_id: int, user_id: int):
    """Return a Project row or None."""
    from app.models import Project
    return db.query(Project).filter_by(id=project_id, user_id=user_id).one_or_none()


def get_dataset(db: Session, dataset_id: int, project_id: int):
    """Return a DataQualityDataset row or None."""
    from app.models import DataQualityDataset
    return (
        db.query(DataQualityDataset)
        .filter_by(id=dataset_id, project_id=project_id)
        .one_or_none()
    )


def list_datasets(db: Session, project_id: int):
    """Return all datasets for a project ordered by upload time descending."""
    from app.models import DataQualityDataset
    return (
        db.query(DataQualityDataset)
        .filter_by(project_id=project_id)
        .order_by(DataQualityDataset.uploaded_at.desc())
        .all()
    )


def create_dataset(db: Session, project_id: int, **kwargs):
    """Insert a DataQualityDataset row and return it."""
    from app.models import DataQualityDataset
    row = DataQualityDataset(project_id=project_id, **kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_dataset(db: Session, dataset, **updates):
    """Apply updates to a dataset and commit."""
    for key, value in updates.items():
        setattr(dataset, key, value)
    db.commit()
    db.refresh(dataset)
    return dataset


def delete_dataset(db: Session, dataset) -> None:
    """Delete a dataset row."""
    db.delete(dataset)
    db.commit()


def get_sheet_profile(db: Session, dataset_id: int, sheet_name: str):
    """Return a DataQualitySheetProfile or None."""
    from app.models import DataQualitySheetProfile
    return (
        db.query(DataQualitySheetProfile)
        .filter_by(dataset_id=dataset_id, sheet_name=sheet_name)
        .one_or_none()
    )


def list_sheet_profiles(db: Session, dataset_id: int):
    """Return all sheet profiles for a dataset."""
    from app.models import DataQualitySheetProfile
    return db.query(DataQualitySheetProfile).filter_by(dataset_id=dataset_id).all()


def get_column_profile(db: Session, profile_id: int, column_name: str):
    """Return a DataQualityColumnProfile or None."""
    from app.models import DataQualityColumnProfile
    return (
        db.query(DataQualityColumnProfile)
        .filter_by(sheet_profile_id=profile_id, name=column_name)
        .one_or_none()
    )


def list_issues(db: Session, dataset_id: int):
    """Return all issues for a dataset."""
    from app.models import DataQualityIssue
    return (
        db.query(DataQualityIssue)
        .filter_by(dataset_id=dataset_id)
        .order_by(DataQualityIssue.created_at.asc())
        .all()
    )


def get_profile_config(db: Session, dataset_id: int):
    """Return the profile config for a dataset or None."""
    from app.models import DataQualityProfileConfig
    return (
        db.query(DataQualityProfileConfig)
        .filter_by(dataset_id=dataset_id)
        .one_or_none()
    )


def list_similarity_runs(db: Session, dataset_id: int):
    """Return all similarity runs for a dataset ordered by start time descending."""
    from app.models import DataQualitySimilarityRun
    return (
        db.query(DataQualitySimilarityRun)
        .filter_by(dataset_id=dataset_id)
        .order_by(DataQualitySimilarityRun.started_at.desc())
        .all()
    )


def get_similarity_run(db: Session, run_id: int, dataset_id: int):
    """Return a similarity run or None."""
    from app.models import DataQualitySimilarityRun
    return (
        db.query(DataQualitySimilarityRun)
        .filter_by(id=run_id, dataset_id=dataset_id)
        .one_or_none()
    )


def list_clusters(db: Session, run_id: int):
    """Return all clusters for a run."""
    from app.models import DataQualityRecordCluster
    return (
        db.query(DataQualityRecordCluster)
        .filter_by(run_id=run_id)
        .order_by(DataQualityRecordCluster.cluster_index.asc())
        .all()
    )


def get_cluster(db: Session, cluster_id: int, run_id: int):
    """Return a cluster or None."""
    from app.models import DataQualityRecordCluster
    return (
        db.query(DataQualityRecordCluster)
        .filter_by(id=cluster_id, run_id=run_id)
        .one_or_none()
    )


def list_relationships(db: Session, dataset_id: int):
    """Return all cross-sheet relationships for a dataset."""
    from app.models import DataQualityRelationship
    return (
        db.query(DataQualityRelationship)
        .filter_by(dataset_id=dataset_id)
        .order_by(DataQualityRelationship.confidence_pct.desc())
        .all()
    )


def get_relationship(db: Session, relationship_id: int, dataset_id: int):
    """Return a relationship or None."""
    from app.models import DataQualityRelationship
    return (
        db.query(DataQualityRelationship)
        .filter_by(id=relationship_id, dataset_id=dataset_id)
        .one_or_none()
    )


def get_chat_thread(db: Session, thread_id: int, project_id: int, scope: str):
    """Return a ChatThread or None."""
    from app.models import ChatThread
    return (
        db.query(ChatThread)
        .filter_by(id=thread_id, project_id=project_id, scope=scope)
        .one_or_none()
    )


def get_oldest_chat_thread(db: Session, project_id: int, scope: str):
    """Return the oldest chat thread for a project+scope, or None."""
    from app.models import ChatThread
    return (
        db.query(ChatThread)
        .filter_by(project_id=project_id, scope=scope)
        .order_by(ChatThread.created_at.asc(), ChatThread.id.asc())
        .first()
    )


def create_chat_thread(db: Session, project_id: int, scope: str, title: str):
    """Insert and return a new ChatThread."""
    from app.models import ChatThread
    thread = ChatThread(project_id=project_id, scope=scope, title=title)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def list_chat_messages(db: Session, project_id: int, thread_id: int, scope: str):
    """Return chat messages for a project+thread+scope ordered by time."""
    from app.models import ChatMessage
    return (
        db.query(ChatMessage)
        .filter_by(project_id=project_id, thread_id=thread_id, scope=scope)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
