import { ExternalLink } from "lucide-react";
import React from "react";

interface EvidenceTextProps {
  text: string;
  className?: string;
  prefix?: string;
}

/**
 * Kanıt metnindeki URL'leri (özellikle "Kaynak: https://..." gibi uzun linkleri)
 * temiz, belirgin ve tıklanabilir "Kaynak için tıklayınız ↗" bağlantısına dönüştürür.
 */
export function EvidenceText({ text, className, prefix = "Kanıt: " }: EvidenceTextProps) {
  if (!text) return null;

  // URL ve önündeki "Kaynak:" / "(veri:" kısımlarını yakalar
  const urlRegex = /(?:\(veri:\s*)?(?:Kaynak:\s*)?(https?:\/\/[^\s\),]+)(?:\))?/g;

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = urlRegex.exec(text)) !== null) {
    const fullMatch = match[0];
    const url = match[1];
    const startIndex = match.index;

    // Eşleşme öncesindeki düz metin
    if (startIndex > lastIndex) {
      parts.push(text.slice(lastIndex, startIndex));
    }

    // Tıklanabilir bağlantı
    parts.push(
      <a
        key={`${url}-${startIndex}`}
        href={url}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1 font-medium text-brand-600 underline underline-offset-2 hover:text-brand-800 transition-colors"
      >
        <span>Kaynak için tıklayınız</span>
        <ExternalLink className="h-3 w-3 inline shrink-0" aria-hidden="true" />
      </a>
    );

    lastIndex = startIndex + fullMatch.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return (
    <p className={className ?? "text-xs text-text-500"}>
      {prefix}“{parts}”
    </p>
  );
}
