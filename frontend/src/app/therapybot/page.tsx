'use client';

import React, { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import HavenAvatar from '@/components/HavenAvatar';
import { InlineError } from '@/components/States';
import { apiPost } from '@/lib/api';
import type { CaseRecord, ChatReply } from '@/lib/types';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  /** True when this bubble reports a failure rather than carrying a real reply. */
  failed?: boolean;
}

const SUGGESTIONS = [
  'I am feeling overwhelmed and need help calming down.',
  'Can you guide me through a 4-7-8 calming breath?',
  'My partner is threatening me and I am scared.',
  'I just need someone safe to listen right now.',
];

function TherapyBotPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // When opened from a Case Workspace (/therapybot?case_id=xxx), Niva has
  // full case context and can invoke safety plan tools if situation escalates.
  const caseId = searchParams?.get('case_id') || null;

  const [isPromoting, setIsPromoting] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        "Hello, I'm Niva. Take a deep breath — you are in a safe, confidential space with HerWay. Whether you're feeling overwhelmed, looking for guidance, or just need someone to talk to, I'm right here with you.",
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto scroll messages to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Clean up any ongoing speech synthesis on unmount
  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const speakText = (text: string) => {
    if (!voiceEnabled || typeof window === 'undefined' || !('speechSynthesis' in window)) {
      return;
    }

    try {
      window.speechSynthesis.cancel();
      const cleanText = text.replace(/[*_#`]/g, '').slice(0, 300);
      const utterance = new SpeechSynthesisUtterance(cleanText);
      utterance.rate = 0.95;
      utterance.pitch = 1.05;

      // Select gentle female voice if available
      const voices = window.speechSynthesis.getVoices();
      const preferred = voices.find(
        (v) =>
          v.lang.startsWith('en') &&
          (v.name.includes('Samantha') ||
            v.name.includes('Zira') ||
            v.name.includes('Natural') ||
            v.name.includes('Female'))
      );
      if (preferred) utterance.voice = preferred;

      utterance.onstart = () => setIsSpeaking(true);
      utterance.onend = () => setIsSpeaking(false);
      utterance.onerror = () => setIsSpeaking(false);

      window.speechSynthesis.speak(utterance);
    } catch {
      setIsSpeaking(false);
    }
  };

  const stopSpeaking = () => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      setIsSpeaking(false);
    }
  };

  const handleSendMessage = async (textToSend?: string) => {
    const text = (textToSend || inputText).trim();
    if (!text || isLoading) return;

    setInputText('');
    stopSpeaking();

    const newHistory: Message[] = [...messages, { role: 'user', content: text }];
    setMessages(newHistory);
    setIsLoading(true);

    setError(null);

    const result = await apiPost<ChatReply>('/api/v2/chat', {
      message: text,
      // Pass case_id for case-grounded support when available
      ...(caseId ? { case_id: caseId } : {}),
      // mode='therapy' keeps Niva supportive and stops legal escalation
      mode: 'therapy',
      history: newHistory.slice(-8).map((m) => ({ role: m.role, content: m.content })),
    });

    if (result.ok && result.data.reply) {
      setMessages((prev) => [...prev, { role: 'assistant', content: result.data.reply }]);
      speakText(result.data.reply);
    } else {
      // Niva does not invent a reply when the service is down. The previous
      // version emitted a scripted "supportive" message that was visually
      // identical to a real answer, so a user in distress could not tell that
      // nobody had actually responded to what she said.
      const detail = result.ok
        ? 'Niva did not reply this time.'
        : result.error.message;
      setError(detail);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content:
            'I am having trouble replying right now — this is a connection problem, not ' +
            'anything you did. What you wrote has not been lost.\n\n' +
            'If you need to talk to someone now, Tele-MANAS is free and available 24 hours ' +
            'on 14416. In an emergency, call 112.',
          failed: true,
        },
      ]);
    }
    setIsLoading(false);
  };

  const handleSaveAsCase = async () => {
    const userMsgs = messages.filter((m) => m.role === 'user').map((m) => m.content);
    if (userMsgs.length === 0 || isPromoting) return;

    setIsPromoting(true);
    setError(null);

    const situation = userMsgs.join('. ');
    // Ownership comes from the session, not from a hardcoded "anonymous" —
    // which previously meant saved sessions never appeared in My cases.
    const result = await apiPost<CaseRecord>('/api/v2/cases', {
      situation_text: situation,
      category: 'other_women_safety',
      title: `From a conversation with Niva: ${situation.slice(0, 40)}`,
    });

    if (result.ok) {
      router.push(`/cases/${result.data.id}`);
    } else {
      setError(result.error.message);
      setIsPromoting(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-background flex flex-col">
      {/* Safety Help Strip */}
      <div className="bg-rose-900/10 border-b border-rose-500/20 px-4 py-2">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-rose-800 dark:text-rose-300">
          <span>In immediate danger? Emergency helplines are always active:</span>
          <div className="flex items-center gap-4 font-mono font-medium">
            <a href="tel:112" className="hover:underline">
              112 (Emergency)
            </a>
            <a href="tel:181" className="hover:underline">
              181 (Women Helpline)
            </a>
            <a href="tel:1091" className="hover:underline">
              1091 (Women Police)
            </a>
          </div>
        </div>
      </div>

      {/* Main Workspace */}
      <div className="flex-1 max-w-5xl mx-auto w-full p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-6">
        {/* Left Column: 3D Niva Avatar */}
        <div className="flex flex-col space-y-4">
          <div className="h-[380px] sm:h-[460px] w-full">
            <HavenAvatar isSpeaking={isSpeaking} />
          </div>

          {/* Voice Controls */}
          <div className="flex items-center justify-between p-3 rounded-xl border border-border bg-card text-xs">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Voice:</span>
              <button
                type="button"
                onClick={() => {
                  if (voiceEnabled) stopSpeaking();
                  setVoiceEnabled(!voiceEnabled);
                }}
                className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                  voiceEnabled
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:text-foreground'
                }`}
              >
                {voiceEnabled ? '🔊 Voice On' : '🔇 Muted'}
              </button>
            </div>

            {isSpeaking && (
              <button
                type="button"
                onClick={stopSpeaking}
                className="px-2.5 py-1 rounded-md bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300 font-medium hover:bg-rose-200 transition-colors"
              >
                Stop speaking
              </button>
            )}
          </div>

          <div className="p-3 rounded-xl border border-border bg-muted/20 text-xs text-muted-foreground leading-relaxed">
            <strong>Privacy:</strong> this conversation is private to you and is not shared.
            Press <kbd className="px-1 py-0.5 rounded border border-border bg-background text-[10px]">Esc</kbd>{' '}
            at any time to leave immediately — though that cannot erase your browser history.{' '}
            <Link href="/privacy" className="text-primary hover:underline">What this does and does not protect</Link>
          </div>
        </div>

        {/* Right Column: Conversational Chat */}
        <div className="flex flex-col border border-border rounded-2xl bg-card shadow-sm overflow-hidden h-[600px] lg:h-auto">
          {/* Header */}
          <div className="px-5 py-3.5 border-b border-border flex items-center justify-between bg-muted/10 flex-wrap gap-2">
            <div>
              <h1 className="text-sm font-semibold text-foreground">Talk to Niva</h1>
              <p className="text-xs text-muted-foreground">HerWay&apos;s gentle, supportive companion for your thoughts</p>
            </div>
            <div className="flex items-center gap-2">
              {caseId ? (
                <Link
                  href={`/cases/${caseId}`}
                  className="text-xs text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-700 px-2.5 py-1 rounded-md font-medium hover:bg-purple-100 transition-colors"
                >
                  ← Back to Case
                </Link>
              ) : messages.some((m) => m.role === 'user') ? (
                <button
                  type="button"
                  onClick={handleSaveAsCase}
                  disabled={isPromoting}
                  className="text-xs text-primary bg-primary/10 border border-primary/30 px-2.5 py-1 rounded-md font-medium hover:bg-primary/20 transition-colors disabled:opacity-50"
                >
                  {isPromoting ? 'Creating case…' : '✨ Save as Guided Case'}
                </button>
              ) : (
                <Link
                  href="/cases"
                  className="text-xs text-primary hover:underline font-medium"
                >
                  My Cases →
                </Link>
              )}
            </div>
          </div>

          {/* Messages scroll area */}
          <div className="flex-1 p-4 overflow-y-auto space-y-3.5 custom-scrollbar">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`max-w-[85%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground ml-auto rounded-br-xs'
                    : msg.failed
                    ? 'bg-rose-500/10 border border-rose-500/30 text-foreground mr-auto rounded-bl-xs'
                    : 'bg-muted/50 border border-border text-foreground mr-auto rounded-bl-xs'
                }`}
              >
                {msg.content}
              </div>
            ))}

            {isLoading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground p-2">
                <span className="w-3.5 h-3.5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                Niva is listening and thinking…
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {error && (
            <div className="px-3 pt-2">
              <InlineError message={error} onDismiss={() => setError(null)} />
            </div>
          )}

          {/* Quick prompt suggestions */}
          <div className="px-4 py-2 border-t border-border bg-muted/10 flex gap-2 overflow-x-auto no-scrollbar">
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                type="button"
                onClick={() => handleSendMessage(s)}
                className="whitespace-nowrap px-3 py-1.5 rounded-full text-xs bg-background border border-border hover:border-primary/50 text-muted-foreground hover:text-foreground transition-colors shrink-0"
              >
                {s}
              </button>
            ))}
          </div>

          {/* Input form */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage();
            }}
            className="p-3 border-t border-border flex gap-2 bg-background"
          >
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="Type your message here or click a prompt above…"
              disabled={isLoading}
              className="flex-1 px-4 py-2.5 text-sm rounded-xl border border-input bg-background focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isLoading || !inputText.trim()}
              className="px-5 py-2.5 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground text-sm font-medium rounded-xl transition-colors shrink-0"
            >
              Send
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function Page() {
  // useSearchParams requires a Suspense boundary during static rendering.
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading…</div>}>
      <TherapyBotPage />
    </Suspense>
  );
}
