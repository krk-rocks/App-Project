import { Link } from 'react-router-dom'

export default function Nav() {
  return (
    <header className="nav">
      <Link to="/" className="logo"><span className="logo-dot" />wanderlust</Link>
      <nav className="nav-pill">
        <a href="/#destinations">Destinations</a>
        <a href="/#features">Features</a>
        <a href="/#explore">Explore</a>
      </nav>
      <a href="/#destinations" className="btn btn-dark">Start exploring</a>
    </header>
  )
}
