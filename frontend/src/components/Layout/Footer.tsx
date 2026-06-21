import React from "react";

const Footer: React.FC = () => {
  return (
    <footer className="text-center text-sm text-gray-500 py-4 border-t">
      DailyFeed &copy; {new Date().getFullYear()}
    </footer>
  );
};

export default Footer;
