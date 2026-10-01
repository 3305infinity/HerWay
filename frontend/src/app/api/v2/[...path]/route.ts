import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthToken } from '@/lib/server-auth';

/**
 * Proxy for the HerWay FastAPI backend.
 *
 * Everything the browser needs from the backend goes through here rather than
 * being fetched cross-origin. That buys three things:
 *
 * 1. **Relative URLs work.** Several pages already called `/api/v2/cases`
 *    directly (LawBot's "Promote to case", the community "Start case from
 *    this" button, the discreet-report save). There was no such route, so
 *    those buttons 404'd and failed silently.
 * 2. **The session cookie is first-party.** The backend issues an httpOnly
 *    anonymous session cookie; same-origin requests carry it without needing
 *    SameSite=None.
 * 3. **The Clerk token never reaches client JavaScript.** It is attached here,
 *    on the server.
 */

const BACKEND_URL = (
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'http://localhost:8000'
).replace(/\/$/, '');

/** Upper bound on a single backend call, so the UI never hangs forever. */
const TIMEOUT_MS = Number(process.env.BACKEND_TIMEOUT_MS || 60_000);

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
]);

async function proxy(req: NextRequest, path: string[]) {
  const targetPath = path.map(encodeURIComponent).join('/');
  const search = req.nextUrl.search || '';
  const url = `${BACKEND_URL}/api/v2/${targetPath}${search}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });

  // Attach the verified session token server-side.
  const token = await getServerAuthToken();
  if (token) headers.set('authorization', `Bearer ${token}`);

  let body: BodyInit | undefined;
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    body = await req.arrayBuffer();
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const upstream = await fetch(url, {
      method: req.method,
      headers,
      body,
      signal: controller.signal,
      redirect: 'manual',
      cache: 'no-store',
    });

    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      if (HOP_BY_HOP.has(key.toLowerCase())) return;
      // Preserve every Set-Cookie: the anonymous session id arrives this way.
      responseHeaders.append(key, value);
    });

    return new NextResponse(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    const aborted = error instanceof Error && error.name === 'AbortError';
    console.error(`Backend proxy ${req.method} /api/v2/${targetPath} failed:`, error);

    return NextResponse.json(
      {
        detail: aborted
          ? 'HerWay took too long to respond. Your information is safe — please try again.'
          : 'We could not reach HerWay right now. Your information is safe — please try again.',
      },
      { status: aborted ? 504 : 502 },
    );
  } finally {
    clearTimeout(timer);
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function PATCH(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function PUT(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function DELETE(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
