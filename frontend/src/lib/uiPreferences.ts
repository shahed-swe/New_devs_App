// Applies user profile settings (theme) to the running app. Values are
// mirrored to localStorage so they can be re-applied instantly on startup,
// before the profile API loads.

export const applyTheme = (theme: string): void => {
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  const dark = theme === 'dark' || (theme === 'auto' && prefersDark);
  document.documentElement.classList.toggle('dark', dark);
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  localStorage.setItem('appTheme', theme);
};

// Re-apply persisted settings on startup (before the profile API responds)
export const initUiPreferences = (): void => {
  applyTheme(localStorage.getItem('appTheme') || 'light');

  // Follow OS theme changes while in "auto" mode
  window
    .matchMedia?.('(prefers-color-scheme: dark)')
    .addEventListener('change', () => {
      if (localStorage.getItem('appTheme') === 'auto') {
        applyTheme('auto');
      }
    });
};
