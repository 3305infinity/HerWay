'use client';

import React, { Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowUp, Check, Fingerprint, Scale, Sparkles, Triangle } from 'lucide-react';

import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { InlineError } from '@/components/States';
import { apiPost } from '@/lib/api';
import type { CaseRecord } from '@/lib/types';

const ChatSchema = z.object({
  message: z.string().min(1, 'Message cannot be empty'),
});

type ChatFormValues = z.infer<typeof ChatSchema>;

const PROMPT_SUGGESTIONS = [
  { text: 'My rights under the Domestic Violence Act', icon: <Scale className="h-4 w-4" /> },
  { text: 'How do I file a POSH complaint at work?', icon: <Triangle className="h-4 w-4" /> },
  { text: 'How do I report online harassment?', icon: <Check className="h-4 w-4" /> },
  { text: 'How do I get free legal aid?', icon: <Fingerprint className="h-4 w-4" /> },
];

interface Message {
  text: string;
  isUser: boolean;
  failed?: boolean;
  sources?: string[];
}

function LawBotPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const caseId = searchParams?.get('case_id') ?? null;

  const [messages, setMessages] = React.useState<Message[]>([]);
  const [isThinking, setIsThinking] = React.useState(false);
  const [chatError, setChatError] = React.useState<string | null>(null);
  const [isPromoting, setIsPromoting] = React.useState(false);
  const [promoteError, setPromoteError] = React.useState<string | null>(null);
  const endRef = React.useRef<HTMLDivElement>(null);

  const form = useForm<ChatFormValues>({
    resolver: zodResolver(ChatSchema),
    defaultValues: { message: '' },
  });

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isThinking]);

  const onSubmit = async (data: ChatFormValues) => {
    const question = data.message.trim();
    if (!question || isThinking) return;

    setMessages((prev) => [...prev, { text: question, isUser: true }]);
    form.reset();
    setIsThinking(true);
    setChatError(null);

    // The previous version had no error handling at all: a failed request left
    // `isThinking` true forever and rendered an empty assistant bubble.
    const result = await apiPost<{ reply: string; sources?: string[] }>('/api/v2/chat', {
      ...(caseId ? { case_id: caseId } : {}),
      message: question,
      mode: 'legal',
      history: messages
        .filter((m) => !m.failed)
        .slice(-12)
        .map((m) => ({ role: m.isUser ? 'user' : 'assistant', content: m.text })),
    });

    if (result.ok && result.data.reply) {
      setMessages((prev) => [
        ...prev,
        { text: result.data.reply, isUser: false, sources: result.data.sources },
      ]);
    } else {
      const message = result.ok
        ? 'LawBot did not return an answer. Please try asking again.'
        : result.error.message;
      setChatError(message);
      setMessages((prev) => [
        ...prev,
        {
          text:
            'I could not answer that just now, and I am not going to guess at the law.\n\n' +
            'Free legal aid is available to women through your District Legal Services ' +
            'Authority — see nalsa.gov.in. For emergencies call 112, or 181 for the ' +
            'women helpline.',
          isUser: false,
          failed: true,
        },
      ]);
    }
    setIsThinking(false);
  };

  const handlePromptClick = (prompt: string) => {
    form.setValue('message', prompt);
    void form.handleSubmit(onSubmit)();
  };

  const handlePromoteToCase = async () => {
    if (messages.length === 0 || isPromoting) return;
    setIsPromoting(true);
    setPromoteError(null);

    const userQuestions = messages
      .filter((m) => m.isUser)
      .map((m) => m.text)
      .join('. ');
    const firstQuestion = messages.find((m) => m.isUser)?.text ?? 'Legal enquiry';

    // Goes through the Next proxy. The old relative call hit a route that did
    // not exist, so this button 404'd silently and nothing ever happened.
    const result = await apiPost<CaseRecord>('/api/v2/cases', {
      situation_text: userQuestions || firstQuestion,
      category: 'legal_information',
      title: `Legal enquiry: ${firstQuestion.slice(0, 45)}`,
    });

    if (result.ok) {
      router.push(`/cases/${result.data.id}`);
    } else {
      setPromoteError(result.error.message);
      setIsPromoting(false);
    }
  };

  const disclaimer = (
    <p className="text-[11px] text-muted-foreground leading-relaxed">
      LawBot gives legal information about Indian law, not legal advice, and it is not a
      lawyer. Free legal aid is available to women through DLSA and NALSA.
    </p>
  );

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-4 py-10 w-full">
        {caseId && (
          <div className="mb-6 px-4 py-2 rounded-xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-700 dark:text-blue-300 flex items-center gap-3 flex-wrap justify-center">
            <span>Answers will use the verified sources in your case</span>
            <Link href={`/cases/${caseId}`} className="font-semibold underline hover:no-underline">
              Back to case →
            </Link>
          </div>
        )}

        <h1 className="text-2xl sm:text-3xl font-semibold text-foreground mb-2 text-center">
          What would you like to understand?
        </h1>
        <p className="text-sm text-muted-foreground mb-6 text-center max-w-md">
          Ask about your rights under Indian law. You do not need to use legal words.
        </p>

        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex items-center max-w-2xl w-full gap-2"
        >
          <div className="rounded-xl flex w-full items-center bg-muted/50 border border-border p-1">
            <Input
              {...form.register('message')}
              className="focus-within:ring-0 ring-offset-transparent text-sm focus-visible:ring-0 bg-transparent rounded-lg focus-visible:ring-transparent px-4 py-3 border-none"
              placeholder="Ask about your rights, a law, or how to complain…"
              autoComplete="off"
              aria-label="Your legal question"
            />
            <Button
              className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-lg"
              disabled={isThinking}
              type="submit"
              aria-label="Send question"
            >
              <ArrowUp size={20} />
            </Button>
          </div>
        </form>

        <div className="mt-5 flex items-center gap-2.5 flex-wrap justify-center max-w-2xl">
          {PROMPT_SUGGESTIONS.map((prompt) => (
            <button
              key={prompt.text}
              type="button"
              onClick={() => handlePromptClick(prompt.text)}
              className="flex items-center gap-2 border border-border rounded-full px-4 py-2 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 hover:bg-muted/30 transition-colors"
            >
              {prompt.icon}
              {prompt.text}
            </button>
          ))}
        </div>

        <div className="mt-6 max-w-md text-center">{disclaimer}</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 w-full max-w-3xl mx-auto px-4 pt-3 pb-4">
      {caseId ? (
        <div className="w-full mb-3 px-4 py-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-700 dark:text-blue-300 flex items-center justify-between gap-3 flex-wrap">
          <span>Answers grounded in your case&apos;s verified sources</span>
          <Link href={`/cases/${caseId}`} className="font-semibold underline hover:no-underline">
            Back to case →
          </Link>
        </div>
      ) : (
        <div className="w-full mb-2 px-1 py-2 border-b border-border flex items-center justify-between gap-3 text-xs flex-wrap">
          <span className="text-muted-foreground">Legal information session</span>
          <button
            type="button"
            onClick={() => void handlePromoteToCase()}
            disabled={isPromoting}
            className="px-3 py-1 rounded-lg border border-primary/40 text-primary hover:bg-primary/10 transition-colors inline-flex items-center gap-1.5 font-medium disabled:opacity-50"
          >
            <Sparkles size={13} />
            <span>{isPromoting ? 'Creating case…' : 'Save this as a case'}</span>
          </button>
        </div>
      )}

      {promoteError && (
        <div className="mb-2">
          <InlineError message={promoteError} onDismiss={() => setPromoteError(null)} />
        </div>
      )}

      <div className="flex-1 overflow-y-auto custom-scrollbar min-h-[50vh] max-h-[70vh] py-3 space-y-3">
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex items-start gap-2 ${message.isUser ? 'justify-end' : ''}`}
          >
            <div
              className={`py-3 px-4 rounded-xl max-w-[85%] text-sm leading-relaxed ${
                message.isUser
                  ? 'bg-primary text-primary-foreground'
                  : message.failed
                  ? 'bg-rose-500/10 border border-rose-500/30 text-foreground whitespace-pre-wrap'
                  : 'bg-muted text-foreground border border-border'
              }`}
            >
              {message.isUser || message.failed ? (
                message.text
              ) : (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
                </div>
              )}
              {(message.sources?.length ?? 0) > 0 && (
                <div className="mt-2 pt-2 border-t border-border/50 space-y-1">
                  <p className="text-[11px] font-medium text-muted-foreground">Sources</p>
                  {message.sources!.slice(0, 4).map((url) => (
                    <a
                      key={url}
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-[11px] text-primary hover:underline break-all"
                    >
                      {url.replace(/^https?:\/\//, '').split('/')[0]}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {isThinking && (
          <div className="flex items-center space-x-3">
            <Skeleton className="h-9 w-9 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-3 w-[220px]" />
              <Skeleton className="h-3 w-[170px]" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {chatError && (
        <div className="mb-2">
          <InlineError message={chatError} onDismiss={() => setChatError(null)} />
        </div>
      )}

      <form onSubmit={form.handleSubmit(onSubmit)} className="flex items-center w-full gap-2">
        <div className="rounded-xl flex w-full items-center border bg-muted/50 border-border p-1">
          <Input
            {...form.register('message')}
            className="focus-within:ring-0 ring-offset-transparent text-sm bg-transparent focus-visible:ring-0 rounded-lg focus-visible:ring-transparent px-4 py-3 border-none"
            placeholder="Ask another question…"
            autoComplete="off"
            aria-label="Your legal question"
          />
          <Button
            className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-lg"
            disabled={isThinking}
            type="submit"
            aria-label="Send question"
          >
            <ArrowUp size={20} />
          </Button>
        </div>
      </form>

      <div className="pt-2">{disclaimer}</div>
    </div>
  );
}

export default function Page() {
  // useSearchParams needs a Suspense boundary during static rendering.
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading…</div>}>
      <LawBotPage />
    </Suspense>
  );
}
