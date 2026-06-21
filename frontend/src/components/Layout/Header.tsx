import React from "react";
import { Link } from "react-router-dom";

const Header: React.FC = () => {
  return (
    <header className="bg-indigo-700 text-white px-6 py-3 flex items-center justify-between">
      <Link to="/" className="font-bold text-lg">DailyFeed</Link>
      <nav className="space-x-4">
        <Link to="/reports" className="hover:underline">Reports</Link>
        <Link to="/settings" className="hover:underline">Settings</Link>
      </nav>
    </header>
  );
};

export default Header;
