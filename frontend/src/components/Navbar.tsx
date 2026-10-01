'use client';
import Link from 'next/link';
import React from 'react';
import { LoginDropdown } from './LoginDropdown';
import { ModeToggle } from './ModeToggle';
import SignOut from './SignOut';
import { usePathname } from 'next/navigation';
import { useClerk } from '@clerk/nextjs';

function Navbar() {
  const pathname = usePathname();
  const { user } = useClerk();
  const [mounted, setMounted] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  const isActive = (href: string) => pathname === href;

  // Discreet Quick Exit — redirects away immediately
  const handleQuickExit = () => {
    window.location.replace('https://www.google.com');
  };

  React.useEffect(() => {
    setMounted(true);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleQuickExit();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const navLinks = [
    { href: '/', label: 'Home' },
    { href: '/cases', label: 'My Cases' },
    { href: '/lawbot', label: 'LawBot' },
    { href: '/therapybot', label: 'Talk to Niva' },
    { href: '/community', label: 'Community' },
    { href: '/discreet-message', label: 'Discreet message' },
  ];

  return (
    <nav
      className="w-full h-14 px-4 sm:px-6 flex items-center justify-between border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 sticky top-0 z-50"
      aria-label="Main navigation"
    >
      {/* Wordmark */}
      <Link
        href="/"
        className="font-semibold text-lg text-foreground hover:text-primary transition-colors flex items-center gap-2 shrink-0"
        aria-label="HerWay — go to homepage"
      >
        <span
          className="w-7 h-7 rounded-md bg-primary flex items-center justify-center text-primary-foreground font-bold text-xs"
          aria-hidden="true"
        >
          HW
        </span>
        HerWay
      </Link>

      {/* Primary nav links — desktop */}
      <div className="hidden md:flex items-center gap-1" role="list">
        {navLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            role="listitem"
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
              isActive(link.href)
                ? 'text-primary font-semibold bg-primary/8'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
            }`}
          >
            {link.label}
          </Link>
        ))}
      </div>

      {/* Right side actions */}
      <div className="flex items-center gap-2">
        {/* Quick Exit — always visible, safety critical */}
        <div className="relative group">
          <button
            suppressHydrationWarning
            onClick={handleQuickExit}
            aria-label="Quick exit — leave this page immediately (also press Escape)"
            title="Leave this page immediately. Press Escape at any time."
            className="px-3 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold text-xs rounded-md transition-colors flex items-center gap-1.5"
          >
            <span aria-hidden="true">✕</span>
            <span>Exit</span>
            <span className="hidden sm:inline text-[10px] opacity-70 font-normal">(ESC)</span>
          </button>
          {/* Tooltip */}
          <div
            className="absolute right-0 top-full mt-2 hidden group-hover:block w-52 p-3 bg-popover text-popover-foreground border border-border rounded-lg text-xs shadow-lg z-50 leading-relaxed"
            role="tooltip"
          >
            Redirects to Google immediately. Your browser history may still show this page.
          </div>
        </div>

        <ModeToggle />

        {mounted ? (
          !user ? <LoginDropdown /> : <SignOut />
        ) : (
          <div className="w-16 h-8" aria-hidden="true" />
        )}

        {/* Mobile hamburger */}
        <button
          suppressHydrationWarning
          className="md:hidden p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={mobileOpen}
        >
          <span className="block w-5 h-0.5 bg-current mb-1 transition-all" />
          <span className="block w-5 h-0.5 bg-current mb-1 transition-all" />
          <span className="block w-5 h-0.5 bg-current transition-all" />
        </button>
      </div>

      {/* Mobile nav dropdown */}
      {mobileOpen && (
        <div
          className="absolute top-14 left-0 right-0 bg-background border-b border-border shadow-md p-4 space-y-1 md:hidden z-50"
          role="navigation"
          aria-label="Mobile navigation"
        >
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setMobileOpen(false)}
              className={`block px-3 py-2.5 rounded-md text-sm transition-colors ${
                isActive(link.href)
                  ? 'text-primary font-semibold bg-primary/8'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>
      )}
    </nav>
  );
}

export default Navbar;
