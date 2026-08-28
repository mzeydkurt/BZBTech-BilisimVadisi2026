import { useState } from "react";
import { Building2 } from "lucide-react";

interface BankLogoProps {
  bankCode?: string | null;
  bankName?: string | null;
  className?: string;
  size?: "sm" | "md" | "lg";
  alt?: string;
}

const sizeClasses = {
  sm: "h-6 max-w-[80px]",
  md: "h-8 max-w-[120px]",
  lg: "h-10 max-w-[160px]",
};

const BANK_CODE_ALIASES: Record<string, string> = {
  tom: "tom_bank",
  tom_katilim: "tom_bank",
  emlak: "emlak_katilim",
  ziraat: "ziraat_katilim",
  vakif: "vakif_katilim",
  dunya: "dunya_katilim",
  hayat: "hayat_finans",
  kuveyt: "kuveyt_turk",
};

/**
 * Banka logosunu /banks/{bank_code}.png konumundan yükler.
 * Bulunamazsa veya hata verirse banka baş harfleri veya ikon ile yedek görünüm sunar.
 */
export function BankLogo({
  bankCode,
  bankName,
  className = "",
  size = "md",
  alt,
}: BankLogoProps) {
  const [hasError, setHasError] = useState(false);

  const rawCode = bankCode?.toLowerCase().trim();
  const cleanCode = rawCode ? (BANK_CODE_ALIASES[rawCode] ?? rawCode) : null;
  const logoSrc = cleanCode ? `/banks/${cleanCode}.png` : null;

  if (!logoSrc || hasError) {
    return (
      <div
        className={`inline-flex items-center justify-center rounded bg-neutral-100 px-2 py-1 text-xs font-semibold text-text-700 border border-border shrink-0 ${
          size === "sm" ? "h-6 text-[10px]" : size === "lg" ? "h-10 text-sm" : "h-8"
        } ${className}`}
        title={bankName ?? bankCode ?? "Banka"}
      >
        <Building2 className="mr-1 h-3.5 w-3.5 text-text-400" />
        <span className="truncate max-w-[90px]">{bankName ?? cleanCode ?? "Banka"}</span>
      </div>
    );
  }

  return (
    <img
      src={logoSrc}
      alt={alt ?? bankName ?? `${cleanCode} logosu`}
      onError={() => setHasError(true)}
      className={`object-contain inline-block shrink-0 ${sizeClasses[size]} ${className}`}
      loading="lazy"
    />
  );
}
