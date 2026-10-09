'use client';

/**
 * Dictation for the situation box, using the browser's own Web Speech API.
 *
 * Why this matters more here than on most products
 * ------------------------------------------------
 * Typing out what happened to you is work, and it is hardest exactly when you
 * are most upset. It is harder again in a second language: many users think in
 * Hindi or Marathi and type in English only because the box expects it. Speech
 * removes both barriers at once.
 *
 * Everything happens in the browser. No audio is uploaded, nothing is stored,
 * and HerWay never receives a recording — only the text the user chooses to
 * keep. That is stated in the UI, because a microphone button on a
 * domestic-violence product needs to answer "where does this go?" immediately.
 *
 * Support is uneven (Chrome and Edge have it, Firefox does not), so the button
 * renders only where it will actually work rather than showing a control that
 * fails on press.
 */

import React from 'react';

/** Languages offered. `hi-IN` handles Hinglish dictation noticeably better
 *  than `en-IN` for code-mixed speech, which is how most users actually talk. */
const LANGUAGES = [
  { code: 'en-IN', label: 'English' },
  { code: 'hi-IN', label: 'हिंदी' },
  { code: 'mr-IN', label: 'मराठी' },
  { code: 'bn-IN', label: 'বাংলা' },
  { code: 'ta-IN', label: 'தமிழ்' },
  { code: 'te-IN', label: 'తెలుగు' },
] as const;

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onend: (() => void) | null;
};

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition || w.webkitSpeechRecognition) as
    | (new () => SpeechRecognitionLike)
    | null;
}

export default function VoiceInput({
  onTranscript,
  className = '',
}: {
  /** Called with each finalised chunk, to append to the textarea. */
  onTranscript: (text: string) => void;
  className?: string;
}) {
  const [supported, setSupported] = React.useState(false);
  const [listening, setListening] = React.useState(false);
  const [language, setLanguage] = React.useState<string>('en-IN');
  const [error, setError] = React.useState<string | null>(null);
  const recognitionRef = React.useRef<SpeechRecognitionLike | null>(null);

  // Checked after mount: `window` does not exist during SSR, and rendering the
  // button optimistically would make it flash in on browsers that lack support.
  React.useEffect(() => {
    setSupported(getRecognitionCtor() !== null);
    return () => recognitionRef.current?.stop();
  }, []);

  const stop = React.useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
  }, []);

  const start = React.useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;

    setError(null);
    const recognition = new Ctor();
    recognition.lang = language;
    recognition.continuous = true;
    // Interim results are discarded — appending them would make the textarea
    // rewrite itself while someone is mid-sentence, which is unsettling to
    // watch and makes the text hard to trust.
    recognition.interimResults = false;

    recognition.onresult = (event: unknown) => {
      const e = event as { results: ArrayLike<ArrayLike<{ transcript: string }>>; resultIndex: number };
      let finalText = '';
      for (let i = e.resultIndex; i < e.results.length; i += 1) {
        finalText += e.results[i][0].transcript;
      }
      if (finalText.trim()) onTranscript(finalText.trim());
    };

    recognition.onerror = (event: unknown) => {
      const code = (event as { error?: string }).error;
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        setError('Microphone access was blocked. You can still type instead.');
      } else if (code === 'no-speech') {
        setError('I did not catch anything. Try again, or type instead.');
      } else if (code !== 'aborted') {
        setError('Dictation stopped working. You can still type instead.');
      }
      stop();
    };

    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, [language, onTranscript, stop]);

  if (!supported) return null;

  return (
    <div className={`space-y-2 ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={listening ? stop : start}
          aria-pressed={listening}
          className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
            listening
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border bg-card text-foreground hover:border-primary/50'
          }`}
        >
          <span className="relative flex h-2 w-2" aria-hidden>
            {listening && (
              <span className="absolute inline-flex h-full w-full rounded-full bg-primary/60 motion-safe:animate-ping" />
            )}
            <span
              className={`relative inline-flex h-2 w-2 rounded-full ${
                listening ? 'bg-primary' : 'bg-muted-foreground/50'
              }`}
            />
          </span>
          {listening ? 'Listening — tap to stop' : 'Speak instead of typing'}
        </button>

        <label className="sr-only" htmlFor="voice-language">
          Dictation language
        </label>
        <select
          id="voice-language"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          disabled={listening}
          className="rounded-lg border border-border bg-card px-2 py-1.5 text-xs text-foreground disabled:opacity-50"
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <p role="alert" className="text-[11px] text-amber-600 dark:text-amber-400">
          {error}
        </p>
      ) : (
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Speech is converted by your browser on this device. No audio is sent to
          HerWay or saved anywhere — only the words that appear in the box.
        </p>
      )}
    </div>
  );
}
