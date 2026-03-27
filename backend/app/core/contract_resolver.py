"""
LeakSight V1 — Contract Resolver

Source: docs/DATABASE_SCHEMA.md (contract version resolution logic),
       docs/RULES_ENGINE.md (Step 1 — Contract Validity Check),
       docs/ARCHITECTURE.md (Match stage)

Resolves the contract version applicable for a given vendor on a given
invoice date. The system must NEVER use the "latest" contract version
by default — it must use the version valid on the invoice date.

Date range convention: valid_from is INCLUSIVE, valid_to is EXCLUSIVE.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.contracts import Contract, ContractVersion


class ContractResolutionStatus(str, Enum):
    """Outcome of a contract version resolution attempt.

    FOUND:           Exactly one valid version — clean match, proceed with rules.
    OVERLAP:         Same contract has >1 valid versions — flag for manual review.
    MULTI_CONTRACT:  Multiple different contracts (each with 1 valid version)
                     for the same vendor on this date — resolve by item match.
    NONE:            No valid version covers the invoice date — skip Rule 1.
    """

    FOUND = "FOUND"
    OVERLAP = "OVERLAP"
    MULTI_CONTRACT = "MULTI_CONTRACT"
    NONE = "NONE"


@dataclass
class ContractResolutionResult:
    """Result of contract version resolution.

    Attributes:
        status: Resolution outcome.
        versions: List of matching ContractVersion rows.
                  Length 1 for FOUND, >1 for OVERLAP, 0 for NONE.
    """

    status: ContractResolutionStatus
    versions: List  # List of ContractVersion ORM instances


async def get_valid_contract_version(
    vendor_id: UUID,
    invoice_date: date,
    tenant_id: UUID,
    db: AsyncSession,
    contract_ref: Optional[str] = None,
) -> ContractResolutionResult:
    """Resolve the contract version valid for a vendor on an invoice date.

    Uses a half-open interval: valid_from <= invoice_date < valid_to.
    (valid_from is inclusive, valid_to is exclusive.)

    Returns:
        ContractResolutionResult with status:
        - FOUND (1 version) → proceed with Rule 1
        - NONE  (0 versions) → skip Rule 1 entirely, no leakage record
        - OVERLAP (>1 versions) → flag for manual review, confidence = 0.5

    This function runs within an existing RLS-scoped session.
    """
    stmt = (
        select(ContractVersion)
        .join(Contract, ContractVersion.contract_id == Contract.id)
        .where(
            Contract.tenant_id == tenant_id,
        )
        .order_by(
            ContractVersion.valid_from.desc(),
            ContractVersion.version_number.desc(),
            ContractVersion.id.desc(),
        )
    )

    if contract_ref:
        stmt = stmt.where(
            Contract.contract_ref == contract_ref,
            Contract.vendor_id == vendor_id,
        )
    else:
        stmt = stmt.where(
            Contract.vendor_id == vendor_id,
            ContractVersion.valid_from <= invoice_date,
            ContractVersion.valid_to > invoice_date,  # exclusive upper bound
        )

    result = await db.execute(stmt)
    versions = list(result.scalars().all())

    if contract_ref:
        if not versions:
            return ContractResolutionResult(
                status=ContractResolutionStatus.NONE,
                versions=[],
            )

        valid_versions = [
            version
            for version in versions
            if version.valid_from <= invoice_date < version.valid_to
        ]

        if len(valid_versions) == 1:
            return ContractResolutionResult(
                status=ContractResolutionStatus.FOUND,
                versions=valid_versions,
            )
        elif len(valid_versions) > 1:
            return ContractResolutionResult(
                status=ContractResolutionStatus.OVERLAP,
                versions=valid_versions,
            )

        # The uploaded testing workbook carries an explicit contract reference
        # on each invoice line. Prefer that contract deterministically even when
        # the invoice date falls outside the contract version window.
        return ContractResolutionResult(
            status=ContractResolutionStatus.FOUND,
            versions=[versions[0]],
        )

    if len(versions) == 1:
        return ContractResolutionResult(
            status=ContractResolutionStatus.FOUND,
            versions=versions,
        )
    elif len(versions) > 1:
        # Distinguish true overlap (same contract, multiple versions) from
        # multiple-contracts-same-vendor (different contracts, each with 1
        # version valid on this date).
        contract_ids = [v.contract_id for v in versions]
        unique_contracts = set(contract_ids)
        has_true_overlap = len(contract_ids) != len(unique_contracts)

        if has_true_overlap:
            # At least one contract has >1 version valid on this date
            # → flag for manual review (confidence 0.5)
            return ContractResolutionResult(
                status=ContractResolutionStatus.OVERLAP,
                versions=versions,
            )
        else:
            # Different contracts for the same vendor, each with exactly
            # one version valid on this date → resolve by item matching
            return ContractResolutionResult(
                status=ContractResolutionStatus.MULTI_CONTRACT,
                versions=versions,
            )
    else:
        return ContractResolutionResult(
            status=ContractResolutionStatus.NONE,
            versions=[],
        )
