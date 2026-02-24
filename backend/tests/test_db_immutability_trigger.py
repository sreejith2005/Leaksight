"""
LeakSight V1 — DB Immutability Trigger Integration Tests (Step 5.5)

These tests verify the PostgreSQL trigger `trg_leakage_immutability` that
prevents modification of financial fields on ACCEPTED leakage records.

Trigger: trg_leakage_immutability
Function: prevent_accepted_leakage_modification()

BLOCKED after ACCEPTED:
  - amount
  - leakage_type
  - confidence
  - evidence_jsonb
  - rule_applied

ALLOWED after ACCEPTED:
  - review_notes (reviewer can add additional notes)
  - status (application enforces, trigger does not block status changes)

These are integration tests requiring a real PostgreSQL database with the
trigger installed. Mark with @pytest.mark.integration and skip in CI
unless DB is available.

Ref: docs/DATABASE_SCHEMA.md §Immutability Trigger
     backend/migrations/versions/a1b2c3d4e5f6_phase2_data_model.py
"""

import uuid
from decimal import Decimal

import pytest

# ── These tests require a real PG connection — mark as integration ────

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "not config.getoption('--run-integration', default=False)",
        reason="Requires --run-integration flag and live PostgreSQL",
    ),
]


@pytest.fixture
async def accepted_leakage_record(db_session):
    """Create and ACCEPT a leakage record in the real database."""
    from backend.app.models.derived import LeakageRecord

    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()

    record = LeakageRecord(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=run_id,
        invoice_id=uuid.uuid4(),
        leakage_type="PRICE_MISMATCH",
        amount=Decimal("5000.00"),
        currency="INR",
        confidence=0.95,
        evidence_jsonb={"contract_price": 450, "invoice_price": 500},
        rule_applied="RULE_1_PRICE_MISMATCH",
        explanation="Invoice overcharges ₹5000 total.",
        status="ACCEPTED",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


class TestImmutabilityTriggerExists:
    """Verify trigger is installed in the database."""

    async def test_trigger_registered(self, db_session):
        """trg_leakage_immutability must be present on leakage_records."""
        from sqlalchemy import text

        result = await db_session.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'leakage_records'::regclass "
                "AND tgname = 'trg_leakage_immutability'"
            )
        )
        triggers = [row[0] for row in result.fetchall()]
        assert "trg_leakage_immutability" in triggers

    async def test_trigger_function_exists(self, db_session):
        """prevent_accepted_leakage_modification() function must exist."""
        from sqlalchemy import text

        result = await db_session.execute(
            text(
                "SELECT proname FROM pg_proc "
                "WHERE proname = 'prevent_accepted_leakage_modification'"
            )
        )
        assert result.scalar_one_or_none() is not None


