import { NextResponse } from 'next/server';
import { clerkMiddleware } from '@clerk/nextjs/server';

const pubKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
const isValidClerkKey =
  typeof pubKey === 'string' &&
  (pubKey.startsWith('pk_test_') || pubKey.startsWith('pk_live_')) &&
  !pubKey.includes('your_');

export default isValidClerkKey
  ? clerkMiddleware()
  : () => NextResponse.next();

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
};
