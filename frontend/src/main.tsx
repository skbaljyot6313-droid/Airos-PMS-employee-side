import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import {perfMarkOnce} from './utils/perf';

perfMarkOnce('t2_webview');
createRoot(document.getElementById('root')!).render(<App />);
