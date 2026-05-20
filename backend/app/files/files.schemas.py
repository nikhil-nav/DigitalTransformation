"""Files module Pydantic schemas — no ORM, no FastAPI imports."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

FileKind = Literal["pdf", "image"]


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    anthropic_file_id: str
    original_filename: str
    kind: FileKind
    mime_type: str
    size_bytes: int
    uploaded_at: datetime
