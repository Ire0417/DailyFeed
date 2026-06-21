import React from "react";
import ReactMarkdown from "react-markdown";

interface Props {
  body: string;
}

const ReportContent: React.FC<Props> = ({ body }) => {
  return (
    <article className="prose bg-white p-6 rounded shadow">
      <ReactMarkdown>{body}</ReactMarkdown>
    </article>
  );
};

export default ReportContent;
