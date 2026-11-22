import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './app/App';
import './styles/workbench.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('未找到工作台挂载节点');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
);
