export const stripHtml = (raw: string): string =>
  raw.replace(/<[^>]+>/g, "").trim();

export const toPlainText = (markdown: string): string =>
  markdown
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/`(.+?)`/g, "$1");
