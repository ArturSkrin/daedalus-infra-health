import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Ops from './Ops.tsx'

// /ops is the admin screen; everything else is the overview. nginx serves index.html for both.
const admin = window.location.pathname.replace(/\/+$/, '').endsWith('/ops')
// relative API paths resolve against the page: under /ops/ they would point at /ops/api
if (admin && window.location.pathname.endsWith('/')) {
  window.history.replaceState(null, '', window.location.pathname.replace(/\/+$/, '') + window.location.search)
}

createRoot(document.getElementById('root')!).render(<StrictMode>{admin ? <Ops /> : <App />}</StrictMode>)
