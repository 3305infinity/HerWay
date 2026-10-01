import type { NextConfig } from 'next';
import path from 'path';
import { describeClerkFallback, getClerkKeyStatus } from './src/lib/clerk-config';

/** A real Clerk project is configured for this build. */
const clerkStatus = getClerkKeyStatus();
const hasRealClerkKeys = clerkStatus.configured;

const isProductionDeploy = process.env.HERWAY_ENV === 'production';

/**
 * Without Clerk keys the app falls back to local auth stand-ins so it can be
 * developed offline. That fallback must never reach a production deploy: it
 * would ship an app with no real authentication at all. Opt out knowingly with
 * `HERWAY_ALLOW_AUTH_FALLBACK=true` if you genuinely want an anonymous-only
 * deployment.
 */
if (isProductionDeploy && !hasRealClerkKeys && process.env.HERWAY_ALLOW_AUTH_FALLBACK !== 'true') {
  throw new Error(
    'Refusing to build for production without usable Clerk credentials.\n' +
      `Reason: ${clerkStatus.detail ?? 'Clerk is not configured.'}\n` +
      'Set NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY, or set\n' +
      'HERWAY_ALLOW_AUTH_FALLBACK=true to deploy deliberately without accounts.',
  );
}

if (!hasRealClerkKeys) {
  console.warn(describeClerkFallback(clerkStatus));
}

const nextConfig: NextConfig = {
  images: {
    // Only the hosts we actually render images from. The previous wildcard
    // (`hostname: '**'`) let any URL in a model response be proxied through
    // the image optimiser.
    remotePatterns: [
      { protocol: 'https', hostname: '**.s3.amazonaws.com' },
      { protocol: 'https', hostname: '**.s3.*.amazonaws.com' },
      { protocol: 'https', hostname: 'images.pexels.com' },
    ],
  },
  webpack: (config) => {
    if (!hasRealClerkKeys) {
      config.resolve.alias = {
        ...config.resolve.alias,
        '@clerk/nextjs/server': path.resolve(__dirname, 'src/lib/clerk-mock-server.ts'),
        '@clerk/nextjs': path.resolve(__dirname, 'src/lib/clerk-mock.tsx'),
      };
    }
    return config;
  },
};

export default nextConfig;
