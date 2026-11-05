import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.jsx';
import '@fontsource-variable/geist/latin.css';
import './styles.css';
import './clean-layout.css';
import './engineering.css';
import './workspace.css';
import './chat/workspace.css';
import './part/workspace.css';

createRoot(document.getElementById('root')).render(<App />);
