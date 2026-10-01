import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthToken } from '@/lib/server-auth';

/**
 * Proxy for the moderation "close issue" action used by the responder dashboard.
 *
 * The backend's `/close-issue/{id}` requires an authenticated identity. This
 * route previously forwarded neither the session cookie nor the Clerk token, so
 * the backend always answered 401 and the `catch` below turned that into an
 * opaque 500 — the dashboard button could never succeed, and said only
 * "Failed to close issue" regardless of the real cause.
 *
 * Credentials are attached the same way as in the `/api/v2/[...path]` proxy,
 * and the upstream status is preserved so the caller can tell "not allowed"
 * apart from "backend down".
 */

const BACKEND_URL = (
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'http://localhost:8000'
).replace(/\/$/, '');

interface CloseIssueRequest {
  issueId: string;
}

export async function POST(request: NextRequest) {
  let issueId: string;
  try {
    ({ issueId } = (await request.json()) as CloseIssueRequest);
  } catch {
    return NextResponse.json({ detail: 'A valid issueId is required.' }, { status: 400 });
  }

  if (!issueId) {
    return NextResponse.json({ detail: 'A valid issueId is required.' }, { status: 400 });
  }

  const headers = new Headers({ 'content-type': 'application/json' });

  // Forward the anonymous session cookie the backend issued.
  const cookie = request.headers.get('cookie');
  if (cookie) headers.set('cookie', cookie);

  // Attach the Clerk token server-side; it never reaches client JavaScript.
  const token = await getServerAuthToken();
  if (token) headers.set('authorization', `Bearer ${token}`);

  try {
    const upstream = await fetch(
      `${BACKEND_URL}/close-issue/${encodeURIComponent(issueId)}`,
      { method: 'POST', headers, cache: 'no-store' },
    );

    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: { 'content-type': upstream.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    console.error('closeIssue proxy failed:', error);
    return NextResponse.json(
      { detail: 'We could not reach HerWay right now. Please try again.' },
      { status: 502 },
    );
  }
}
