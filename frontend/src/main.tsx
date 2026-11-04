import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
// Page styles load up front in the order the pages used to import them, so the global
// sheets below still override them while the page code itself is split into lazy chunks.
import './flowSql.css';
import './sankey.css';
import './temporal-institutions.css';
import './career-directory.css';
import './constellation.css';
import './topics.css';
import './styles.css';
import './redesign.css';
import './theme.css';
import './flat.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
);
