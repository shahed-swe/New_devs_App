// Applies user profile/preference settings (theme, language, compact view,
// auto refresh) to the running app. Values are mirrored to localStorage so
// they can be re-applied instantly on startup, before the profile API loads.

import i18n from '../i18n';

export const applyTheme = (theme: string): void => {
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  const dark = theme === 'dark' || (theme === 'auto' && prefersDark);
  document.documentElement.classList.toggle('dark', dark);
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  localStorage.setItem('appTheme', theme);
};

export const applyLanguage = (language: string): void => {
  if (!language) return;
  if (i18n.language !== language) {
    i18n.changeLanguage(language);
  }
  document.documentElement.lang = language;
  document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
  localStorage.setItem('appLanguage', language);
};

export const applyCompactView = (enabled: boolean): void => {
  document.documentElement.classList.toggle('compact', enabled);
  localStorage.setItem('compactView', String(enabled));
};

export const applyAutoRefresh = (enabled: boolean): void => {
  localStorage.setItem('autoRefresh', String(enabled));
  window.dispatchEvent(new CustomEvent('auto-refresh-changed', { detail: enabled }));
};

export const isAutoRefreshEnabled = (): boolean =>
  localStorage.getItem('autoRefresh') !== 'false'; // defaults to on

// Re-apply persisted settings on startup (before the profile API responds)
export const initUiPreferences = (): void => {
  applyTheme(localStorage.getItem('appTheme') || 'light');

  const language = localStorage.getItem('appLanguage');
  if (language) {
    applyLanguage(language);
  }

  applyCompactView(localStorage.getItem('compactView') === 'true');

  // Follow OS theme changes while in "auto" mode
  window
    .matchMedia?.('(prefers-color-scheme: dark)')
    .addEventListener('change', () => {
      if (localStorage.getItem('appTheme') === 'auto') {
        applyTheme('auto');
      }
    });
};
