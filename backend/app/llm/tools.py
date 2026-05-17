"""Tools the BCM agent can call.

Each tool has:
- a Python implementation (`fetch_url`, `extract_pdf`, `web_search`, `set_capabilities`)
- an Anthropic-format tool definition in ANTHROPIC_TOOLS.

Network-touching tools enforce an SSRF guard, request timeout, and size cap.
"""
from __future__ import annotations

import socket
from io import BytesIO
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models import BcmCapability

MAX_BYTES = 1_000_000
TIMEOUT_SECONDS = 10.0


def _is_safe_url(url: str) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "URL must use http or https"
    if not parsed.hostname:
        return False, "URL must have a hostname"

    try:
        ip = ip_address(socket.gethostbyname(parsed.hostname))
    except (ValueError, socket.gaierror) as e:
        return False, f"Could not resolve {parsed.hostname}: {e}"

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return (
            False,
            "URL resolves to a private/loopback/reserved IP and cannot be fetched",
        )
    return True, None


def fetch_url(url: str) -> str:
    """GET a public URL; return up to 1 MB of decoded text."""
    ok, err = _is_safe_url(url)
    if not ok:
        raise ValueError(err)

    with httpx.Client(
        timeout=TIMEOUT_SECONDS, follow_redirects=True, max_redirects=5
    ) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in r.iter_bytes():
                total += len(chunk)
                chunks.append(chunk)
                if total >= MAX_BYTES:
                    break
    return b"".join(chunks)[:MAX_BYTES].decode("utf-8", errors="replace")


def extract_pdf(url: str) -> str:
    """Download a PDF from a public URL and return its text content."""
    ok, err = _is_safe_url(url)
    if not ok:
        raise ValueError(err)

    with httpx.Client(
        timeout=TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        r = client.get(url)
        r.raise_for_status()
        if len(r.content) > MAX_BYTES:
            raise ValueError(f"PDF exceeds {MAX_BYTES} bytes")
        reader = PdfReader(BytesIO(r.content))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                pages.append(text)
        return "\n\n".join(pages)


def set_capabilities(
    db: Session, project_id: int, tree: list[dict[str, Any]]
) -> dict[str, Any]:
    """Replace the project's capability tree with the supplied L1/L2/L3 list.

    `tree` is a list of L1 dicts: {name, description?, children: [L2 dicts]}.
    Each L2 dict has the same shape with L3 children. L3 has no children.
    """
    db.query(BcmCapability).filter_by(project_id=project_id).delete()
    db.flush()

    for l1_pos, l1 in enumerate(tree):
        l1_row = BcmCapability(
            project_id=project_id,
            parent_id=None,
            level=1,
            name=l1["name"],
            description=l1.get("description"),
            position=l1_pos,
        )
        db.add(l1_row)
        db.flush()
        for l2_pos, l2 in enumerate(l1.get("children", []) or []):
            l2_row = BcmCapability(
                project_id=project_id,
                parent_id=l1_row.id,
                level=2,
                name=l2["name"],
                description=l2.get("description"),
                position=l2_pos,
            )
            db.add(l2_row)
            db.flush()
            for l3_pos, l3 in enumerate(l2.get("children", []) or []):
                l3_row = BcmCapability(
                    project_id=project_id,
                    parent_id=l2_row.id,
                    level=3,
                    name=l3["name"],
                    description=l3.get("description"),
                    position=l3_pos,
                )
                db.add(l3_row)
    db.commit()
    return {"ok": True, "l1_count": len(tree)}


# --- Tool schemas (Anthropic format) ---

_CAPABILITY_NODE = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["name"],
}

_L2_NODE = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "children": {"type": "array", "items": _CAPABILITY_NODE},
    },
    "required": ["name"],
}

_L1_NODE = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "children": {"type": "array", "items": _L2_NODE},
    },
    "required": ["name"],
}

ANTHROPIC_TOOLS: list[dict[str, Any]] = [
    {
        "name": "fetch_url",
        "description": (
            "Fetch a public web page and return up to 1 MB of decoded text. "
            "Use for company websites, About pages, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "An http(s) URL"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "extract_pdf",
        "description": (
            "Download a PDF from a public URL and return its extracted text. "
            "Use for annual reports, white papers, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL pointing to a PDF"}
            },
            "required": ["url"],
        },
    },
    {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 5,
    },
    {
        "name": "set_capabilities",
        "description": (
            "Replace the entire Business Capability Map with the supplied L1/L2/L3 "
            "tree. Call this once you have enough information to draft the BCM. "
            "Each L1 may have L2 children, each L2 may have L3 children. Aim for "
            "5-10 L1s, 3-7 L2s per L1, and 0-5 L3s per L2."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tree": {
                    "type": "array",
                    "description": "List of L1 capabilities, top-down.",
                    "items": _L1_NODE,
                }
            },
            "required": ["tree"],
        },
    },
]
