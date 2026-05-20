"""Auth repository — SQLAlchemy queries only. No FastAPI imports allowed."""
from sqlalchemy.orm import Session

from app.auth import User


def get_or_create_user(db: Session, username: str) -> User:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
