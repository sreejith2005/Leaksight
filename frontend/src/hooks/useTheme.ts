import { useState, useCallback } from 'react';

type Theme = 'light' | 'dark';

const STORAGE_KEY = 'leaksight-theme';

function getInitialTheme(): Theme {
  // The inline <script> in index.html already set data-theme on <html>
  // before React loaded. Read back whatever it resolved to.
  const attr = document.documentElement.getAttribute('data-theme');
  if (attr === 'dark' || attr === 'light') return attr;
  return 'light';
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem(STORAGE_KEY, next);
      return next;
    });
  }, []);

  return { theme, toggleTheme } as const;
}
