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
  getAuthorityReference,
  getComparableInvoiceUnitPrice,
  getConfidenceDisplay,
  getDuplicateOriginalAmount,
  getDuplicateOriginalDate,
  getRuleLabel,
  getSection,
} from './leakageDetailUtils';

interface EvidencePanelProps {
  leakageType: LeakageType;
  evidence: Record<string, unknown> | null | undefined;
  confidence?: number | null;
  ruleApplied?: string | null;
  vendorName?: string | null;
  explanation?: string | null;
  currency?: string;
}

interface DetailRow {
  label: string;
  value: string;
  hidden?: boolean;
}

export function EvidencePanel({
  leakageType,
  evidence,
  confidence,
  ruleApplied,
  vendorName,
  explanation,
  currency = 'INR',
}: EvidencePanelProps) {
  const [showRawEvidence, setShowRawEvidence] = useState(false);
  const parsedEvidence = asEvidenceMap(evidence);
  const rows = buildRows({
    leakageType,
    evidence: parsedEvidence,
    confidence,
    ruleApplied,
    vendorName,
    explanation,
    currency,
  });

  return (
    <div>
      <DetailGrid rows={rows} />
      <div style={{ marginTop: 'var(--space-5)' }}>
        <button
          type="button"
          onClick={() => setShowRawEvidence((current) => !current)}
          style={toggleButtonStyle}
        >
          {showRawEvidence ? 'Hide raw evidence' : 'Show raw evidence'}
        </button>
        {showRawEvidence && (
          <pre
            style={{
              marginTop: 'var(--space-3)',
              backgroundColor: 'var(--bg-base)',
              padding: 'var(--space-5)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              overflow: 'auto',
              maxHeight: 320,
              border: '1px solid var(--border-subtle)',
              lineHeight: 1.6,
            }}
          >
            {JSON.stringify(parsedEvidence, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

function buildRows({
  leakageType,
  evidence,
  confidence,
  ruleApplied,
  vendorName,
  explanation,
  currency,
}: {
  leakageType: LeakageType;
  evidence: Record<string, unknown>;
  confidence?: number | null;
  ruleApplied?: string | null;
  vendorName?: string | null;
  explanation?: string | null;
  currency: string;
}): DetailRow[] {
  const invoiceReference = getSection(evidence, 'invoice_reference');
  const contractReference = getSection(evidence, 'contract_reference');
  const calculation = getSection(evidence, 'calculation');
  const duplicateReference = getSection(evidence, 'duplicate_reference');
  const quantityReference = getSection(evidence, 'quantity_reference');
  const unitConversionDetails = getSection(evidence, 'unit_conversion_details');
  const confidenceDisplay = getConfidenceDisplay(confidence);

  const rows: DetailRow[] = [
    { label: 'Invoice reference', value: formatTextValue(invoiceReference.invoice_no) },
    { label: 'Invoice line item', value: formatTextValue(invoiceReference.item_desc) },
    { label: 'Vendor', value: formatTextValue(vendorName) },
    { label: 'Detection rule', value: getRuleLabel(ruleApplied, leakageType) },
    { label: 'Confidence', value: `${confidenceDisplay.score} - ${confidenceDisplay.note}` },
  ];

  if (leakageType === 'PRICE_MISMATCH') {
    const comparableUnitPrice = getComparableInvoiceUnitPrice(calculation, contractReference, invoiceReference);
    const displayUnit = contractReference.unit ?? invoiceReference.unit;
    const calculationQuantity = calculation.quantity ?? invoiceReference.quantity;

    rows.push(
      { label: 'Contract ref', value: formatTextValue(contractReference.contract_id) },
      { label: 'Matched item', value: formatTextValue(contractReference.item_desc) },
      {
        label: 'Contract unit price',
        value: formatPricePerUnit(contractReference.unit_price, displayUnit, getCurrency(contractReference.currency, currency)),
      },
      {
        label: 'Invoiced unit price',
        value: formatPricePerUnit(comparableUnitPrice, displayUnit, getCurrency(contractReference.currency ?? invoiceReference.currency, currency)),
      },
      {
        label: 'Unit conversion',
        value: unitConversionDetails.applied
          ? `${formatTextValue(unitConversionDetails.from_unit)} -> ${formatTextValue(unitConversionDetails.to_unit)} (factor ${formatTextValue(unitConversionDetails.factor)})`
          : EMPTY_VALUE,
        hidden: !unitConversionDetails.applied,
      },
      {
        label: 'Calculation',
        value: buildPriceCalculation({
          invoicedUnitPrice: comparableUnitPrice,
          contractUnitPrice: contractReference.unit_price,
          quantity: calculationQuantity,
          total: calculation.total_leakage,
          currency: getCurrency(calculation.currency ?? contractReference.currency, currency),
        }),
      },
    );

    return rows;
  }

  if (leakageType === 'DUPLICATE_INVOICE') {
    rows.push(
      { label: 'Original invoice', value: formatTextValue(duplicateReference.original_invoice_no) },
      { label: 'Original date', value: formatDateValue(getDuplicateOriginalDate(explanation)) },
      {
        label: 'Duplicate type',
        value: duplicateReference.duplicate_type === 'EXACT' ? 'Exact duplicate' : duplicateReference.duplicate_type === 'NEAR_DUPLICATE' ? 'Near duplicate' : EMPTY_VALUE,
      },
      {
        label: 'Date gap',
        value: buildDaysApart(duplicateReference.temporal_distance_days),
      },
      {
        label: 'Original amount',
        value: formatCurrencyValue(getDuplicateOriginalAmount(explanation), getCurrency(invoiceReference.currency, currency)),
      },
    );

    return rows;
  }

  const authorityUsed = formatTextValue(quantityReference.authority_used);
  const authorityReference = getAuthorityReference(
    typeof quantityReference.authority_used === 'string' ? quantityReference.authority_used : null,
    quantityReference,
    explanation,
  );
  const authorityQuantity = quantityReference.authority_used === 'GRN'
    ? quantityReference.grn_quantity
    : quantityReference.authority_used === 'PO'
      ? quantityReference.po_quantity
      : quantityReference.contract_quantity;

  rows.push(
    {
      label: 'Authority source',
      value: authorityReference === EMPTY_VALUE ? authorityUsed : `${authorityUsed} ${authorityReference}`,
    },
    {
      label: 'Authorised qty',
      value: formatQuantity(authorityQuantity, invoiceReference.unit),
    },
    {
      label: 'Invoiced qty',
      value: formatQuantity(invoiceReference.quantity ?? quantityReference.invoiced_quantity, invoiceReference.unit),
    },
    {
      label: 'Excess',
      value: formatQuantity(quantityReference.quantity_difference, invoiceReference.unit),
    },
  );

  return rows;
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
      {rows.filter((row) => !row.hidden).map((row) => (
        <React.Fragment key={row.label}>
          <div style={labelStyle}>{row.label}</div>
          <div style={valueStyle}>{row.value || EMPTY_VALUE}</div>
        </React.Fragment>
      ))}
    </div>
  );
}

function buildPriceCalculation({
  invoicedUnitPrice,
  contractUnitPrice,
  quantity,
  total,
  currency,
}: {
  invoicedUnitPrice: number | null;
  contractUnitPrice: unknown;
  quantity: unknown;
  total: unknown;
  currency: string;
}): string {
  const invoiced = formatCurrencyValue(invoicedUnitPrice, currency);
  const contract = formatCurrencyValue(contractUnitPrice, currency);
  const quantityValue = formatTextValue(quantity);
  const totalValue = formatCurrencyValue(total, currency);

  if ([invoiced, contract, quantityValue, totalValue].includes(EMPTY_VALUE)) {
    return EMPTY_VALUE;
  }

  return `(${invoiced} - ${contract}) x ${quantityValue} = ${totalValue}`;
}

function buildDaysApart(value: unknown): string {
  const days = formatTextValue(value);
  return days === EMPTY_VALUE ? EMPTY_VALUE : `${days} days`;
}

function getCurrency(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
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
