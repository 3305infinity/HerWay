'use client';

import React, { createContext, useContext, useState } from 'react';

export interface MockUser {
  id: string;
  firstName: string;
  lastName: string;
  fullName: string;
  imageUrl?: string;
  emailAddresses: Array<{ emailAddress: string; id: string }>;
  unsafeMetadata: {
    isAdmin?: boolean;
    [key: string]: any;
  };
}

const defaultUser: MockUser = {
  id: 'user_haven_local_guest',
  firstName: 'Haven',
  lastName: 'User',
  fullName: 'Haven User',
  imageUrl: '',
  emailAddresses: [{ emailAddress: 'user@haven.local', id: 'email_1' }],
  unsafeMetadata: {
    isAdmin: true,
  },
};

interface AuthContextType {
  user: MockUser | null;
  isSignedIn: boolean;
  isLoaded: boolean;
  signOut: () => Promise<void>;
  setUser: (u: MockUser | null) => void;
}

const AuthContext = createContext<AuthContextType>({
  user: defaultUser,
  isSignedIn: true,
  isLoaded: true,
  signOut: async () => {},
  setUser: () => {},
});

export function ClerkProvider({
  children,
}: {
  children: React.ReactNode;
  [key: string]: any;
}) {
  const [user, setUser] = useState<MockUser | null>(defaultUser);

  const signOut = async () => {
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isSignedIn: !!user,
        isLoaded: true,
        signOut,
        setUser,
      }}
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
  const { user, signOut, setUser } = useContext(AuthContext);
  return {
    user,
    signOut,
    openSignIn: () => setUser(defaultUser),
    openSignUp: () => setUser(defaultUser),
  };
}

export function useAuth() {
  const { user, isLoaded, isSignedIn, signOut } = useContext(AuthContext);
  return {
    isLoaded,
    isSignedIn,
    userId: user?.id || null,
    sessionId: 'sess_local_dev',
    getToken: async () => 'mock_token',
    signOut,
  };
}

export function useSignIn() {
  const { setUser } = useContext(AuthContext);
  return {
    isLoaded: true,
    signIn: {
      authenticateWithRedirect: async () => {
        setUser(defaultUser);
        window.location.href = '/';
      },
      create: async () => {},
    },
  };
}

export function useSignUp() {
  const { setUser } = useContext(AuthContext);
  return {
    isLoaded: true,
    signUp: {
      create: async () => {},
      prepareVerification: async () => {},
      authenticateWithRedirect: async () => {
        setUser(defaultUser);
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
  [key: string]: any;
}) {
  const { setUser } = useContext(AuthContext);
  const handleClick = (e: React.MouseEvent) => {
    if (onClick) onClick();
    setUser(defaultUser);
  };

  if (React.isValidElement(children)) {
    return React.cloneElement(children as any, { onClick: handleClick });
  }

  return (
    <button onClick={handleClick} {...props}>
      {children || 'Sign In'}
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
  [key: string]: any;
}) {
  const { signOut } = useContext(AuthContext);
  const handleClick = (e: React.MouseEvent) => {
    if (onClick) onClick();
    signOut();
  };

  if (React.isValidElement(children)) {
    return React.cloneElement(children as any, { onClick: handleClick });
  }

  return (
    <button onClick={handleClick} {...props}>
      {children || 'Sign Out'}
    </button>
  );
}

export function UserButton(props: any) {
  const { user } = useContext(AuthContext);
  return (
    <div className="flex items-center gap-2 px-2 py-1 bg-muted rounded-full text-xs font-semibold">
      <span>👤 {user?.firstName || 'User'}</span>
    </div>
  );
}

export function AuthenticateWithRedirectCallback() {
  if (typeof window !== 'undefined') {
    window.location.href = '/';
  }
  return <div>Redirecting...</div>;
}
