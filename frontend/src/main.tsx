import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import './styles/datepicker.css';
import './i18n'; // Import i18n configuration
import { initUiPreferences } from './lib/uiPreferences';

// Apply persisted theme/language/compact-view before first render
initUiPreferences();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);