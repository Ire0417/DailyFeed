import React from "react";

interface Props {
  message?: string;
}

const Empty: React.FC<Props> = ({ message = "Nothing to show." }) => {
  return (
    <div className="text-center text-gray-500 py-8 border rounded bg-gray-50">
      {message}
    </div>
  );
};

export default Empty;
