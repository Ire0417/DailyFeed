import React, { useState } from "react";
import SourceTypeSelector from "./SourceTypeSelector";

const SubscriptionForm: React.FC = () => {
  const [sourceType, setSourceType] = useState<string>("rss");
  return (
    <form className="bg-white p-4 rounded shadow mb-6">
      <h2 className="font-bold mb-3">Add Subscription</h2>
      <SourceTypeSelector value={sourceType} onChange={setSourceType} />
      <button
        type="button"
        className="mt-3 bg-indigo-600 text-white px-4 py-2 rounded"
      >
        Save
      </button>
    </form>
  );
};

export default SubscriptionForm;
