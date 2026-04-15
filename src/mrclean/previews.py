from __future__ import annotations

from dataclasses import dataclass
import difflib
import hmac
import hashlib
import json
import os
from pathlib import Path

from .drafts import DraftBundle, DraftOperation

PREVIEW_ARTIFACT_TYPE = "mrclean.preview.v1"
PREVIEW_SIGNATURE_ALGORITHM = "hmac-sha256"


@dataclass(slots=True)
class PreviewOperation:
    path: str
    requested_operation: str
    action: str
    absolute_path: str
    status: str
    validation_reason: str
    expected_sha256: str
    current_sha256: str
    current_exists: bool
    diff: str
    diff_bytes: int
    content_sha256: str = ""
    content: str = ""


@dataclass(slots=True)
class PreviewBundle:
    repository: str
    number: int
    branch: str
    status: str
    summary: str
    operations: tuple[PreviewOperation, ...]
    validation: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(slots=True)
class PreviewArtifactSignature:
    algorithm: str
    key_env: str
    digest: str


@dataclass(slots=True)
class PreviewArtifact:
    bundles: tuple[PreviewBundle, ...]
    signature: PreviewArtifactSignature | None = None


class DraftPreviewer:
    def preview(self, draft: DraftBundle) -> PreviewBundle:
        if draft.status != "ready":
            operations = tuple(
                PreviewOperation(
                    path=operation.path,
                    requested_operation=operation.requested_operation,
                    action=operation.action,
                    absolute_path=operation.absolute_path,
                    status="blocked",
                    validation_reason=operation.validation_reason or "draft bundle is not ready",
                    expected_sha256=operation.expected_sha256,
                    current_sha256="",
                    current_exists=False,
                    diff="",
                    diff_bytes=0,
                    content_sha256=operation.content_sha256,
                    content=operation.content,
                )
                for operation in draft.operations
            )
            return PreviewBundle(
                repository=draft.repository,
                number=draft.number,
                branch=draft.branch,
                status="blocked",
                summary="Preview generation is blocked until the draft bundle is ready.",
                operations=operations,
                validation=draft.validation,
                risks=draft.risks + ("preview generation skipped because the draft bundle is not ready",),
            )

        operations = tuple(self._preview_operation(operation) for operation in draft.operations)
        status = "ready" if all(operation.status == "ready" for operation in operations) else "blocked"
        return PreviewBundle(
            repository=draft.repository,
            number=draft.number,
            branch=draft.branch,
            status=status,
            summary=draft.summary,
            operations=operations,
            validation=draft.validation,
            risks=draft.risks,
        )

    def _preview_operation(self, operation: DraftOperation) -> PreviewOperation:
        target = Path(operation.absolute_path)
        current_exists = target.exists()
        current_sha256 = ""
        current_text = ""
        problems: list[str] = []

        if operation.status != "ready":
            problems.append(operation.validation_reason or "draft operation is not ready")

        if operation.action == "write_file":
            if operation.requested_operation == "create":
                if current_exists:
                    problems.append("target file already exists")
            else:
                if not current_exists:
                    problems.append("target file does not exist")
        elif operation.action == "delete_file":
            if not current_exists:
                problems.append("target file does not exist")
        else:
            problems.append(f"unsupported preview action: {operation.action!r}")

        if current_exists:
            if not target.is_file():
                problems.append("target path is not a regular file")
            else:
                data = target.read_bytes()
                current_sha256 = hashlib.sha256(data).hexdigest()
                try:
                    current_text = data.decode("utf-8")
                except UnicodeDecodeError:
                    problems.append("current file is not UTF-8 text")

        if operation.expected_sha256 and current_sha256 and current_sha256 != operation.expected_sha256:
            problems.append("current file hash no longer matches the expected precondition")

        diff = ""
        if not problems:
            diff = _render_diff(operation, current_text)
            if not diff:
                problems.append("generated operation does not produce a diff")

        status = "blocked" if problems else "ready"
        return PreviewOperation(
            path=operation.path,
            requested_operation=operation.requested_operation,
            action=operation.action,
            absolute_path=operation.absolute_path,
            status=status,
            validation_reason="; ".join(problems) if problems else "ready",
            expected_sha256=operation.expected_sha256,
            current_sha256=current_sha256,
            current_exists=current_exists,
            diff=diff,
            diff_bytes=len(diff.encode("utf-8")) if diff else 0,
            content_sha256=operation.content_sha256,
            content=operation.content,
        )


def _render_diff(operation: DraftOperation, current_text: str) -> str:
    if operation.action == "write_file":
        before = current_text.splitlines(keepends=True)
        after = operation.content.splitlines(keepends=True)
        from_file = "/dev/null" if operation.requested_operation == "create" else f"a/{operation.path}"
        to_file = f"b/{operation.path}"
    else:
        before = current_text.splitlines(keepends=True)
        after = []
        from_file = f"a/{operation.path}"
        to_file = "/dev/null"

    diff_lines = difflib.unified_diff(
        before,
        after,
        fromfile=from_file,
        tofile=to_file,
        lineterm="",
    )
    return "\n".join(diff_lines)


def preview_bundle_to_payload(bundle: PreviewBundle) -> dict[str, object]:
    return {
        "repository": bundle.repository,
        "number": bundle.number,
        "branch": bundle.branch,
        "status": bundle.status,
        "summary": bundle.summary,
        "operations": [
            {
                "path": operation.path,
                "requested_operation": operation.requested_operation,
                "action": operation.action,
                "absolute_path": operation.absolute_path,
                "status": operation.status,
                "validation_reason": operation.validation_reason,
                "expected_sha256": operation.expected_sha256,
                "current_sha256": operation.current_sha256,
                "current_exists": operation.current_exists,
                "diff": operation.diff,
                "diff_bytes": operation.diff_bytes,
                "content_sha256": operation.content_sha256,
                "content": operation.content,
            }
            for operation in bundle.operations
        ],
        "validation": list(bundle.validation),
        "risks": list(bundle.risks),
    }


