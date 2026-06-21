import React from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
}

const options = [
  { value: "rss", label: "RSS Feed" },
  { value: "github", label: "GitHub" },
  { value: "bilibili", label: "Bilibili" },
];

const SourceTypeSelector: React.FC<Props> = ({ value, onChange }) => {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700">Source Type</label>
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="mt-1 block w-full border rounded px-3 py-2"
    >
      {options.map((o) => (
        <option key={o.value}>{o.label}</option>
      ))}
    </select>
    </div>
  );
};

export default SourceTypeSelector;
