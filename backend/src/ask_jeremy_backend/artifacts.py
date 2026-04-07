from __future__ import annotations

from dataclasses import dataclass
from mimetypes import guess_type
from pathlib import Path

_INTERNAL_ARTIFACT_PREFIXES = ("sql/",)


@dataclass(frozen=True)
class ArtifactFile:
    path: str
    relative_path: str
    filename: str
    mime_type: str | None
    size_bytes: int


def session_artifact_root(session_root: Path, session_id: str) -> Path | None:
    if not session_id:
        return None
    return session_root / session_id / "artifacts"


def snapshot_artifacts(artifact_root: Path | None) -> dict[str, tuple[int, int]]:
    if artifact_root is None or not artifact_root.exists():
        return {}

    snapshot: dict[str, tuple[int, int]] = {}
    for path in artifact_root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        snapshot[str(path.resolve())] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def collect_artifacts(
    artifact_root: Path | None,
    before_snapshot: dict[str, tuple[int, int]],
) -> list[ArtifactFile]:
    if artifact_root is None or not artifact_root.exists():
        return []

    artifacts: list[ArtifactFile] = []
    for path in sorted(artifact_root.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        resolved = str(path.resolve())
        signature = (stat.st_size, stat.st_mtime_ns)
        if before_snapshot.get(resolved) == signature:
            continue
        mime_type, _ = guess_type(path.name)
        artifacts.append(
            ArtifactFile(
                path=resolved,
                relative_path=path.relative_to(artifact_root).as_posix(),
                filename=path.name,
                mime_type=mime_type,
                size_bytes=stat.st_size,
            )
        )
    return artifacts


def is_user_visible_artifact(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").lstrip("./")
    if normalized == "sql":
        return False
    return not any(normalized.startswith(prefix) for prefix in _INTERNAL_ARTIFACT_PREFIXES)


def resolve_session_artifact_path(
    session_root: Path,
    session_id: str,
    relative_path: str,
) -> Path:
    artifact_root = session_artifact_root(session_root, session_id)
    if artifact_root is None:
        raise ValueError("Session artifacts path could not be resolved.")

    candidate = (artifact_root / relative_path).resolve(strict=True)
    root = artifact_root.resolve(strict=True)
    if candidate != root and root not in candidate.parents:
        raise ValueError("Artifact path is outside the session artifacts directory.")
    if not candidate.is_file():
        raise ValueError("Artifact path does not reference a file.")
    return candidate
