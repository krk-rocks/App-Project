import { Routes, Route, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import Nav from './components/Nav.jsx'
import Home from './pages/Home.jsx'
import Destination from './pages/Destination.jsx'
import Login from './pages/Login.jsx'
import Bookings from './pages/Bookings.jsx'
import Tickets from './pages/Tickets.jsx'

export default function App() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  return (
    <>
      <Nav />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/destination/:id" element={<Destination />} />
        <Route path="/login" element={<Login />} />
        <Route path="/bookings" element={<Bookings />} />
        <Route path="/tickets" element={<Tickets />} />
      </Routes>
      <footer className="footer">© 2026 Epic TN · Timings and events are indicative; confirm locally before you travel. Bookings are simulated.</footer>
    </>
  )
}
