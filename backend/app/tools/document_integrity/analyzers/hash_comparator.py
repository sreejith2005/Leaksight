"""Hash comparison for Tool B."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from backend.app.models.derived import DocumentHash
from backend.app.models.raw import Document


class HashComparator:
    """Compare current document hash state against the baseline."""

    @staticmethod
    def _inconclusive(version_count: int = 0) -> dict[str, object]:
        return {
            "status": "INCONCLUSIVE",
            "previous_version_id": None,
            "version_count": version_count,
            "hash_changed": False,
        }
    def compare(
        self,
        document_id: str,
        tenant_id: str,
        db_session,
    ) -> dict[str, object]:
        """Compare the latest hash row against the baseline hash row."""
        document_uuid = UUID(str(document_id))
        tenant_uuid = UUID(str(tenant_id))

        document = db_session.execute(
            select(Document).where(
                Document.id == document_uuid,
                Document.tenant_id == tenant_uuid,
            )
        ).scalar_one_or_none()
        if document is None:
            return self._inconclusive()

        try:
            rows = list(
                db_session.execute(
                    select(DocumentHash)
                    .where(
                        DocumentHash.document_id == document_uuid,
                        DocumentHash.tenant_id == tenant_uuid,
                    )
                    .order_by(DocumentHash.upload_sequence.asc())
                ).scalars()
            )
        except Exception:
            return self._inconclusive()

        if not rows:
            return self._inconclusive()

        baseline = rows[0]
        latest = rows[-1]
        version_count = len(rows)

        if version_count > 1:
            hash_changed = str(latest.hash_sha256) != str(baseline.hash_sha256)
            return {
                "status": "MODIFIED" if hash_changed else "UNCHANGED",
                "previous_version_id": str(baseline.id),
                "version_count": version_count,
                "hash_changed": hash_changed,
            }

        matching_documents = list(
            db_session.execute(
                select(Document)
                .where(
                    Document.tenant_id == tenant_uuid,
                    Document.original_filename == document.original_filename,
                    Document.doc_type == document.doc_type,
                    Document.id != document_uuid,
                )
                .order_by(Document.created_at.desc())
            ).scalars()
        )
        if not matching_documents:
            return {
                "status": "NEW",
                "previous_version_id": None,
                "version_count": 1,
                "hash_changed": False,
            }

        previous_document = matching_documents[0]
        previous_hash = db_session.execute(
            select(DocumentHash)
            .where(
                DocumentHash.document_id == previous_document.id,
                DocumentHash.tenant_id == tenant_uuid,
            )
            .order_by(DocumentHash.upload_sequence.desc(), DocumentHash.created_at.desc())
        ).scalars().first()
        if previous_hash is None:
            return self._inconclusive(version_count=len(matching_documents) + 1)

        hash_changed = str(latest.hash_sha256) != str(previous_hash.hash_sha256)
        return {
            "status": "MODIFIED" if hash_changed else "UNCHANGED",
            "previous_version_id": str(previous_hash.id),
            "version_count": len(matching_documents) + 1,
            "hash_changed": hash_changed,
        }
