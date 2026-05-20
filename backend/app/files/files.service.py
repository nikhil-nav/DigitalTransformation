"""Files service — business logic. No FastAPI imports allowed (AC-6)."""
from __future__ import annotations

MAX_FILE_BYTES = 32 * 1024 * 1024  # 32 MB ceiling per file
ALLOWED_PDF_MIME = {"application/pdf"}
ALLOWED_IMAGE_MIME = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}


def classify_mime(mime_type: str) -> str:
    """Return 'pdf' or 'image', raising ValueError for unsupported types."""
    if mime_type in ALLOWED_PDF_MIME:
        return "pdf"
    if mime_type in ALLOWED_IMAGE_MIME:
        return "image"
    raise ValueError(f"Unsupported file type: {mime_type}")


def validate_file(filename: str | None, contents: bytes, mime_type: str) -> str:
    """Validate upload, returning the file kind. Raises ValueError on any violation."""
    if not filename:
        raise ValueError("Upload missing filename")
    kind = classify_mime(mime_type)
    if len(contents) == 0:
        raise ValueError("Empty file")
    if len(contents) > MAX_FILE_BYTES:
        raise ValueError(
            f"File too large: {len(contents)} bytes (max {MAX_FILE_BYTES} bytes)"
        )
    return kind


def require_anthropic_keys(session_id: str | None, session_keys: dict):
    """Return LlmKeys for the session, raising ValueError if not configured or wrong provider."""
    if session_id is None or session_id not in session_keys:
        raise ValueError("LLM API key not configured. Set it in Chat Settings.")
    keys = session_keys[session_id]
    if keys.provider != "anthropic":
        raise ValueError(
            "File uploads require the Anthropic provider. "
            "Switch to Claude in Chat Settings."
        )
    return keys
