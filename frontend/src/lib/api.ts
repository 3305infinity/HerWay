/**
 * Single entry point for talking to the HerWay backend.
 *
 * Everything goes through the Next.js proxy at `/api/v2/*`, which is
 * same-origin, so the backend's httpOnly session cookie is sent automatically
 * and the Clerk token is attached server-side.
 *
 * Every call has a timeout and returns a typed outcome rather than throwing,
 * so no screen can end up stuck on a spinner because a promise rejected
 * somewhere nobody was catching.
 */

export const DEFAULT_TIMEOUT_MS = 65_000;

export interface ApiError {
  /** Message safe to show the user. */
  message: string;
  status: number;
  /** True when retrying could plausibly work. */
  retryable: boolean;
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

function messageForStatus(status: number, detail?: string): string {
  if (detail && detail.trim()) return detail;
  switch (status) {
    case 0:
      return 'We could not reach HerWay. Check your connection and try again.';
    case 400:
      return 'Something in that request was not quite right. Please check and try again.';
    case 401:
      return 'Your session has expired. Please sign in again.';
    case 403:
      return 'This belongs to a different account or session.';
    case 404:
      return 'We could not find that.';
    case 408:
    case 504:
      return 'That took too long. Your information is safe — please try again.';
    case 429:
      return 'Too many requests just now. Please wait a moment and try again.';
    case 503:
      return 'That part of HerWay is temporarily unavailable. Please try again shortly.';
    default:
      return status >= 500
        ? 'Something went wrong on our side. Your information is safe.'
        : 'That did not work. Please try again.';
  }
}

function isRetryable(status: number): boolean {
  return status === 0 || status === 408 || status === 429 || status >= 500;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<ApiResult<T>> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(path, {
      ...rest,
      signal: controller.signal,
      // Same-origin, but be explicit: the session cookie must travel.
      credentials: 'same-origin',
      headers: {
        ...(rest.body && !(rest.body instanceof FormData)
          ? { 'Content-Type': 'application/json' }
          : {}),
        ...(rest.headers || {}),
      },
    });

    if (!response.ok) {
      let detail: string | undefined;
      try {
        const body = await response.json();
        detail = typeof body?.detail === 'string' ? body.detail : undefined;
      } catch {
        // Non-JSON error body; fall back to the status message.
      }
      return {
        ok: false,
        error: {
          message: messageForStatus(response.status, detail),
          status: response.status,
          retryable: isRetryable(response.status),
        },
      };
    }

    if (response.status === 204) {
      return { ok: true, data: undefined as T };
    }

    const data = (await response.json()) as T;
    return { ok: true, data };
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === 'AbortError';
    return {
      ok: false,
      error: {
        message: aborted
          ? 'That took too long. Your information is safe — please try again.'
          : 'We could not reach HerWay. Check your connection and try again.',
        status: aborted ? 408 : 0,
        retryable: true,
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

export function apiGet<T>(path: string, timeoutMs?: number) {
  return apiFetch<T>(path, { method: 'GET', timeoutMs });
}

export function apiPost<T>(path: string, body?: unknown, timeoutMs?: number) {
  return apiFetch<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
    timeoutMs,
  });
}

export function apiPatch<T>(path: string, body?: unknown, timeoutMs?: number) {
  return apiFetch<T>(path, {
    method: 'PATCH',
    body: body === undefined ? undefined : JSON.stringify(body),
    timeoutMs,
  });
}

export function apiUpload<T>(path: string, form: FormData, timeoutMs?: number) {
  return apiFetch<T>(path, { method: 'POST', body: form, timeoutMs });
}

/**
 * Added for the Safety Center, where a user deleting a plan, a contact or their
 * whole record is a first-class action rather than an edge case.
 */
export function apiDelete<T>(path: string, timeoutMs?: number) {
  return apiFetch<T>(path, { method: 'DELETE', timeoutMs });
}
