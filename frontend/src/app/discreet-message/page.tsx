'use client';

import React, { useRef, useState } from 'react';
import Link from 'next/link';
import { InlineError } from '@/components/States';
import { apiGet, apiUpload } from '@/lib/api';

/**
 * Discreet message — hide a short message inside an ordinary photo, and read
 * one back out.
 *
 * This page replaces a flow that never worked end to end: the old "Discreet
 * Message" route collected a long abuse-report form, generated AI imagery, then
 * posted the image URL to the wrong endpoint and read a field
 * (`encodedImage`) that endpoint never returned — so the share link was
 * literally the string "undefined", and nothing was ever encoded or decoded.
 *
 * It is also deliberately honest about what steganography does and does not
 * protect against. Overstating it to someone deciding whether it is safe to
 * send a message would be the most dangerous thing on this page.
 */

interface EncodeResponse {
  image_base64: string;
  filename: string;
  message_length: number;
  capacity_used_percent: number;
  limitations: string[];
}

interface DecodeResponse {
  found: boolean;
  message: string | null;
  note: string;
}

const MAX_FILE_BYTES = 8 * 1024 * 1024;

export default function DiscreetMessagePage() {
  const [mode, setMode] = useState<'hide' | 'read'>('hide');

  // Hide
  const [message, setMessage] = useState('');
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [encoded, setEncoded] = useState<EncodeResponse | null>(null);
  const [isEncoding, setIsEncoding] = useState(false);
  const [encodeError, setEncodeError] = useState<string | null>(null);

  // Read
  const [readFile, setReadFile] = useState<File | null>(null);
  const [decoded, setDecoded] = useState<DecodeResponse | null>(null);
  const [isDecoding, setIsDecoding] = useState(false);
  const [decodeError, setDecodeError] = useState<string | null>(null);

  const [limitations, setLimitations] = useState<string[]>([]);
  const hideInputRef = useRef<HTMLInputElement>(null);
  const readInputRef = useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    void (async () => {
      const result = await apiGet<{ limitations: string[] }>('/api/v2/discreet/limitations');
      if (result.ok) setLimitations(result.data.limitations);
    })();
  }, []);

  const pickCover = (file: File | null) => {
    setEncodeError(null);
    setEncoded(null);
    if (!file) {
      setCoverFile(null);
      setCoverPreview(null);
      return;
    }
    if (!file.type.startsWith('image/')) {
      setEncodeError('Please choose an image file (PNG works best).');
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setEncodeError('Please choose an image smaller than 8 MB.');
      return;
    }
    setCoverFile(file);
    setCoverPreview(URL.createObjectURL(file));
  };

  const handleEncode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!coverFile || !message.trim()) return;

    setIsEncoding(true);
    setEncodeError(null);
    setEncoded(null);

    const form = new FormData();
    form.append('message', message.trim());
    form.append('file', coverFile);

    const result = await apiUpload<EncodeResponse>('/api/v2/discreet/encode', form);
    if (result.ok) {
      setEncoded(result.data);
    } else {
      setEncodeError(result.error.message);
    }
    setIsEncoding(false);
  };

  const handleDecode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!readFile) return;

    setIsDecoding(true);
    setDecodeError(null);
    setDecoded(null);

    const form = new FormData();
    form.append('file', readFile);

    const result = await apiUpload<DecodeResponse>('/api/v2/discreet/decode', form);
    if (result.ok) {
      setDecoded(result.data);
    } else {
      setDecodeError(result.error.message);
    }
    setIsDecoding(false);
  };

  const downloadEncoded = () => {
    if (!encoded) return;
    const link = document.createElement('a');
    link.href = `data:image/png;base64,${encoded.image_base64}`;
    link.download = encoded.filename || 'photo.png';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const resetHide = () => {
    setMessage('');
    setCoverFile(null);
    setCoverPreview(null);
    setEncoded(null);
    setEncodeError(null);
    if (hideInputRef.current) hideInputRef.current.value = '';
  };

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-background">
      <div className="bg-rose-900/10 border-b border-rose-500/20 px-4 py-2">
        <div className="max-w-3xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-rose-800 dark:text-rose-300">
          <span>In immediate danger?</span>
          <div className="flex items-center gap-4 font-mono font-medium">
            <a href="tel:112" className="hover:underline">112 Emergency</a>
            <a href="tel:181" className="hover:underline">181 Women Helpline</a>
          </div>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 space-y-6">
        <div className="space-y-2">
          <h1 className="font-serif text-2xl sm:text-3xl text-foreground font-normal">
            Discreet message
          </h1>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Hide a short message inside an ordinary photo, so the picture looks like any other
            if someone checks your phone. The person you send it to opens this same page to
            read it.
          </p>
        </div>

        {/* The honest limitations, before anything else. */}
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4 space-y-2">
          <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">
            Please read this first — this is not encryption
          </p>
          <ul className="space-y-1.5">
            {(limitations.length
              ? limitations
              : [
                  'This hides your message from a casual look. It is not encryption.',
                  'Send the image as a file or document attachment. WhatsApp, Instagram and similar apps compress photos, which destroys the hidden message.',
                  'If someone has monitoring software on your device, they can see what you type regardless of this feature.',
                  'The person receiving it needs to open it here to read the message.',
                ]
            ).map((l, i) => (
              <li key={i} className="text-xs text-muted-foreground leading-relaxed flex gap-2">
                <span aria-hidden="true" className="mt-1.5 h-1 w-1 rounded-full bg-amber-500 shrink-0" />
                <span>{l}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Mode */}
        <div className="border-b border-border" role="tablist">
          {(
            [
              { id: 'hide' as const, label: 'Hide a message' },
              { id: 'read' as const, label: 'Read a message' },
            ]
          ).map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={mode === tab.id}
              onClick={() => setMode(tab.id)}
              className={`px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors ${
                mode === tab.id
                  ? 'border-primary text-primary font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Hide */}
        {mode === 'hide' && (
          <form onSubmit={handleEncode} className="space-y-5">
            <div className="space-y-1.5">
              <label htmlFor="cover-image" className="text-xs font-medium text-muted-foreground">
                1. Choose an ordinary photo
              </label>
              <input
                id="cover-image"
                ref={hideInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => pickCover(e.target.files?.[0] ?? null)}
                className="w-full text-sm text-foreground file:mr-3 file:rounded-lg file:border-0 file:bg-muted file:px-4 file:py-2 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted/80 cursor-pointer"
              />
              <p className="text-[11px] text-muted-foreground">
                A larger photo can hold a longer message. PNG is best.
              </p>
            </div>

            {coverPreview && (
              // eslint-disable-next-line @next/next/no-img-element -- local object URL, not a remote asset
              <img
                src={coverPreview}
                alt="The photo you chose"
                className="max-h-56 rounded-xl border border-border object-contain"
              />
            )}

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="secret-message" className="text-xs font-medium text-muted-foreground">
                  2. Write your message
                </label>
                <span className="text-[11px] text-muted-foreground">{message.length}/2000</span>
              </div>
              <textarea
                id="secret-message"
                rows={4}
                maxLength={2000}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Write what you need to say. You can write in any language."
                className="w-full p-3.5 rounded-xl border border-input bg-card text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors resize-y"
              />
            </div>

            {encodeError && <InlineError message={encodeError} onDismiss={() => setEncodeError(null)} />}

            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="submit"
                disabled={isEncoding || !coverFile || !message.trim()}
                className="px-6 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-40 transition-colors"
              >
                {isEncoding ? 'Hiding your message…' : 'Hide message in photo'}
              </button>
              {(coverFile || message) && (
                <button
                  type="button"
                  onClick={resetHide}
                  className="px-4 py-2.5 rounded-xl border border-border text-foreground text-sm font-medium hover:bg-muted transition-colors"
                >
                  Start over
                </button>
              )}
            </div>

            {encoded && (
              <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4 space-y-3">
                <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
                  Your photo is ready
                </p>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {encoded.message_length} characters are hidden inside it
                  ({encoded.capacity_used_percent}% of what this photo can hold). It looks the
                  same as the original.
                </p>
                {/* eslint-disable-next-line @next/next/no-img-element -- in-memory data URL */}
                <img
                  src={`data:image/png;base64,${encoded.image_base64}`}
                  alt="Your photo with the message hidden inside it"
                  className="max-h-56 rounded-lg border border-border object-contain"
                />
                <button
                  type="button"
                  onClick={downloadEncoded}
                  className="px-5 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                >
                  Download the photo
                </button>
                <p className="text-xs text-amber-800 dark:text-amber-300 leading-relaxed">
                  Send this as a <strong>file or document attachment</strong>, or by email. If you
                  send it as a normal photo in a chat app it will be compressed and the message
                  will be lost.
                </p>
              </div>
            )}
          </form>
        )}

        {/* Read */}
        {mode === 'read' && (
          <form onSubmit={handleDecode} className="space-y-5">
            <div className="space-y-1.5">
              <label htmlFor="read-image" className="text-xs font-medium text-muted-foreground">
                Upload the photo you were sent
              </label>
              <input
                id="read-image"
                ref={readInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  setDecodeError(null);
                  setDecoded(null);
                  setReadFile(e.target.files?.[0] ?? null);
                }}
                className="w-full text-sm text-foreground file:mr-3 file:rounded-lg file:border-0 file:bg-muted file:px-4 file:py-2 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted/80 cursor-pointer"
              />
            </div>

            {decodeError && <InlineError message={decodeError} onDismiss={() => setDecodeError(null)} />}

            <button
              type="submit"
              disabled={isDecoding || !readFile}
              className="px-6 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-40 transition-colors"
            >
              {isDecoding ? 'Reading…' : 'Read hidden message'}
            </button>

            {decoded && (
              <div
                className={`rounded-xl border p-4 space-y-2 ${
                  decoded.found
                    ? 'border-emerald-500/40 bg-emerald-500/5'
                    : 'border-border bg-muted/20'
                }`}
              >
                <p className="text-sm font-semibold text-foreground">
                  {decoded.found ? 'Hidden message' : 'No hidden message found'}
                </p>
                {decoded.message && (
                  <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed bg-background border border-border rounded-lg p-3">
                    {decoded.message}
                  </p>
                )}
                <p className="text-xs text-muted-foreground leading-relaxed">{decoded.note}</p>
              </div>
            )}
          </form>
        )}

        <div className="border-t border-border pt-5 space-y-2">
          <p className="text-xs text-muted-foreground">
            Looking for something else?{' '}
            <Link href="/community" className="text-primary hover:underline">
              Share your experience anonymously
            </Link>{' '}
            ·{' '}
            <Link href="/" className="text-primary hover:underline">
              Start a case
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
