import { NextResponse } from 'next/server';

const BACKEND_URL = (
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'http://localhost:8000'
).replace(/\/$/, '');

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  try {
    const response = await fetch(`${BACKEND_URL}/get-post/${encodeURIComponent(id)}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(20_000),
    });

    if (!response.ok) {
      let detail = 'That post could not be loaded.';
      try {
        const body = await response.json();
        if (typeof body?.detail === 'string') detail = body.detail;
      } catch {
        // Non-JSON error body.
      }
      return NextResponse.json({ error: detail }, { status: response.status });
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    console.error('Failed to fetch community post:', error);
    return NextResponse.json(
      { error: 'We could not reach HerWay. Please check your connection and try again.' },
      { status: 502 },
    );
  }
}
