import React, { useState } from 'react';
import type { LeakageType } from '../../types/api';
import {
  EMPTY_VALUE,
  asEvidenceMap,
  formatCurrencyValue,
  formatDateValue,
  formatPricePerUnit,
  formatQuantity,
  formatTextValue,
  getComparableInvoiceUnitPrice,
  getDuplicateOriginalAmount,
  getDuplicateOriginalDate,
  getDuplicateWindowLabel,
  getSection,
} from './leakageDetailUtils';

interface ExplanationPanelProps {
  leakageType: LeakageType;
  evidence: Record<string, unknown> | null | undefined;
  explanation: string | null | undefined;
  currency?: string;
}

interface DetailRow {
  label: string;
  value: string;
}

export function ExplanationPanel({
  leakageType,
  evidence,
  explanation,
  currency = 'INR',
}: ExplanationPanelProps) {
  const [showFullExplanation, setShowFullExplanation] = useState(false);
  const parsedEvidence = asEvidenceMap(evidence);
  const rows = buildRows(leakageType, parsedEvidence, explanation, currency);

  return (
    <div>
      <DetailGrid rows={rows} />
      <div style={{ marginTop: 'var(--space-5)' }}>
        <button
          type="button"
          onClick={() => setShowFullExplanation((current) => !current)}
          style={toggleButtonStyle}
        >
          {showFullExplanation ? 'Hide full explanation' : 'Full explanation'}
        </button>
        {showFullExplanation && (
          <div
            style={{
              marginTop: 'var(--space-3)',
              padding: 'var(--space-4)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
              background: 'var(--bg-surface-2)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-sm)',
              lineHeight: 1.7,
            }}
          >
            {explanation?.trim() || EMPTY_VALUE}
          </div>
        )}
      </div>
    </div>
  );
}

function buildRows(
  leakageType: LeakageType,
  evidence: Record<string, unknown>,
  explanation: string | null | undefined,
  currency: string,
): DetailRow[] {
  const invoiceReference = getSection(evidence, 'invoice_reference');
  const contractReference = getSection(evidence, 'contract_reference');
  const calculation = getSection(evidence, 'calculation');
  const duplicateReference = getSection(evidence, 'duplicate_reference');
  const quantityReference = getSection(evidence, 'quantity_reference');

  if (leakageType === 'PRICE_MISMATCH') {
    const itemDescription = formatTextValue(invoiceReference.item_desc ?? contractReference.item_desc);
    const comparableUnitPrice = getComparableInvoiceUnitPrice(calculation, contractReference, invoiceReference);
    const displayUnit = contractReference.unit ?? invoiceReference.unit;

    return [
      { label: 'What was found', value: `Overcharge on ${itemDescription}` },
      { label: 'Contract price', value: formatPricePerUnit(contractReference.unit_price, displayUnit, getCurrency(contractReference.currency, currency)) },
      { label: 'Invoiced price', value: formatPricePerUnit(comparableUnitPrice, displayUnit, getCurrency(contractReference.currency ?? invoiceReference.currency, currency)) },
      { label: 'Overcharge per unit', value: formatCurrencyValue(calculation.price_difference_per_unit, getCurrency(contractReference.currency, currency)) },
      { label: 'Quantity', value: formatQuantity(calculation.quantity ?? invoiceReference.quantity, displayUnit) },
      { label: 'Total overcharge', value: formatCurrencyValue(calculation.total_leakage, getCurrency(calculation.currency ?? contractReference.currency, currency)) },
      { label: 'Contract reference', value: formatTextValue(contractReference.contract_id) },
    ];
  }

  if (leakageType === 'DUPLICATE_INVOICE') {
    const originalAmount = getDuplicateOriginalAmount(explanation);
    const originalDate = getDuplicateOriginalDate(explanation);
    const duplicateType = formatTextValue(duplicateReference.duplicate_type);
    const matchBasis = duplicateType === 'EXACT'
      ? 'Same invoice number and same vendor'
      : `Same vendor, same amount, within the ${getDuplicateWindowLabel(explanation)}`;

    return [
      { label: 'What was found', value: 'Possible duplicate invoice' },
      {
        label: 'This invoice',
        value: buildInvoiceSummary(
          invoiceReference.invoice_no,
          invoiceReference.invoice_date,
          invoiceReference.total_amount,
          getCurrency(invoiceReference.currency, currency),
        ),
      },
      {
        label: 'Matches invoice',
        value: buildInvoiceSummary(
          duplicateReference.original_invoice_no,
          originalDate,
          originalAmount,
          getCurrency(invoiceReference.currency, currency),
        ),
      },
      { label: 'Gap', value: buildDaysApart(duplicateReference.temporal_distance_days) },
      { label: 'Match basis', value: matchBasis },
    ];
  }

  const authorityUsed = formatTextValue(quantityReference.authority_used);
  const authorityReference = getAuthorityReferenceLabel(quantityReference.authority_used, explanation, quantityReference);
  const authorisedQuantity = getAuthorisedQuantity(quantityReference, invoiceReference.unit);

  return [
    { label: 'What was found', value: 'Invoice quantity exceeds authorised quantity' },
    { label: 'Invoiced quantity', value: formatQuantity(invoiceReference.quantity ?? quantityReference.invoiced_quantity, invoiceReference.unit) },
    {
      label: 'Authorised quantity',
      value: authorityReference === EMPTY_VALUE
        ? authorisedQuantity
        : `${authorisedQuantity} (from ${authorityUsed} ${authorityReference})`,
    },
    { label: 'Excess quantity', value: formatQuantity(quantityReference.quantity_difference, invoiceReference.unit) },
    { label: 'Excess value', value: formatCurrencyValue(calculation.leakage_amount, currency) },
  ];
}

