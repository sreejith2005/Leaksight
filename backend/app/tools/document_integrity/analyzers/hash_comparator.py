"""Hash comparison for Tool B."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from backend.app.models.derived import DocumentHash


class HashComparator:
    """Compare current document hash state against the baseline."""

    def compare(
        self,
        document_id: str,
        tenant_id: str,
        db_session,
    ) -> dict[str, object]:
        """Compare the latest hash row against the baseline hash row."""
        document_uuid = UUID(str(document_id))
        tenant_uuid = UUID(str(tenant_id))
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
            return {
                "status": "INCONCLUSIVE",
                "previous_version_id": None,
                "version_count": 0,
                "hash_changed": False,
            }

        if not rows:
            return {
                "status": "INCONCLUSIVE",
                "previous_version_id": None,
                "version_count": 0,
                "hash_changed": False,
            }

        baseline = rows[0]
        latest = rows[-1]
        version_count = len(rows)

        if version_count == 1:
            return {
                "status": "NEW",
                "previous_version_id": str(baseline.id),
                "version_count": version_count,
                "hash_changed": False,
            }

        hash_changed = str(latest.hash_sha256) != str(baseline.hash_sha256)
        return {
            "status": "MODIFIED" if hash_changed else "UNCHANGED",
            "previous_version_id": str(baseline.id),
            "version_count": version_count,
            "hash_changed": hash_changed,
        }
