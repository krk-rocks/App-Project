import { Routes, Route, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import Nav from './components/Nav.jsx'
import Home from './pages/Home.jsx'
import Destination from './pages/Destination.jsx'
import Login from './pages/Login.jsx'
import Bookings from './pages/Bookings.jsx'
import Tickets from './pages/Tickets.jsx'
import Wallet from './pages/Wallet.jsx'
import Planner from './pages/Planner.jsx'
import Trips, { TripJoin } from './pages/Trips.jsx'
import Trip from './pages/Trip.jsx'

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
        <Route path="/wallet" element={<Wallet />} />
        <Route path="/planner" element={<Planner />} />
        <Route path="/trips" element={<Trips />} />
        <Route path="/trips/join/:code" element={<TripJoin />} />
        <Route path="/trips/:id" element={<Trip />} />
      </Routes>
      <footer className="footer">© 2026 Epic TN · Timings and events are indicative; confirm locally before you travel. Bookings are simulated.</footer>
    </>
  )
}