function DetailGrid({ rows }: { rows: DetailRow[] }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(160px, 220px) minmax(0, 1fr)',
        gap: 'var(--space-3) var(--space-4)',
        alignItems: 'start',
      }}
    >
      {rows.map((row) => (
        <React.Fragment key={row.label}>
          <div style={labelStyle}>{row.label}</div>
          <div style={valueStyle}>{row.value || EMPTY_VALUE}</div>
        </React.Fragment>
      ))}
    </div>
  );
}

function buildInvoiceSummary(
  invoiceNo: unknown,
  date: unknown,
  amount: unknown,
  currency: string,
): string {
  return `${formatTextValue(invoiceNo)} dated ${formatDateValue(date)} for ${formatCurrencyValue(amount, currency)}`;
}

function buildDaysApart(value: unknown): string {
  const days = formatTextValue(value);
  return days === EMPTY_VALUE ? EMPTY_VALUE : `${days} days apart`;
}

function getCurrency(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function getAuthorisedQuantity(quantityReference: Record<string, unknown>, unit: unknown): string {
  if (quantityReference.authority_used === 'GRN') {
    return formatQuantity(quantityReference.grn_quantity, unit);
  }

  if (quantityReference.authority_used === 'PO') {
    return formatQuantity(quantityReference.po_quantity, unit);
  }

  return formatQuantity(quantityReference.contract_quantity, unit);
}

function getAuthorityReferenceLabel(
  authorityUsed: unknown,
  explanation: string | null | undefined,
  quantityReference: Record<string, unknown>,
): string {
  const authorityValue = typeof authorityUsed === 'string' ? authorityUsed : null;
  if (!authorityValue) {
    return EMPTY_VALUE;
  }

  if (authorityValue === 'GRN') {
    const grnDate = explanation?.match(/the GRN \(received on ([^)]+)\)/i)?.[1];
    return grnDate ?? formatTextValue(quantityReference.grn_id);
  }

  if (authorityValue === 'PO') {
    const poRef = explanation?.match(/the PO \(([^)]+)\)/i)?.[1];
    return poRef ?? formatTextValue(quantityReference.po_id);
  }

  const contractRef = explanation?.match(/referenced contract \(([^)]+)\)/i)?.[1];
  return contractRef ?? formatTextValue(quantityReference.contract_id);
}

const labelStyle: React.CSSProperties = {
  fontFamily: 'var(--font-body)',
  fontSize: 'var(--text-xs)',
  fontWeight: 600,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
};

const valueStyle: React.CSSProperties = {
  fontFamily: 'var(--font-body)',
  fontSize: 'var(--text-sm)',
  color: 'var(--text-primary)',
  lineHeight: 1.6,
};

const toggleButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  color: 'var(--accent)',
  cursor: 'pointer',
  fontFamily: 'var(--font-body)',
  fontSize: 'var(--text-sm)',
  fontWeight: 600,
};
