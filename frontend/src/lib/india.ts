/**
 * India-specific formatting and location helpers.
 *
 * HerWay serves Indian users, so dates, currency and phone numbers follow
 * Indian conventions, and the app never assumes a default city.
 */

export const INDIAN_STATES = [
  'Andhra Pradesh',
  'Arunachal Pradesh',
  'Assam',
  'Bihar',
  'Chhattisgarh',
  'Goa',
  'Gujarat',
  'Haryana',
  'Himachal Pradesh',
  'Jharkhand',
  'Karnataka',
  'Kerala',
  'Madhya Pradesh',
  'Maharashtra',
  'Manipur',
  'Meghalaya',
  'Mizoram',
  'Nagaland',
  'Odisha',
  'Punjab',
  'Rajasthan',
  'Sikkim',
  'Tamil Nadu',
  'Telangana',
  'Tripura',
  'Uttar Pradesh',
  'Uttarakhand',
  'West Bengal',
] as const;

export const INDIAN_UNION_TERRITORIES = [
  'Andaman and Nicobar Islands',
  'Chandigarh',
  'Dadra and Nagar Haveli and Daman and Diu',
  'Delhi',
  'Jammu and Kashmir',
  'Ladakh',
  'Lakshadweep',
  'Puducherry',
] as const;

export const ALL_INDIAN_REGIONS: string[] = [
  ...INDIAN_STATES,
  ...INDIAN_UNION_TERRITORIES,
].sort((a, b) => a.localeCompare(b));

/** Short codes that should be dialled as-is, never reformatted. */
const SHORT_CODES = new Set(['100', '101', '102', '108', '112', '181', '1091', '1098', '1930', '14416', '14567', '1915']);

/**
 * Format an Indian phone number for display.
 *
 * Leaves national short codes (112, 181, …) untouched — grouping them would
 * make them look wrong — and renders mobiles as `+91 98765 43210`.
 * Anything it does not recognise is returned unchanged rather than mangled.
 */
export function formatIndianPhone(raw?: string | null): string {
  if (!raw) return '';
  const trimmed = raw.trim();
  const digits = trimmed.replace(/\D/g, '');

  if (SHORT_CODES.has(digits)) return digits;
  if (digits.length <= 5) return trimmed;

  // 10-digit mobile or landline-with-STD
  if (digits.length === 10) {
    return `+91 ${digits.slice(0, 5)} ${digits.slice(5)}`;
  }
  // With country code
  if (digits.length === 12 && digits.startsWith('91')) {
    const local = digits.slice(2);
    return `+91 ${local.slice(0, 5)} ${local.slice(5)}`;
  }
  if (digits.length === 13 && digits.startsWith('091')) {
    const local = digits.slice(3);
    return `+91 ${local.slice(0, 5)} ${local.slice(5)}`;
  }

  return trimmed;
}

/** A `tel:` value that preserves short codes and strips display formatting. */
export function telHref(raw?: string | null): string {
  if (!raw) return '';
  // Some listings carry several numbers; dial the first.
  const first = raw.split(/[,/]|\sor\s/i)[0] ?? raw;
  const cleaned = first.replace(/[^0-9+]/g, '');
  return cleaned ? `tel:${cleaned}` : '';
}

/** `1 October 2026` — the convention Indian users expect. */
export function formatIndianDate(value?: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date);
}

/** `1 Oct 2026, 4:05 pm` */
export function formatIndianDateTime(value?: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date);
}

/** Relative age, falling back to an Indian-format date beyond a week. */
export function timeAgo(value?: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return formatIndianDate(value);
}

/** Amounts in rupees, using the Indian digit grouping (lakh / crore). */
export function formatINR(amount: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount);
}

/** A 6-digit Indian PIN code if the text contains one. */
export function extractPinCode(value?: string | null): string | null {
  if (!value) return null;
  const match = value.match(/\b[1-9]\d{5}\b/);
  return match ? match[0] : null;
}

/** Build the location string sent to the backend from the picker fields. */
export function composeLocation(parts: {
  city?: string;
  state?: string;
  pin?: string;
}): string {
  return [parts.city?.trim(), parts.state?.trim(), parts.pin?.trim()]
    .filter(Boolean)
    .join(', ');
}
