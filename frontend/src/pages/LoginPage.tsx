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
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'var(--color-black)',
        padding: 'var(--space-4)',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 400,
          backgroundColor: 'var(--color-prussian-blue)',
          borderRadius: 'var(--radius-lg)',
          padding: 'var(--space-8)',
          border: '1px solid var(--color-border)',
        }}
      >
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 'var(--space-8)' }}>
          <span
            style={{
              fontSize: '28px',
              fontWeight: 700,
              color: 'var(--color-orange)',
              letterSpacing: '-0.02em',
            }}
          >
            LeakSight
          </span>
          <p style={{ fontSize: '14px', color: 'var(--color-muted)', marginTop: 'var(--space-2)' }}>
            Enterprise Commercial Intelligence
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Email */}
          <div style={{ marginBottom: 'var(--space-4)' }}>
            <label
              style={{
                display: 'block',
                fontSize: '12px',
                color: 'var(--color-muted)',
                textTransform: 'uppercase',
                marginBottom: 'var(--space-1)',
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
                backgroundColor: 'var(--color-black)',
                color: 'var(--color-grey)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-3)',
                fontSize: '14px',
                outline: 'none',
              }}
              onFocus={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--color-orange)';
              }}
              onBlur={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--color-border)';
              }}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: 'var(--space-6)' }}>
            <label
              style={{
                display: 'block',
                fontSize: '12px',
                color: 'var(--color-muted)',
                textTransform: 'uppercase',
                marginBottom: 'var(--space-1)',
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
                backgroundColor: 'var(--color-black)',
                color: 'var(--color-grey)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-3)',
                fontSize: '14px',
                outline: 'none',
              }}
              onFocus={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--color-orange)';
              }}
              onBlur={(e) => {
                (e.target as HTMLElement).style.borderColor = 'var(--color-border)';
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
