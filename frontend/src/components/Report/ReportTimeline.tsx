import React from "react";

interface Props {
  items?: { id: number; title: string; time: string }[];
}

const ReportTimeline: React.FC<Props> = ({ items = [] }) => {
  return (
    <ol className="border-l-2 border-indigo-200 pl-4">
      {items.map((item) => (
        <li key={item.id} className="mb-4">
          <div className="text-sm font-semibold">{item.title}</div>
          <div className="text-xs text-gray-500">{item.time}</div>
        </li>
      ))}
    </ol>
  );
};

export default ReportTimeline;
