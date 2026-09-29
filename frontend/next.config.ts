import type { NextConfig } from 'next';
import path from 'path';

const pubKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY || '';
// Check if user provided an actual live/test Clerk project key (not a dummy placeholder)
const isLiveClerkKey =
  pubKey.startsWith('pk_live_') ||
  (pubKey.startsWith('pk_test_') &&
    pubKey.length > 50 &&
    !pubKey.includes('haven-dev') &&
    !pubKey.includes('example') &&
    !pubKey.includes('your_'));

const nextConfig: NextConfig = {
  images: {
    domains: [],
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**',
        port: '',
        pathname: '/**',
      },
    ],
  },
  webpack: (config) => {
    if (!isLiveClerkKey) {
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
