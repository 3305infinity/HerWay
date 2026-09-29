import { NextResponse } from 'next/server';

export function clerkMiddleware() {
  return () => NextResponse.next();
}

export async function currentUser() {
  return {
    id: 'user_haven_local_admin',
    firstName: 'Admin',
    lastName: 'User',
    fullName: 'Admin User',
    emailAddresses: [{ emailAddress: 'admin@haven.local', id: 'email_admin' }],
    unsafeMetadata: {
      isAdmin: true,
    },
  };
}

export function auth() {
  return {
    userId: 'user_haven_local_admin',
    sessionId: 'sess_local_dev',
    getToken: async () => 'mock_token',
  };
}
