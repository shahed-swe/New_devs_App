// Applies user profile settings (theme, language) to the running app. Values
// are mirrored to localStorage so they can be re-applied instantly on
// startup, before the profile API loads.

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

// Re-apply persisted settings on startup (before the profile API responds)
export const initUiPreferences = (): void => {
  applyTheme(localStorage.getItem('appTheme') || 'light');

  const language = localStorage.getItem('appLanguage');
  if (language) {
    applyLanguage(language);
  }

  // Follow OS theme changes while in "auto" mode
  window
    .matchMedia?.('(prefers-color-scheme: dark)')
    .addEventListener('change', () => {
      if (localStorage.getItem('appTheme') === 'auto') {
        applyTheme('auto');
      }
    });
};
