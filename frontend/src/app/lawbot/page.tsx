'use client';
import React from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { Input } from '../../components/ui/input';
import { ArrowUp, Scale, Triangle, Check, Fingerprint, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useClerk } from '@clerk/nextjs';
import Image from 'next/image';
import modelImage from '../../assets/modelLogo.png';
import { Skeleton } from '@/components/ui/skeleton';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const ChatSchema = z.object({
  message: z.string().min(1, 'Message cannot be empty'),
});

type ChatFormValues = z.infer<typeof ChatSchema>;

const promptSuggestions = [
  { text: 'Indian Law', icon: <Scale className="text-gray-700" size={16} /> },
  {
    text: 'Indian Law IPC 320',
    icon: <Triangle className="text-gray-700" size={16} />,
  },
  { text: 'Women Rights', icon: <Check className="text-gray-700" size={16} /> },
  {
    text: 'Women Safety',
    icon: <Fingerprint className="text-gray-700" size={16} />,
  },
];

function Page() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // When opened from a Case Workspace (/lawbot?case_id=xxx), answers are
  // grounded in the case evidence via ChatAgent's invoke_lawbot tool.
  const caseId = searchParams?.get('case_id') || null;

  const [messages, setMessages] = React.useState<
    {
      text: string;
      isUser: boolean;
    }[]
  >([]);

  const [isPromoting, setIsPromoting] = React.useState(false);
  const typingText = useTypingText('What can I help you with?');
  const [isThinking, setIsThinking] = React.useState<boolean>(false);
  // Custom hook for typing effect
  function useTypingText(text: string, speed: number = 100) {
    const [displayedText, setDisplayedText] = React.useState('');

    React.useEffect(() => {
      let index = 0;
      const intervalId = setInterval(() => {
        setDisplayedText(text.slice(0, index + 1));
        index++;
        if (index === text.length) clearInterval(intervalId);
      }, speed);

      return () => clearInterval(intervalId);
    }, [text, speed]);

    return displayedText;
  }

  const { user } = useClerk();
  const form = useForm<ChatFormValues>({
    resolver: zodResolver(ChatSchema),
    defaultValues: { message: '' },
  });

  const onSubmit = async (data: ChatFormValues) => {
    setMessages((prev) => [...prev, { text: data.message, isUser: true }]);
    form.reset();
    setIsThinking(true);

    const response = await fetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        userInput: data.message,
        // Pass case_id so the proxy routes to case-aware ChatAgent
        ...(caseId ? { case_id: caseId } : {}),
        history: messages.map((m) => ({
          role: m.isUser ? 'user' : 'assistant',
          content: m.text,
        })),
      }),
      headers: { 'Content-Type': 'application/json' },
    });

    const result = await response.json();
    setMessages((prev) => [...prev, { text: result.reply, isUser: false }]);
    setIsThinking(false);
  };

  const handlePromptClick = (prompt: string) => {
    form.setValue('message', prompt);
    form.handleSubmit(onSubmit)();
  };

  const handlePromoteToCase = async () => {
    if (messages.length === 0 || isPromoting) return;
    setIsPromoting(true);
    try {
      const userQuestions = messages
        .filter((m) => m.isUser)
        .map((m) => m.text)
        .join('. ');
      const firstQuestion = messages.find((m) => m.isUser)?.text || 'Legal Inquiry';

      const res = await fetch('/api/v2/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: user?.id || 'anonymous',
          situation_text: userQuestions || firstQuestion,
          category: 'legal_information',
          title: `Legal Inquiry: ${firstQuestion.slice(0, 45)}`,
        }),
      });

      if (res.ok) {
        const newCase = await res.json();
        const id = newCase.id || newCase._id;
        router.push(`/cases/${id}`);
      }
    } catch (err) {
      console.error('Failed to promote to case:', err);
    } finally {
      setIsPromoting(false);
    }
  };

  if (messages.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center">
        {caseId && (
          <div className="mb-6 px-4 py-2 rounded-xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-700 dark:text-blue-300 flex items-center gap-3">
            <span>⚖️ Grounded in Case #{caseId} verified evidence</span>
            <Link href={`/cases/${caseId}`} className="font-semibold underline hover:no-underline">
              Return to Case Workspace →
            </Link>
          </div>
        )}
        <h1 className="text-2xl sm:text-3xl font-semibold text-foreground mb-5">
          {typingText}
        </h1>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex items-center max-w-3xl w-full gap-2"
        >
          <div className="rounded-xl flex w-full items-center bg-muted/50 border border-border p-1">
            <Input
              {...form.register('message')}
              className="focus-within:ring-0 ring-offset-transparent text-sm focus-visible:ring-0 bg-transparent rounded-lg focus-visible:ring-transparent px-4 py-3 border-none"
              placeholder="Ask about Indian law, women's rights, or any legal question…"
              autoComplete="off"
            />
            <Button
              className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-lg cursor-pointer"
              disabled={isThinking || !form.formState.isValid}
              type="submit"
            >
              <ArrowUp size={24} />
            </Button>
          </div>
        </form>
        <div className="mt-5 flex items-center gap-5">
          {promptSuggestions.map((prompt, index) => (
            <button
              key={index}
              type="button"
              suppressHydrationWarning
              onClick={() =>
                handlePromptClick(
                  typeof prompt === 'string' ? prompt : prompt.text
                )
              }
              className="flex items-center gap-2 border border-border rounded-full px-4 py-2 text-sm text-muted-foreground hover:text-foreground hover:border-primary/40 hover:bg-muted/30 transition-colors"
            >
              {typeof prompt !== 'string' && prompt.icon}
              {typeof prompt === 'string' ? prompt : prompt.text}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full items-center justify-center max-w-3xl w-full mx-auto pt-2">
      {/* Contextual Case Strip */}
      {caseId ? (
        <div className="w-full mb-3 px-4 py-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-700 dark:text-blue-300 flex items-center justify-between">
          <span>⚖️ Answers grounded in Case #{caseId} verified evidence</span>
          <Link href={`/cases/${caseId}`} className="font-semibold underline hover:no-underline">
            Return to Case Workspace →
          </Link>
        </div>
      ) : (
        <div className="w-full mb-2 px-3 py-2 border-b border-border flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Direct LawBot legal session</span>
          <button
            type="button"
            onClick={handlePromoteToCase}
            disabled={isPromoting}
            className="px-3 py-1 rounded-lg border border-primary/40 text-primary hover:bg-primary/10 transition-colors inline-flex items-center gap-1.5 font-medium disabled:opacity-50"
          >
            <Sparkles size={13} />
            <span>{isPromoting ? 'Creating case…' : 'Promote to Guided Case'}</span>
          </button>
        </div>
      )}

      <div className="w-full overflow-y-auto rounded-md custom-scrollbar ">
        <div className="flex flex-col gap-2 h-[75vh] overflow-y-auto custom-scrollbar p-4">
          {messages.length > 0 &&
            messages.map((message, index) => (
              <div
                key={index}
                className={`flex items-start gap-2 ${
                  message.isUser ? 'justify-end' : ''
                }`}
              >
                {!message.isUser && (
                  <Image
                    src={modelImage}
                    alt="Bot Avatar"
                    width={45}
                    height={45}
                    className="rounded-full"
                  />
                )}
                <div
                  className={`py-3 px-4 rounded-xl max-w-[70%] text-sm leading-relaxed ${
                    message.isUser
                      ? 'bg-primary text-primary-foreground self-end'
                      : 'bg-muted text-foreground self-start border border-border'
                  }`}
                >
                  {message.isUser ? (
                    message.text
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {message.text}
                    </ReactMarkdown>
                  )}
                </div>

                {message.isUser && user && (
                  <Image
                    src={user?.imageUrl || ''}
                    alt="User Avatar"
                    className="w-8 h-8 rounded-full"
                    width={32}
                    height={32}
                  />
                )}
                {message.isUser && !user && (
                  <div className="rounded-full border shadow-sm h-10 w-10 flex items-center justify-center ">
                    <h1 className="font-semibold">G</h1>
                  </div>
                )}
              </div>
            ))}

          {isThinking && (
            <div className="flex items-center space-x-4">
              <Skeleton className="h-12 w-12 rounded-full" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-[250px]" />
                <Skeleton className="h-4 w-[200px]" />
              </div>
            </div>
          )}
        </div>
      </div>
      {messages.length > 0 && (
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex items-center max-w-3xl w-full gap-2"
        >
          <div className="rounded-xl flex w-full items-center border bg-muted/50 border-border p-1">
            <Input
              {...form.register('message')}
              className="focus-within:ring-0 ring-offset-transparent text-sm bg-transparent focus-visible:ring-0 rounded-lg focus-visible:ring-transparent px-4 py-3 border-none"
              placeholder="Ask about Indian law, women's rights, or any legal question…"
              autoComplete="off"
            />
            <Button
              className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-lg cursor-pointer"
              disabled={isThinking || !form.formState.isValid}
              type="submit"
            >
              <ArrowUp size={24} />
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export default Page;
