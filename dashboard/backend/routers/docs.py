"""
Vehicle reference docs router — CRUD for vehicle_reference/*.md files.
"""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from profiles import load_profiles, _find_vehicle_doc

router = APIRouter(prefix="/docs", tags=["docs"])

_PROFILES_YAML = Path(__file__).parent.parent.parent.parent / "profiles.yaml"

# Only allow safe filenames: letters, digits, underscores, hyphens, dots
_SAFE_FILENAME_RE = re.compile(r"^[\w\-]+\.md$")


def _docs_dir() -> Path:
    """Resolved path to the vehicle_reference directory (from live config)."""
    return Path(config.VEHICLE_REFERENCE_DIR)


def _check_filename(filename: str) -> None:
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(
            422,
            "Filename must match [a-zA-Z0-9_-]+\\.md  "
            "(e.g. honda_crv.md).  No path separators allowed.",
        )


def _matched_profiles(filename: str) -> list[str]:
    """Return the profile_ids that would auto-select this doc via _find_vehicle_doc()."""
    docs_dir = _docs_dir()
    if not docs_dir.is_dir():
        return []
    try:
        profiles = load_profiles(str(_PROFILES_YAML))
    except Exception:
        return []

    matched: list[str] = []
    for profile in profiles:
        for make, model in profile.vehicles:
            best = _find_vehicle_doc(make, model, docs_dir)
            if best and best.name == filename:
                matched.append(profile.profile_id)
                break  # already matched this profile
    return matched


class DocContent(BaseModel):
    content: str


class GenerateRequest(BaseModel):
    make: str
    model: str
    year_start: int
    year_end: int
    notes: str = ""


# Register before /{filename} so the literal path wins.
@router.post("/generate")
async def generate_doc(body: GenerateRequest):
    """Use Cerebras to generate a vehicle reference markdown document."""
    from dashboard.backend.doc_generator import generate_vehicle_doc
    try:
        content = generate_vehicle_doc(body.make.strip(), body.model.strip(), body.year_start, body.year_end, body.notes)
        return {"content": content}
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")


@router.get("")
def list_docs():
    """List all .md files in vehicle_reference/."""
    docs_dir = _docs_dir()
    if not docs_dir.is_dir():
        return []

    result = []
    for path in sorted(docs_dir.glob("*.md")):
        result.append({
            "filename":        path.name,
            "size_bytes":      path.stat().st_size,
            "matched_profiles": _matched_profiles(path.name),
        })
    return result


@router.get("/{filename}")
def get_doc(filename: str):
    """Return the content of a single reference doc."""
    _check_filename(filename)
    path = _docs_dir() / filename
    if not path.exists():
        raise HTTPException(404, f"Doc '{filename}' not found")
    return {"filename": filename, "content": path.read_text(encoding="utf-8")}


@router.put("/{filename}")
def put_doc(filename: str, body: DocContent):
    """Create or overwrite a reference doc."""
    _check_filename(filename)
    docs_dir = _docs_dir()
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / filename
    path.write_text(body.content, encoding="utf-8")
    return {
        "filename":         filename,
        "size_bytes":       path.stat().st_size,
        "matched_profiles": _matched_profiles(filename),
    }


@router.delete("/{filename}")
def delete_doc(filename: str):
    """Delete a reference doc."""
    _check_filename(filename)
    path = _docs_dir() / filename
    if not path.exists():
        raise HTTPException(404, f"Doc '{filename}' not found")
    path.unlink()
    return {"deleted": filename}