class TestImmutabilityTriggerBlocks:
    """Verify trigger blocks modification of protected fields on ACCEPTED records."""

    async def test_block_amount_update(self, db_session, accepted_leakage_record):
        """Updating amount on ACCEPTED record must raise DB exception."""
        from sqlalchemy import text

        with pytest.raises(Exception, match="Cannot modify accepted leakage record"):
            await db_session.execute(
                text(
                    "UPDATE leakage_records SET amount = :new_amount "
                    "WHERE id = :record_id"
                ),
                {
                    "new_amount": Decimal("9999.00"),
                    "record_id": accepted_leakage_record.id,
                },
            )
            await db_session.commit()

    async def test_block_evidence_jsonb_update(
        self, db_session, accepted_leakage_record
    ):
        """Updating evidence_jsonb on ACCEPTED record must raise DB exception."""
        from sqlalchemy import text

        with pytest.raises(Exception, match="Cannot modify accepted leakage record"):
            await db_session.execute(
                text(
                    "UPDATE leakage_records "
                    "SET evidence_jsonb = :new_evidence "
                    "WHERE id = :record_id"
                ),
                {
                    "new_evidence": '{"tampered": true}',
                    "record_id": accepted_leakage_record.id,
                },
            )
            await db_session.commit()

    async def test_block_confidence_update(
        self, db_session, accepted_leakage_record
    ):
        """Updating confidence on ACCEPTED record must raise DB exception."""
        from sqlalchemy import text

        with pytest.raises(Exception, match="Cannot modify accepted leakage record"):
            await db_session.execute(
                text(
                    "UPDATE leakage_records SET confidence = :new_conf "
                    "WHERE id = :record_id"
                ),
                {
                    "new_conf": 0.1,
                    "record_id": accepted_leakage_record.id,
                },
            )
            await db_session.commit()

    async def test_block_leakage_type_update(
        self, db_session, accepted_leakage_record
    ):
        """Updating leakage_type on ACCEPTED record must raise DB exception."""
        from sqlalchemy import text

        with pytest.raises(Exception, match="Cannot modify accepted leakage record"):
            await db_session.execute(
                text(
                    "UPDATE leakage_records SET leakage_type = :new_type "
                    "WHERE id = :record_id"
                ),
                {
                    "new_type": "DUPLICATE_INVOICE",
                    "record_id": accepted_leakage_record.id,
                },
            )
            await db_session.commit()

    async def test_block_rule_applied_update(
        self, db_session, accepted_leakage_record
    ):
        """Updating rule_applied on ACCEPTED record must raise DB exception."""
        from sqlalchemy import text

        with pytest.raises(Exception, match="Cannot modify accepted leakage record"):
            await db_session.execute(
                text(
                    "UPDATE leakage_records SET rule_applied = :new_rule "
                    "WHERE id = :record_id"
                ),
                {
                    "new_rule": "RULE_2_DUPLICATE_INVOICE",
                    "record_id": accepted_leakage_record.id,
                },
            )
            await db_session.commit()


class TestImmutabilityTriggerAllows:
    """Verify trigger allows modification of non-protected fields."""

    async def test_allow_review_notes_update(
        self, db_session, accepted_leakage_record
    ):
        """Updating review_notes on ACCEPTED record must succeed."""
        from sqlalchemy import text

        await db_session.execute(
            text(
                "UPDATE leakage_records SET review_notes = :notes "
                "WHERE id = :record_id"
            ),
            {
                "notes": "Additional reviewer comments",
                "record_id": accepted_leakage_record.id,
            },
        )
        await db_session.commit()
        # No exception = pass

    async def test_allow_status_change(
        self, db_session, accepted_leakage_record
    ):
        """Trigger does not block status field changes (app layer enforces)."""
        from sqlalchemy import text

        # Trigger only checks financial fields, not status.
        # Application layer (ImmutabilityError) handles status logic.
        await db_session.execute(
            text(
                "UPDATE leakage_records SET status = :new_status "
                "WHERE id = :record_id"
            ),
            {
                "new_status": "ACCEPTED",  # Same status = no-op
                "record_id": accepted_leakage_record.id,
            },
        )
        await db_session.commit()


class TestImmutabilityTriggerPendingRecords:
    """Verify trigger does NOT block changes on non-ACCEPTED records."""

    async def test_pending_amount_update_allowed(self, db_session):
        """Updating amount on PENDING record must succeed (trigger ignores)."""
        from sqlalchemy import text
        from backend.app.models.derived import LeakageRecord

        record = LeakageRecord(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            leakage_type="PRICE_MISMATCH",
            amount=Decimal("5000.00"),
            currency="INR",
            confidence=0.95,
            evidence_jsonb={"test": True},
            rule_applied="RULE_1_PRICE_MISMATCH",
            explanation="Overcharge of ₹5000.",
            status="PENDING",
        )
        db_session.add(record)
        await db_session.commit()

        await db_session.execute(
            text(
                "UPDATE leakage_records SET amount = :new_amount "
                "WHERE id = :record_id"
            ),
            {"new_amount": Decimal("9999.00"), "record_id": record.id},
        )
        await db_session.commit()
        # No exception = pass
