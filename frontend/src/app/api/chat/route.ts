import { NextResponse } from 'next/server';

/**
 * Legacy LawBot endpoint.
 *
 * Kept so any older client still pointing here keeps working, but it now
 * forwards to the backend agent at `/api/v2/chat` rather than making its own
 * Gemini call. The direct call duplicated model configuration (it was pinned
 * to `gemini-1.5-flash`, which Google has since retired), skipped the legal
 * RAG lookup, and bypassed the grounding rules that stop LawBot stating law
 * from memory.
 */

const BACKEND_URL = (
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'http://localhost:8000'
).replace(/\/$/, '');

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { userInput, message, case_id, history } = body;
    const question = userInput ?? message;

    if (!question || typeof question !== 'string') {
      return NextResponse.json({ error: 'No question was provided.' }, { status: 400 });
    }

    const upstream = await fetch(`${BACKEND_URL}/api/v2/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Forward the session cookie so the backend can honour case ownership.
        ...(req.headers.get('cookie') ? { cookie: req.headers.get('cookie')! } : {}),
      },
      body: JSON.stringify({
        ...(case_id ? { case_id } : {}),
        message: question,
        history: history || [],
        mode: 'legal',
      }),
      signal: AbortSignal.timeout(65_000),
    });

    const data = await upstream.json();

    if (!upstream.ok) {
      return NextResponse.json(
        { error: data?.detail ?? 'LawBot is unavailable right now.' },
        { status: upstream.status },
      );
    }

    return NextResponse.json({ reply: data.reply, sources: data.sources ?? [] });
  } catch (error) {
    console.error('LawBot /api/chat error:', error);
    return NextResponse.json(
      {
        error:
          'We could not reach LawBot. Please try again. For urgent help call 112, or 181 for the women helpline.',
      },
      { status: 502 },
    );
  }
}
