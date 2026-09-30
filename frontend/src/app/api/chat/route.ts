import { NextResponse } from 'next/server';
import { GoogleGenerativeAI } from '@google/generative-ai';

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

/**
 * /api/chat — LawBot chat proxy.
 *
 * Routing logic:
 * 1. If case_id is provided → forward to /api/v2/chat (case-aware ChatAgent)
 *    with mode='legal' so the agent uses invoke_lawbot + case context.
 * 2. If no case_id → call Gemini directly with a legal system prompt
 *    (backward-compatible, existing LawBot standalone behavior).
 *
 * This preserves the existing LawBot page without any changes to that component.
 */
export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { userInput, case_id, history } = body;

    if (case_id) {
      // --- Case-aware path: forward to HerWay backend ChatAgent ---
      const backendRes = await fetch(`${BACKEND_URL}/api/v2/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id,
          message: userInput,
          history: history || [],
          mode: 'legal',
        }),
      });
      if (!backendRes.ok) {
        throw new Error(`Backend returned ${backendRes.status}`);
      }
      const data = await backendRes.json();
      return NextResponse.json({ reply: data.reply, sources: data.sources || [] });
    }

    // --- Standalone LawBot path: direct Gemini call (original behavior) ---
    const genAI = new GoogleGenerativeAI(GEMINI_API_KEY!);
    const model = genAI.getGenerativeModel({
      model: 'gemini-1.5-flash',
      systemInstruction:
        'You are LawBot, a legal information assistant specialising in Indian law, ' +
        "women's rights, IPC sections, consumer protection, and workplace safety (POSH). " +
        'Provide clear, factual legal information. Always clarify that this is information, ' +
        'not formal legal advice, and recommend consulting a qualified advocate for personal cases.',
    });
    const result = await model.generateContent(userInput);
    return NextResponse.json({ reply: result.response.text(), sources: [] });
  } catch (error) {
    console.error('LawBot /api/chat error:', error);
    return NextResponse.json(
      { error: 'There was an issue processing your request.' },
      { status: 500 }
    );
  }
}