def preview_bundle_from_payload(payload: dict[str, object]) -> PreviewBundle:
    operations_raw = payload.get("operations", [])
    if not isinstance(operations_raw, list):
        raise ValueError("preview operations must be a list")
    operations = tuple(
        PreviewOperation(
            path=str(item["path"]),
            requested_operation=str(item.get("requested_operation", "modify")),
            action=str(item["action"]),
            absolute_path=str(item["absolute_path"]),
            status=str(item["status"]),
            validation_reason=str(item["validation_reason"]),
            expected_sha256=str(item.get("expected_sha256", "")),
            current_sha256=str(item.get("current_sha256", "")),
            current_exists=bool(item.get("current_exists", False)),
            diff=str(item.get("diff", "")),
            diff_bytes=int(item.get("diff_bytes", 0)),
            content_sha256=str(item.get("content_sha256", "")),
            content=str(item.get("content", "")),
        )
        for item in operations_raw
        if isinstance(item, dict)
    )
    return PreviewBundle(
        repository=str(payload["repository"]),
        number=int(payload["number"]),
        branch=str(payload["branch"]),
        status=str(payload["status"]),
        summary=str(payload["summary"]),
        operations=operations,
        validation=tuple(str(item) for item in payload.get("validation", [])),
        risks=tuple(str(item) for item in payload.get("risks", [])),
    )


def preview_artifact_to_payload(artifact: PreviewArtifact) -> dict[str, object]:
    payload = _unsigned_artifact_payload(artifact.bundles)
    if artifact.signature is not None:
        payload["signature"] = {
            "algorithm": artifact.signature.algorithm,
            "key_env": artifact.signature.key_env,
            "digest": artifact.signature.digest,
        }
    return payload


def preview_artifact_from_payload(payload: dict[str, object]) -> PreviewArtifact:
    if payload.get("artifact_type") != PREVIEW_ARTIFACT_TYPE:
        return PreviewArtifact(bundles=(preview_bundle_from_payload(payload),))

    bundles_raw = payload.get("bundles", [])
    if not isinstance(bundles_raw, list):
        raise ValueError("preview artifact bundles must be a list")
    bundles = tuple(
        preview_bundle_from_payload(item)
        for item in bundles_raw
        if isinstance(item, dict)
    )
    signature_raw = payload.get("signature")
    signature = None
    if signature_raw is not None:
        if not isinstance(signature_raw, dict):
            raise ValueError("preview artifact signature must be an object")
        signature = PreviewArtifactSignature(
            algorithm=str(signature_raw.get("algorithm", "")),
            key_env=str(signature_raw.get("key_env", "")),
            digest=str(signature_raw.get("digest", "")),
        )
    return PreviewArtifact(bundles=bundles, signature=signature)


def dump_preview_bundles(
    path: Path,
    bundles: tuple[PreviewBundle, ...] | list[PreviewBundle],
    *,
    key_env: str | None = None,
) -> PreviewArtifact:
    artifact = PreviewArtifact(bundles=tuple(bundles))
    if key_env:
        artifact.signature = _sign_preview_artifact(artifact.bundles, key_env)
    path.write_text(json.dumps(preview_artifact_to_payload(artifact), indent=2), encoding="utf-8")
    return artifact


def load_preview_artifact(path: Path) -> PreviewArtifact:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return PreviewArtifact(
            bundles=tuple(preview_bundle_from_payload(item) for item in raw if isinstance(item, dict))
        )
    if isinstance(raw, dict):
        return preview_artifact_from_payload(raw)
    raise ValueError("preview artifact must be a JSON object or list")


def load_preview_bundles(path: Path) -> tuple[PreviewBundle, ...]:
    return load_preview_artifact(path).bundles


def verify_preview_artifact(
    artifact: PreviewArtifact,
    *,
    key_env: str,
    require_signature: bool,
) -> str | None:
    if artifact.signature is None:
        if require_signature:
            return "preview artifact is unsigned"
        return None

    signature = artifact.signature
    if signature.algorithm != PREVIEW_SIGNATURE_ALGORITHM:
        return f"unsupported preview artifact signature algorithm: {signature.algorithm!r}"
    if signature.key_env != key_env:
        return (
            f"preview artifact was signed for {signature.key_env!r}, "
            f"expected {key_env!r}"
        )

    key = os.getenv(key_env)
    if not key:
        return f"artifact signing key environment variable {key_env!r} is not set"

    expected = _sign_preview_artifact(artifact.bundles, key_env)
    if not hmac.compare_digest(signature.digest, expected.digest):
        return "preview artifact signature verification failed"
    return None


def _unsigned_artifact_payload(bundles: tuple[PreviewBundle, ...] | list[PreviewBundle]) -> dict[str, object]:
    return {
        "artifact_type": PREVIEW_ARTIFACT_TYPE,
        "bundles": [preview_bundle_to_payload(bundle) for bundle in bundles],
    }


def _sign_preview_artifact(
    bundles: tuple[PreviewBundle, ...] | list[PreviewBundle],
    key_env: str,
) -> PreviewArtifactSignature | None:
    key = os.getenv(key_env)
    if not key:
        return None
    payload = _unsigned_artifact_payload(bundles)
    digest = hmac.new(
        key.encode("utf-8"),
        _canonical_artifact_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    return PreviewArtifactSignature(
        algorithm=PREVIEW_SIGNATURE_ALGORITHM,
        key_env=key_env,
        digest=digest,
    )


def _canonical_artifact_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
