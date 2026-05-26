import type { LeakageType } from '../../types/api';

export const EMPTY_VALUE = '—';

const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type EvidenceMap = Record<string, unknown>;

export function asEvidenceMap(value: unknown): EvidenceMap {
  return isEvidenceMap(value) ? value : {};
}

export function getSection(evidence: EvidenceMap | null | undefined, key: string): EvidenceMap {
  if (!evidence) {
    return {};
  }

  return asEvidenceMap(evidence[key]);
}

export function getStringValue(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  return null;
}

export function getNumberValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

export function formatTextValue(value: unknown): string {
  return getStringValue(value) ?? EMPTY_VALUE;
}

export function formatDateValue(value: unknown): string {
  const dateString = getStringValue(value);
  if (!dateString) {
    return EMPTY_VALUE;
  }

  if (DATE_ONLY_PATTERN.test(dateString)) {
    const [year, month, day] = dateString.split('-').map(Number);
    return dateFormatter.format(new Date(year, month - 1, day));
  }

  const parsed = new Date(dateString);
  if (Number.isNaN(parsed.getTime())) {
    return dateString;
  }

  return dateFormatter.format(parsed);
}

export function formatNumberValue(value: unknown): string {
  const numberValue = getNumberValue(value);
  if (numberValue === null) {
    return EMPTY_VALUE;
  }

  return numberFormatter.format(numberValue);
}

export function formatQuantity(value: unknown, unit?: unknown): string {
  const formattedValue = formatNumberValue(value);
  const unitText = getStringValue(unit);

  if (formattedValue === EMPTY_VALUE) {
    return EMPTY_VALUE;
  }

  return unitText ? `${formattedValue} ${unitText}` : formattedValue;
}

export function formatCurrencyValue(value: unknown, currency = 'INR'): string {
  const numberValue = getNumberValue(value);
  if (numberValue === null) {
    return EMPTY_VALUE;
  }

  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(numberValue);
  } catch {
    return `${currency} ${numberValue.toFixed(2)}`;
  }
}

export function formatPricePerUnit(value: unknown, unit?: unknown, currency = 'INR'): string {
  const formattedAmount = formatCurrencyValue(value, currency);
  const unitText = getStringValue(unit);

  if (formattedAmount === EMPTY_VALUE) {
    return EMPTY_VALUE;
  }

  return unitText ? `${formattedAmount} per ${unitText}` : formattedAmount;
}

export function getRuleLabel(ruleApplied: string | null | undefined, leakageType: LeakageType): string {
  const rule = ruleApplied ?? '';

  if (rule === 'RULE_1_PRICE_MISMATCH') {
    return 'Price Mismatch (Rule 1)';
  }

  if (rule === 'RULE_2_DUPLICATE_INVOICE') {
    return 'Duplicate Invoice (Rule 2)';
  }

  if (rule === 'RULE_3_QUANTITY_MISMATCH') {
    return 'Quantity Mismatch (Rule 3)';
  }

  if (leakageType === 'PRICE_MISMATCH') {
    return 'Price Mismatch (Rule 1)';
  }

  if (leakageType === 'DUPLICATE_INVOICE') {
    return 'Duplicate Invoice (Rule 2)';
  }

  return 'Quantity Mismatch (Rule 3)';
}

export function getConfidenceDisplay(confidence: number | null | undefined): { score: string; note: string } {
  if (typeof confidence !== 'number' || Number.isNaN(confidence)) {
    return {
      score: EMPTY_VALUE,
      note: EMPTY_VALUE,
    };
  }

  const percentage = Math.round(confidence * 100);
  let note = 'Low confidence - verify before accepting';

  if (percentage >= 100) {
    note = 'Exact match - high certainty';
  } else if (percentage >= 85) {
    note = 'Strong match - recommended for review before accepting';
  } else if (percentage >= 70) {
    note = 'Probable match - manual verification advised';
  }

  return {
    score: `${percentage}%`,
    note,
  };
}

export function getComparableInvoiceUnitPrice(
  calculation: EvidenceMap,
  contractReference: EvidenceMap,
  invoiceReference: EvidenceMap,
): number | null {
  const contractUnitPrice = getNumberValue(contractReference.unit_price);
  const priceDifference = getNumberValue(calculation.price_difference_per_unit);

  if (contractUnitPrice !== null && priceDifference !== null) {
    return contractUnitPrice + priceDifference;
  }

  return getNumberValue(invoiceReference.unit_price);
}

export function getDuplicateWindowLabel(explanation?: string | null): string {
  const match = explanation?.match(/within the (\d+)-day duplicate detection window/i);
  return match?.[1] ? `${match[1]}-day duplicate detection window` : 'duplicate detection window';
}

export function getDuplicateOriginalDate(explanation?: string | null): string | null {
  const match = explanation?.match(/duplicate of Invoice .*? dated (\d{4}-\d{2}-\d{2})/i);
  return match?.[1] ?? null;
}

export function getDuplicateOriginalAmount(explanation?: string | null): number | null {
  const match = explanation?.match(/duplicate of Invoice .*? for ₹([0-9.,]+)/i);
  return match?.[1] ? Number(match[1].replace(/,/g, '')) : null;
}

export function getAuthorityReference(authorityUsed: string | null, quantityReference: EvidenceMap, explanation?: string | null): string {
  if (authorityUsed === 'PO') {
    const poRef = explanation?.match(/the PO \(([^)]+)\)/i)?.[1];
    return poRef ?? getStringValue(quantityReference.po_id) ?? EMPTY_VALUE;
  }

  if (authorityUsed === 'GRN') {
    const grnDate = explanation?.match(/the GRN \(received on ([^)]+)\)/i)?.[1];
    return grnDate ? `received ${grnDate}` : getStringValue(quantityReference.grn_id) ?? EMPTY_VALUE;
  }

  if (authorityUsed === 'CONTRACT') {
    const contractRef = explanation?.match(/referenced contract \(([^)]+)\)/i)?.[1];
    return contractRef ?? getStringValue(quantityReference.contract_id) ?? EMPTY_VALUE;
  }

  return EMPTY_VALUE;
}

function isEvidenceMap(value: unknown): value is EvidenceMap {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const dateFormatter = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

const numberFormatter = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 6,
});
