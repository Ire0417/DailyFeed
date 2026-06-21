import React from "react";
import { NavLink } from "react-router-dom";

const Sidebar: React.FC = () => {
  const links = [
    { to: "/", label: "Dashboard" },
    { to: "/subscriptions", label: "Subscriptions" },
    { to: "/reports", label: "Reports" },
    { to: "/settings", label: "Settings" },
  ];
  return (
    <aside className="w-56 border-r bg-gray-50 p-4">
      <ul className="space-y-2">
        {links.map((l) => (
          <li key={l.to}>
            <NavLink
              to={l.to}
              end={l.to === "/"}
              className={({ isActive }) =>
                `block px-3 py-2 rounded ${isActive ? "bg-indigo-600 text-white" : "text-gray-700 hover:bg-gray-200"}`
              }
            >
              {l.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </aside>
  );
};

export default Sidebar;
