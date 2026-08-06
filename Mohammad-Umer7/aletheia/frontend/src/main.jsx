import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles/tokens.css'
import './styles/app.css'

// No StrictMode: react-force-graph's imperative canvas + double-mounted dev
// effects fight each other (flicker, duplicated simulations).
createRoot(document.getElementById('root')).render(<App />)
