'use client';

/**
 * Local stand-in for `@clerk/nextjs`, used only when no Clerk project is
 * configured so the app can be run and developed without one.
 *
 * Three things this deliberately does NOT do, because the previous version did
 * and each was a real exposure:
 *
 * 1. It does not sign anyone in automatically. Every visitor used to arrive
 *    already authenticated.
 * 2. It does not grant `isAdmin`. Every visitor used to be an admin, which
 *    opened `/dashboard` — the list of every community abuse report — to the
 *    public.
 * 3. It does not hand every browser the same user id. Identities are now
 *    per-browser, so two people developing locally do not share case files.
 *
 * None of this is a substitute for real authentication. Case ownership is
 * enforced by the backend session, not by anything in this file.
 */

import React, { createContext, useContext, useEffect, useState } from 'react';

type Metadata = Record<string, unknown> & { isAdmin?: boolean };

export interface MockUser {
  id: string;
  firstName: string;
  lastName: string;
  fullName: string;
  imageUrl?: string;
  emailAddresses: Array<{ emailAddress: string; id: string }>;
  unsafeMetadata: Metadata;
}

const STORAGE_KEY = 'herway.devUser';

function createLocalUser(): MockUser {
  // A per-browser id, so local sessions are distinguishable.
  const suffix =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);

  return {
    id: `devuser_${suffix}`,
    firstName: 'Local',
    lastName: 'User',
    fullName: 'Local User',
    imageUrl: '',
    emailAddresses: [{ emailAddress: `local-${suffix}@herway.invalid`, id: 'email_local' }],
    // No admin rights. Admin access requires a real, configured identity.
    unsafeMetadata: {},
  };
}

interface AuthContextType {
  user: MockUser | null;
  isSignedIn: boolean;
  isLoaded: boolean;
  signOut: () => Promise<void>;
  signIn: () => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isSignedIn: false,
  isLoaded: false,
  signOut: async () => {},
  signIn: () => {},
});

export function ClerkProvider({ children }: { children: React.ReactNode; [key: string]: unknown }) {
  const [user, setUser] = useState<MockUser | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    // Signed out by default; restore only an explicit previous local sign-in.
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) setUser(JSON.parse(stored) as MockUser);
    } catch {
      // Corrupt or unavailable storage: stay signed out.
    }
    setIsLoaded(true);
  }, []);

  const signIn = () => {
    const next = createLocalUser();
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Private browsing — the session simply will not persist.
    }
    setUser(next);
  };

  const signOut = async () => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Nothing to clean up.
    }
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{ user, isSignedIn: !!user, isLoaded, signOut, signIn }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useUser() {
  const { user, isLoaded, isSignedIn } = useContext(AuthContext);
  return { user, isLoaded, isSignedIn };
}

export function useClerk() {
  const { user, signOut, signIn } = useContext(AuthContext);
  return { user, signOut, openSignIn: signIn, openSignUp: signIn };
}

export function useAuth() {
  const { user, isLoaded, isSignedIn, signOut } = useContext(AuthContext);
  return {
    isLoaded,
    isSignedIn,
    userId: user?.id ?? null,
    sessionId: user ? `devsess_${user.id}` : null,
    // No token is minted: the backend treats these requests as anonymous
    // browser sessions, which is exactly what they are.
    getToken: async () => null,
    signOut,
  };
}

export function useSignIn() {
  const { signIn } = useContext(AuthContext);
  return {
    isLoaded: true,
    signIn: {
      authenticateWithRedirect: async () => {
        signIn();
        window.location.href = '/';
      },
      create: async () => {
        signIn();
      },
    },
  };
}

export function useSignUp() {
  const { signIn } = useContext(AuthContext);
  return {
    isLoaded: true,
    signUp: {
      create: async () => {
        signIn();
      },
      prepareVerification: async () => {},
      authenticateWithRedirect: async () => {
        signIn();
        window.location.href = '/';
      },
    },
  };
}

export function SignInButton({
  children,
  onClick,
  ...props
}: {
  children?: React.ReactNode;
  onClick?: () => void;
  [key: string]: unknown;
}) {
  const { signIn } = useContext(AuthContext);
  const handleClick = () => {
    onClick?.();
    signIn();
  };

  if (React.isValidElement(children)) {
    return React.cloneElement(
      children as React.ReactElement<{ onClick?: () => void }>,
      { onClick: handleClick },
    );
  }

  return (
    <button onClick={handleClick} {...props}>
      {children || 'Sign in'}
    </button>
  );
}

export function SignOutButton({
  children,
  onClick,
  ...props
}: {
  children?: React.ReactNode;
  onClick?: () => void;
  [key: string]: unknown;
}) {
  const { signOut } = useContext(AuthContext);
  const handleClick = () => {
    onClick?.();
    void signOut();
  };

  if (React.isValidElement(children)) {
    return React.cloneElement(
      children as React.ReactElement<{ onClick?: () => void }>,
      { onClick: handleClick },
    );
  }

  return (
    <button onClick={handleClick} {...props}>
      {children || 'Sign out'}
    </button>
  );
}

export function UserButton() {
  const { user } = useContext(AuthContext);
  if (!user) return null;
  return (
    <div className="flex items-center gap-2 px-2 py-1 bg-muted rounded-full text-xs font-semibold">
      <span>{user.firstName}</span>
    </div>
  );
}

export function AuthenticateWithRedirectCallback() {
  useEffect(() => {
    window.location.href = '/';
  }, []);
  return <div className="p-6 text-sm text-muted-foreground">Redirecting…</div>;
}
