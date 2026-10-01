/**
 * The single source of truth for "do we have a usable Clerk project?".
 *
 * This is imported by `next.config.ts` (to decide whether to alias the Clerk
 * SDK to the local stand-ins), by `middleware.ts`, and by `server-auth.ts`.
 * Those three used to each re-implement the check slightly differently, which
 * meant they could disagree — and all three accepted a key that merely *looked*
 * like a Clerk key.
 *
 * A publishable key is `pk_test_` / `pk_live_` followed by the base64 of the
 * instance's Frontend API host with a trailing `$`. Nothing stops someone
 * writing a syntactically perfect key for an instance that does not exist; when
 * that happens Clerk answers every request with
 *
 *     {"errors":[{"message":"Invalid host","code":"host_invalid", ...}]}
 *
 * which surfaces to the user as a broken page rather than as a configuration
 * error. We cannot prove a key is real without calling Clerk, but we can reject
 * the shapes that are definitely not, and fall back to anonymous sessions with
 * an explanation instead of shipping a site that 500s on every route.
 *
 * Deliberately dependency-free (no `server-only`, no Node built-ins) so it can
 * be loaded from the Next config, the Edge middleware runtime and the Node
 * server alike.
 */

export type ClerkKeyProblem =
  | 'missing-publishable-key'
  | 'missing-secret-key'
  | 'placeholder-publishable-key'
  | 'placeholder-secret-key'
  | 'malformed-publishable-key'
  | 'unregistered-instance-host';

export interface ClerkKeyStatus {
  /** True when the keys are usable and the real Clerk SDK should be loaded. */
  configured: boolean;
  problem?: ClerkKeyProblem;
  /** A sentence a developer can act on. Safe to log; contains no secrets. */
  detail?: string;
  /** The Frontend API host the publishable key points at, when decodable. */
  frontendApiHost?: string;
}

/**
 * Substrings that only ever appear in a key someone typed by hand. Checked
 * case-insensitively against both keys.
 */
const PLACEHOLDER_MARKERS = [
  'your_',
  'yourkey',
  'example',
  'mock',
  'placeholder',
  'changeme',
  'change_me',
  'dummy',
  'fake',
  'sample',
  'replace',
  'xxxx',
  '...',
];

function placeholderMarkerIn(value: string): string | null {
  const haystack = value.toLowerCase();
  return PLACEHOLDER_MARKERS.find((marker) => haystack.includes(marker)) ?? null;
}

/** Decode the Frontend API host out of a publishable key, or null if it is not valid. */
export function decodeFrontendApiHost(publishableKey: string): string | null {
  const body = publishableKey.replace(/^pk_(test|live)_/, '');
  if (body === publishableKey) return null;

  let decoded: string;
  try {
    // `atob` exists on the Edge runtime and in Node >= 16; `Buffer` does not
    // exist on Edge, so it cannot be used here.
    decoded = atob(body);
  } catch {
    return null;
  }

  // Clerk appends a `$` terminator to the host before encoding.
  if (!decoded.endsWith('$')) return null;
  const host = decoded.slice(0, -1);

  // A bare word is not a host. Require at least one dot and no whitespace.
  if (!/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(host)) return null;
  return host;
}

/**
 * Clerk names every development instance `<word>-<word>-<digits>.clerk.accounts.dev`
 * (for example `wandering-mallard-42.clerk.accounts.dev`). A `pk_test_` key
 * pointing at a hand-written subdomain such as `haven-dev.clerk.accounts.dev`
 * is therefore an instance that does not exist, and Clerk will reject it.
 *
 * Production keys use whatever custom domain the project configured, so this
 * shape check applies to `pk_test_` only. Set `HERWAY_TRUST_CLERK_KEYS=true` to
 * skip it if Clerk ever changes the naming scheme.
 */
function isImplausibleDevHost(publishableKey: string, host: string): boolean {
  if (!publishableKey.startsWith('pk_test_')) return false;
  if (!host.endsWith('.clerk.accounts.dev')) return false;
  const slug = host.slice(0, -'.clerk.accounts.dev'.length);
  return !/-\d+$/.test(slug);
}

/**
 * Inspect the Clerk credentials in the given environment.
 *
 * Reads `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` and
 * `HERWAY_TRUST_CLERK_KEYS` from `env`, which defaults to `process.env`.
 */
export function getClerkKeyStatus(
  env: Record<string, string | undefined> = process.env,
): ClerkKeyStatus {
  const publishableKey = (env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? '').trim();
  const secretKey = (env.CLERK_SECRET_KEY ?? '').trim();

  if (!publishableKey) {
    return {
      configured: false,
      problem: 'missing-publishable-key',
      detail: 'NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is not set.',
    };
  }

  const publishableMarker = placeholderMarkerIn(publishableKey);
  if (publishableMarker) {
    return {
      configured: false,
      problem: 'placeholder-publishable-key',
      detail:
        `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY contains "${publishableMarker}", ` +
        'so it is a placeholder rather than a key from a Clerk project.',
    };
  }

  const frontendApiHost = decodeFrontendApiHost(publishableKey);
  if (!frontendApiHost) {
    return {
      configured: false,
      problem: 'malformed-publishable-key',
      detail:
        'NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is not a Clerk publishable key. It must ' +
        'start with pk_test_ or pk_live_ followed by the base64 of your Frontend API host.',
    };
  }

  if (!secretKey) {
    return {
      configured: false,
      problem: 'missing-secret-key',
      detail: 'CLERK_SECRET_KEY is not set, so the server cannot verify sessions.',
      frontendApiHost,
    };
  }

  const secretMarker = placeholderMarkerIn(secretKey);
  if (secretMarker) {
    return {
      configured: false,
      problem: 'placeholder-secret-key',
      detail:
        `CLERK_SECRET_KEY contains "${secretMarker}", so it is a placeholder ` +
        'rather than a key from a Clerk project.',
      frontendApiHost,
    };
  }

  const trustKeys = (env.HERWAY_TRUST_CLERK_KEYS ?? '').toLowerCase() === 'true';
  if (!trustKeys && isImplausibleDevHost(publishableKey, frontendApiHost)) {
    return {
      configured: false,
      problem: 'unregistered-instance-host',
      detail:
        `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY decodes to "${frontendApiHost}", which is ` +
        'not the shape Clerk gives development instances (they end in -<number>, ' +
        'for example wandering-mallard-42.clerk.accounts.dev). Clerk would answer ' +
        '"Invalid host" for this key. Copy the key from your Clerk dashboard, or set ' +
        'HERWAY_TRUST_CLERK_KEYS=true if you are certain this one is real.',
      frontendApiHost,
    };
  }

  return { configured: true, frontendApiHost };
}

/** True when a real Clerk project is configured for this deployment. */
export function isClerkConfigured(
  env: Record<string, string | undefined> = process.env,
): boolean {
  return getClerkKeyStatus(env).configured;
}

/**
 * The warning shown at build and at startup when Clerk is unusable. Explains
 * what is wrong and what the app does instead, so a misconfiguration is not
 * mistaken for the app being broken.
 */
export function describeClerkFallback(status: ClerkKeyStatus): string {
  const reason = status.detail ?? 'Clerk is not configured.';
  return (
    '\n[HerWay] Signing in with an account is disabled.\n' +
    `         ${reason}\n` +
    '         Visitors will be signed out by default and treated as isolated\n' +
    '         anonymous browser sessions by the backend. Cases still work, but\n' +
    '         they do not follow a user across devices. Do not use this for real\n' +
    '         users. See .env.example for how to set the keys.\n'
  );
}
