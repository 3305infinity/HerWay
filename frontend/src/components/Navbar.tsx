'use client';
import Link from 'next/link';
import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
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

  /**
   * Four top-level destinations, not eight.
   *
   * Eight peers meant a first-time visitor had to read and rank every one
   * before choosing, and "LawBot" / "Talk to Niva" / "Discreet message" are
   * product names that say nothing to someone who has never been here. The
   * four below are the places you go; the named tools live under "Support",
   * described by what they do rather than what they are called.
   */
  const navLinks = [
    { href: '/', label: 'Home' },
    { href: '/safety-center', label: 'Safety Center' },
    { href: '/cases', label: 'My Cases' },
    { href: '/community', label: 'Community' },
  ];

  const supportLinks = [
    { href: '/lawbot', label: 'LawBot', hint: 'Your legal rights and options' },
    { href: '/therapybot', label: 'Talk to Niva', hint: 'Someone to talk to, any time' },
    { href: '/discover', label: 'Find places', hint: 'Services and help near you' },
    { href: '/discreet-message', label: 'Discreet message', hint: 'Hide a message in a photo' },
    { href: '/how-it-works', label: 'How it works', hint: 'The pipeline, the sources, the limits' },
  ];

  const supportActive = supportLinks.some((link) => pathname === link.href);

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

      {/* Primary nav links — desktop.
          The active pill is a single shared element (`layoutId`), so moving
          between routes slides it across rather than blinking it out and in.
          That continuity is what tells you the nav is one object. */}
      <div className="hidden md:flex items-center gap-1" role="list">
        {navLinks.map((link) => {
          const active = isActive(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              role="listitem"
              aria-current={active ? 'page' : undefined}
              className={`relative px-3 py-1.5 rounded-md text-sm transition-colors duration-150 ${
                active
                  ? 'text-primary font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {active && (
                <motion.span
                  layoutId="nav-active-pill"
                  className="absolute inset-0 -z-10 rounded-md bg-primary/10"
                  transition={{ duration: 0.28, ease: [0.22, 0.61, 0.36, 1] }}
                />
              )}
              {link.label}
            </Link>
          );
        })}

        {/* Support menu — the four named tools, each with a line saying what it
            actually does. CSS-only disclosure (group-hover + focus-within), so
            it works without JS and stays keyboard reachable. */}
        <div className="group relative">
          <button
            type="button"
            aria-haspopup="true"
            aria-expanded={supportActive}
            className={`flex items-center gap-1 rounded-md px-3 py-1.5 text-sm transition-colors duration-150 ${
              supportActive
                ? 'font-semibold text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Support
            <span
              aria-hidden
              className="text-[10px] transition-transform duration-200 group-hover:rotate-180 group-focus-within:rotate-180"
            >
              ▾
            </span>
          </button>

          <div className="invisible absolute right-0 top-full z-50 w-72 translate-y-1 pt-2 opacity-0 transition-all duration-200 group-hover:visible group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100">
            <div className="elevate-2 overflow-hidden rounded-xl border border-border/80 bg-popover">
              {supportLinks.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`block border-b border-border/50 px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/60 ${
                    pathname === item.href ? 'bg-primary/[0.07]' : ''
                  }`}
                >
                  <span
                    className={`block text-sm font-medium ${
                      pathname === item.href ? 'text-primary' : 'text-foreground'
                    }`}
                  >
                    {item.label}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {item.hint}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Right side actions */}
      <div className="flex items-center gap-2">
        {/* Quick exit — discreet by design, still always present. */}
        <div className="relative group">
          <button
            suppressHydrationWarning
            onClick={handleQuickExit}
            aria-label="Leave this page immediately (also press Escape)"
            title="Leave this page immediately. Press Escape at any time."
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {/* Icon only.
                This was a filled rose button reading "✕ Exit (ESC)" — the
                loudest element in the header, which made the whole product
                look like a warning rather than a tool.

                The capability is unchanged: this still leaves immediately, and
                Escape still works from anywhere. What changed is that it no
                longer announces itself — which is also closer to the point of
                a discreet exit. It is described for screen readers and on
                /privacy, where its real limits are stated. */}
            <svg
              width="15"
              height="15"
              viewBox="0 0 15 15"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M9 2H12.5V12.5H9" />
              <path d="M6.5 10.5L9.5 7.5L6.5 4.5" />
              <path d="M9.5 7.5H2" />
            </svg>
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
      {/* Mobile menu.
          Height animation rather than a slide-over: the panel grows out of the
          bar it belongs to, which reads as the same object opening instead of
          a new surface flying in over the page. Links settle in order so the
          eye can follow them down. */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
            className="absolute top-14 left-0 right-0 overflow-hidden border-b border-border bg-background/95 shadow-md backdrop-blur-sm md:hidden z-50"
            role="navigation"
            aria-label="Mobile navigation"
          >
            <div className="space-y-1 p-4">
              {[...navLinks, ...supportLinks].map((link, index) => (
                <motion.div
                  key={link.href}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.04 + index * 0.035, duration: 0.2 }}
                >
                  <Link
                    href={link.href}
                    onClick={() => setMobileOpen(false)}
                    aria-current={isActive(link.href) ? 'page' : undefined}
                    className={`block rounded-md px-3 py-2.5 text-sm transition-colors ${
                      isActive(link.href)
                        ? 'bg-primary/10 font-semibold text-primary'
                        : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                    }`}
                  >
                    {link.label}
                  </Link>
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </nav>
  );
}

export default Navbar;
