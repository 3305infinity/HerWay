'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { Loader2, Sparkles } from 'lucide-react';

import { Button } from './ui/button';
import { InlineError } from './States';
import { apiPost } from '@/lib/api';
import type { CaseRecord } from '@/lib/types';

/**
 * Final step of the "share your experience" flow: publish the post
 * anonymously, and optionally open a private case from it.
 *
 * What changed and why:
 *
 * - The old `handleCommonFunction` posted the *image URL* to `/api/decompose`
 *   (a text endpoint) and then read `encodeImage.data.encodedImage` — a field
 *   that endpoint has never returned. The value was always `undefined`, so the
 *   Telegram share link was literally `...?url=undefined`. Nothing was ever
 *   encoded. Real steganography now lives on `/discreet-message`.
 * - Sharing fired before the save completed, so a failed save was invisible.
 * - "Share on Instagram" was a button with no handler at all.
 * - "Save as Guided Safety Case" posted to a route that did not exist.
 */

interface ShareProps {
  imageURL: string;
  resText: string;
  setShared: (shared: boolean) => void;
}

interface DecomposeResponse {
  decomposed: Record<string, string>;
}

export default function Share({ imageURL, resText, setShared }: ShareProps) {
  const router = useRouter();
  const [isPublishing, setIsPublishing] = useState(false);
  const [isSavingCase, setIsSavingCase] = useState(false);
  const [published, setPublished] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Structure the narrative and publish it to the community feed. */
  const publishPost = async (): Promise<boolean> => {
    setError(null);

    const decomposed = await apiPost<DecomposeResponse>('/api/decompose', {
      resText,
    });
    if (!decomposed.ok) {
      setError(`${decomposed.error.message} Your post has not been shared.`);
      return false;
    }

    // Contact details are deliberately not sent: the community feed is public.
    const saved = await apiPost('/api/save', decomposed.data.decomposed ?? {});
    if (!saved.ok) {
      setError(`${saved.error.message} Your post has not been shared.`);
      return false;
    }

    setPublished(true);
    setShared(true);
    return true;
  };

  const handlePublish = async () => {
    setIsPublishing(true);
    await publishPost();
    setIsPublishing(false);
  };

  const handleSaveToCase = async () => {
    setIsSavingCase(true);
    setError(null);

    const result = await apiPost<CaseRecord>('/api/v2/cases', {
      situation_text: resText,
      category: 'domestic_violence',
      title: 'From a shared report',
    });

    if (result.ok) {
      router.push(`/cases/${result.data.id}`);
      return;
    }

    setError(result.error.message);
    setIsSavingCase(false);
  };

  const shareText = encodeURIComponent(
    'Sharing an anonymous experience on HerWay — you are not alone.',
  );

  return (
    <div className="flex flex-col items-center gap-5 w-full max-w-xl mx-auto py-4">
      {imageURL && (
        <div className="relative w-full aspect-square max-w-sm">
          <Image
            src={imageURL}
            alt="The image accompanying your post"
            fill
            sizes="(max-width: 640px) 100vw, 384px"
            className="rounded-xl object-cover"
          />
        </div>
      )}

      {error && (
        <div className="w-full">
          <InlineError message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {published ? (
        <div className="w-full rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4 text-center space-y-2">
          <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
            Your experience has been shared anonymously
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Your contact details were not published. It may take a short while to appear
            while it is reviewed.
          </p>
          <Link href="/community" className="inline-block text-xs text-primary hover:underline">
            View the community →
          </Link>
        </div>
      ) : (
        <Button
          onClick={() => void handlePublish()}
          disabled={isPublishing}
          className="w-full sm:w-auto bg-primary text-primary-foreground hover:bg-primary/90"
        >
          {isPublishing ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Sharing…
            </>
          ) : (
            'Share anonymously with the community'
          )}
        </Button>
      )}

      <div className="w-full border-t border-border pt-5 space-y-3">
        <p className="text-xs text-muted-foreground text-center">
          You can also keep a private case for yourself — only you can see it.
        </p>
        <Button
          variant="outline"
          onClick={() => void handleSaveToCase()}
          disabled={isSavingCase}
          className="w-full flex items-center justify-center gap-2"
        >
          {isSavingCase ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles size={16} />
          )}
          <span>{isSavingCase ? 'Creating your case…' : 'Save this as a private case'}</span>
        </Button>
      </div>

      {published && imageURL && (
        <div className="w-full border-t border-border pt-5 space-y-2">
          <p className="text-xs text-muted-foreground text-center">
            Share the image elsewhere, if you want to
          </p>
          <div className="flex items-center justify-center gap-2 flex-wrap">
            <a
              href={`https://t.me/share/url?url=${encodeURIComponent(imageURL)}&text=${shareText}`}
              target="_blank"
              rel="noreferrer"
              className="px-4 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted transition-colors"
            >
              Telegram
            </a>
            <a
              href={`https://twitter.com/intent/tweet?url=${encodeURIComponent(imageURL)}&text=${shareText}`}
              target="_blank"
              rel="noreferrer"
              className="px-4 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted transition-colors"
            >
              X / Twitter
            </a>
            <a
              href={`https://wa.me/?text=${shareText}%20${encodeURIComponent(imageURL)}`}
              target="_blank"
              rel="noreferrer"
              className="px-4 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted transition-colors"
            >
              WhatsApp
            </a>
          </div>
          <p className="text-[11px] text-muted-foreground text-center leading-relaxed">
            Instagram does not accept shared links from a website — save the image and post
            it from the app if you want to use Instagram.
          </p>
        </div>
      )}
    </div>
  );
}
