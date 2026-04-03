"""Service orchestration for Tool B."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.models.derived import DocumentHash
from backend.app.models.raw import Document
from backend.app.tools.document_integrity.analyzers.hash_comparator import HashComparator
from backend.app.tools.document_integrity.analyzers.metadata_extractor import MetadataExtractor
from backend.app.tools.document_integrity.analyzers.numeric_comparator import NumericComparator
from backend.app.tools.document_integrity.analyzers.risk_scorer import (
    RiskScorer,
    risk_level_from_score,
)


class DocumentIntegrityService:
    """Orchestrates Tool B analyzers and persists the latest hash report."""

    def __init__(self) -> None:
        self.metadata_extractor = MetadataExtractor()
        self.hash_comparator = HashComparator()
        self.numeric_comparator = NumericComparator()
        self.risk_scorer = RiskScorer()

    def run_analysis(
        self,
        document_id: str,
        tenant_id: str,
        db_session,
    ) -> dict[str, Any]:
        """Run integrity analysis and write the result to the latest hash row."""
        document_uuid = UUID(str(document_id))
        tenant_uuid = UUID(str(tenant_id))

        document = db_session.execute(
            select(Document).where(
                Document.id == document_uuid,
                Document.tenant_id == tenant_uuid,
            )
        ).scalar_one_or_none()
        if document is None:
            raise LookupError("DocumentNotFound")

        hash_rows = list(
            db_session.execute(
                select(DocumentHash)
                .where(
                    DocumentHash.document_id == document_uuid,
                    DocumentHash.tenant_id == tenant_uuid,
                )
                .order_by(DocumentHash.upload_sequence.asc())
            ).scalars()
        )
        if not hash_rows:
            raise LookupError("DocumentHashNotFound")

        baseline_hash = next(
            (row for row in hash_rows if str(row.hash_type) == "BASELINE"),
            hash_rows[0],
        )
        current_hash = hash_rows[-1]

        file_path = self._resolve_current_file_path(document.file_path)
        metadata = self.metadata_extractor.extract(file_path=file_path, doc_type=str(document.doc_type))
        hash_result = self.hash_comparator.compare(
            document_id=str(document_uuid),
            tenant_id=str(tenant_uuid),
            db_session=db_session,
        )

        current_numerics = self.numeric_comparator.extract_numerics(file_path)
        previous_numerics: list[dict[str, Any]] = []
        previous_file_path = self._resolve_previous_file_path(
            baseline_hash=baseline_hash,
            current_hash=current_hash,
        )
        if previous_file_path is not None and previous_file_path.exists():
            previous_numerics = self.numeric_comparator.extract_numerics(previous_file_path)

        numeric_changes = self.numeric_comparator.compare(
            current=current_numerics,
            previous=previous_numerics,
        )
        score, flags = self.risk_scorer.score(
            hash_result=hash_result,
            metadata=metadata,
            numeric_changes=numeric_changes,
        )

        current_hash.metadata_jsonb = metadata
        current_hash.comparison_status = hash_result["status"]
        current_hash.comparison_against_id = baseline_hash.id
        current_hash.risk_score = score
        current_hash.flagged_anomalies_jsonb = {
            "flags": flags,
            "numeric_changes": numeric_changes,
        }
        db_session.flush()

        analyzed_at = datetime.now(timezone.utc)
        return {
            "document_id": str(document.id),
            "filename": document.original_filename,
            "doc_type": str(document.doc_type),
            "risk_score": score,
            "risk_level": risk_level_from_score(score),
            "comparison_status": hash_result["status"],
            "version_count": hash_result["version_count"],
            "flags": flags,
            "numeric_changes": numeric_changes,
            "metadata": metadata,
            "analyzed_at": analyzed_at,
        }

    @staticmethod
    def _resolve_current_file_path(file_path_value: str) -> Path:
        path = Path(file_path_value)
        if path.is_absolute():
            return path
        return Path(get_settings().document_storage_path) / path

    def _resolve_previous_file_path(
        self,
        baseline_hash: DocumentHash,
        current_hash: DocumentHash,
    ) -> Path | None:
        if baseline_hash.id == current_hash.id:
            return None

        metadata_candidates = [
            getattr(current_hash, "metadata_jsonb", None),
            getattr(baseline_hash, "metadata_jsonb", None),
        ]
        for candidate in metadata_candidates:
            if not isinstance(candidate, dict):
                continue
            raw_path = candidate.get("previous_file_path") or candidate.get("file_path")
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if path.is_absolute():
                return path
            return Path(get_settings().document_storage_path) / path
        return None
