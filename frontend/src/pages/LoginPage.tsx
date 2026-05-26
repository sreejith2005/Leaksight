import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { login as loginApi } from '../api/endpoints/auth';
import { useAuth } from '../context/AuthContext';
import { Button } from '../components/ui/Button';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import type { CurrentUser } from '../types/api';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  // Redirect if already logged in
  React.useEffect(() => {
    if (isAuthenticated) navigate('/', { replace: true });
  }, [isAuthenticated, navigate]);

  const loginMutation = useMutation({
    mutationFn: () => loginApi({ email, password }),
    onSuccess: (data) => {
      const user: CurrentUser = {
        user_id: data.user.id,
        tenant_id: data.user.tenant_id,
        email: data.user.email,
        role: data.user.role,
        tenant_name: data.user.tenant_name,
      };
      login(data.access_token, user);
      navigate('/', { replace: true });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loginMutation.mutate();
  };

  return (
    <div
      className="noise-overlay"
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'var(--bg-base)',
        padding: 'var(--space-4)',
      }}
    >
      <div
        className="animate-fadeIn"
        style={{
          width: '100%',
          maxWidth: 420,
          backgroundColor: 'var(--bg-surface-1)',
          borderRadius: 'var(--radius-xl)',
          padding: 'var(--space-10) var(--space-8)',
          border: '1px solid var(--border-subtle)',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 'var(--space-10)' }}>
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'var(--text-3xl)',
              fontWeight: 700,
              fontStyle: 'italic',
              color: 'var(--accent)',
              letterSpacing: '-0.02em',
            }}
          >
            LeakSight
          </span>
          <div
            style={{
              width: 40,
              height: 1,
              background: 'linear-gradient(90deg, transparent, var(--accent), transparent)',
              margin: 'var(--space-3) auto',
              opacity: 0.5,
            }}
          />
          <p
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
            }}
          >
            Enterprise Commercial Intelligence
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Email */}
          <div style={{ marginBottom: 'var(--space-5)' }}>
            <label
              style={{
                display: 'block',
                fontFamily: 'var(--font-body)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                marginBottom: 'var(--space-2)',
              }}
            >
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              required
              autoComplete="email"
              style={{
                width: '100%',
                backgroundColor: 'var(--bg-base)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-md)',
                padding: 'var(--space-3) var(--space-4)',
                fontFamily: 'var(--font-body)',
                fontSize: 'var(--text-sm)',
                outline: 'none',
                transition: 'border-color 200ms ease',
              }}
              onFocus={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--accent)';
                (e.target as HTMLElement).style.boxShadow = '0 0 0 3px var(--accent-dim)';
              }}
              onBlur={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--border-default)';
                (e.target as HTMLElement).style.boxShadow = 'none';
              }}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: 'var(--space-8)' }}>
            <label
              style={{
                display: 'block',
                fontFamily: 'var(--font-body)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                marginBottom: 'var(--space-2)',
              }}
            >
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
              autoComplete="current-password"
              style={{
                width: '100%',
                backgroundColor: 'var(--bg-base)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-md)',
                padding: 'var(--space-3) var(--space-4)',
                fontFamily: 'var(--font-body)',
                fontSize: 'var(--text-sm)',
                outline: 'none',
                transition: 'border-color 200ms ease',
              }}
              onFocus={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--accent)';
                (e.target as HTMLElement).style.boxShadow = '0 0 0 3px var(--accent-dim)';
              }}
              onBlur={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--border-default)';
                (e.target as HTMLElement).style.boxShadow = 'none';
              }}
            />
          </div>

          {/* Error */}
          {loginMutation.isError && (
            <div style={{ marginBottom: 'var(--space-4)' }}>
              <ErrorMessage message={(loginMutation.error as Error).message || 'Login failed'} />
            </div>
          )}

          <Button
            type="submit"
            fullWidth
            loading={loginMutation.isPending}
            disabled={!email || !password}
          >
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
