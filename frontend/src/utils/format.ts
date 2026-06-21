export const formatDate = (d: string | Date): string => {
  const date = typeof d === "string" ? new Date(d) : d;
  return date.toLocaleDateString();
};

export const truncate = (text: string, max = 100): string => {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "..." : text;
};
