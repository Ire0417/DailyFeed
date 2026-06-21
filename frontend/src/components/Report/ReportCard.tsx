import React from "react";

interface Props {
  title?: string;
  date?: string;
}

const ReportCard: React.FC<Props> = ({ title = "Daily Report", date }) => {
  return (
    <div className="bg-white p-4 rounded shadow">
      <h3 className="font-bold">{title}</h3>
      <p className="text-sm text-gray-500">{date}</p>
    </div>
  );
};

export default ReportCard;
