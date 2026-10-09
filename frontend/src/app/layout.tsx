import type { Metadata } from 'next';
import './globals.css';
import { Inter, Playfair_Display } from 'next/font/google';
import { ClerkProvider } from '@clerk/nextjs';
import Navbar from '@/components/Navbar';
import Atmosphere from '@/components/Atmosphere';
import ServiceWorkerRegistrar from '@/components/ServiceWorkerRegistrar';
import MotionProvider from '@/components/MotionProvider';
import { ThemeProvider } from '@/components/theme-provider';
import { Toaster } from 'react-hot-toast';

export const metadata: Metadata = {
  title: 'HerWay — A safe place to figure out what comes next',
  description:
    'HerWay helps women navigate unsafe situations, find verified support resources, and build personalized safety plans.',
};

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
});

const playfair = Playfair_Display({
  subsets: ['latin'],
  variable: '--font-serif',
  display: 'swap',
});

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider dynamic>
      <html lang="en" suppressHydrationWarning>
        <body
          className={`${inter.variable} ${playfair.variable} font-sans antialiased`}
          suppressHydrationWarning
        >
          <ThemeProvider
            attribute="class"
            defaultTheme="dark"
            enableSystem
            disableTransitionOnChange
          >
            {/* The signature layer — see Atmosphere.tsx. Mounted once here so
                every page sits on the same surface. */}
            <Atmosphere />
            <ServiceWorkerRegistrar />
            <MotionProvider>
              <div className="min-h-screen flex flex-col">
                <Navbar />
                <main className="flex flex-1 flex-col">{children}</main>
              </div>
            </MotionProvider>
            <Toaster
              toastOptions={{
                style: {
                  borderRadius: '8px',
                  fontSize: '13px',
                },
              }}
            />
          </ThemeProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
