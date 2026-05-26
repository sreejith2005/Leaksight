import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { setToken, clearToken, getToken } from '../api/client';
import type { CurrentUser } from '../types/api';

interface AuthContextValue {
  currentUser: CurrentUser | null;
  isAuthenticated: boolean;
  login: (token: string, user: CurrentUser) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1]));
    return payload;
  } catch {
    return null;
  }
}

function extractUserFromToken(token: string): CurrentUser | null {
  const payload = parseJwtPayload(token);
  if (!payload) return null;

  const exp = payload.exp as number | undefined;
  if (exp && Date.now() / 1000 > exp) {
    return null; // Token expired
  }

  return {
    user_id: payload.sub as string,
    tenant_id: payload.tenant_id as string,
    email: payload.email as string,
    role: (payload.role as string) || 'REVIEWER',
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(() => {
    const token = getToken();
    if (!token) return null;
    return extractUserFromToken(token);
  });

  // Check token expiry on mount and set interval
  useEffect(() => {
    const token = getToken();
    if (token) {
      const user = extractUserFromToken(token);
      if (!user) {
        clearToken();
        setCurrentUser(null);
      }
    }
  }, []);

  const loginFn = useCallback((token: string, user: CurrentUser) => {
    setToken(token);
    setCurrentUser(user);
  }, []);

  const logoutFn = useCallback(() => {
    clearToken();
    setCurrentUser(null);
    window.location.href = '/login';
  }, []);

  const value: AuthContextValue = {
    currentUser,
    isAuthenticated: currentUser !== null,
    login: loginFn,
    logout: logoutFn,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
