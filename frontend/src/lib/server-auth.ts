import 'server-only';

import { isClerkConfigured as isConfigured } from './clerk-config';

/**
 * Re-exported so callers that already depend on this module keep working.
 * The implementation lives in `clerk-config` because `next.config.ts` and the
 * Edge middleware need it too, and neither can import a `server-only` module.
 */
export { isClerkConfigured } from './clerk-config';

/**
 * Server-side access to the Clerk session token.
 *
 * Isolated here so the API proxy can attach a verified token without the value
 * ever being handed to client JavaScript, and so the build does not hard-fail
 * when Clerk is not configured (a developer running the stack locally still
 * gets a working, anonymous session).
 */
export async function getServerAuthToken(): Promise<string | null> {
  if (!isConfigured()) return null;

  try {
    // Imported lazily: when Clerk is not configured this module is aliased to
    // the local stand-in, and we do not want to pull it in at all.
    const { auth } = await import('@clerk/nextjs/server');
    const session = await auth();
    const token = await session?.getToken?.();
    return token ?? null;
  } catch (error) {
    console.warn('Could not read the Clerk session token:', error);
    return null;
  }
}
