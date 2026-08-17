/**
 * Backend Pydantic şemalarının TypeScript karşılıkları.
 *
 * ⚠️ `status` alanı BACKEND'de hesaplanır. Frontend bu değeri yalnızca
 * gösterir; tarihlerden yeniden hesaplamaz. Aksi hâlde iki taraf farklı
 * sonuç üretir ve kullanıcıya çelişkili bilgi gösterilir.
 */

/** Kampanya durumu. `unknown`, `expired`'dan AYRIDIR. */
export type CampaignStatus = "active" | "upcoming" | "expired" | "unknown";

/** Tarih çıkarımının güvenilirliği. */
export type DatePrecision = "exact" | "partial" | "inferred" | "unknown";

/** Bankanın kamuya açık veri zenginliği. */
export type DataStatus = "rich" | "limited" | "none";

export interface Bank {
  id: number;
  code: string;
  name: string;
  legal_name: string | null;
  website: string;
  bddk_status: string;
  tkbb_member: boolean;
  data_status: DataStatus;
  brand_color: string | null;
  notes: string | null;
  campaign_count: number;
}

export interface BankDetail extends Bank {
  legacy_domains: string[] | null;
}

/** Taksonominin dört dik ekseni. */
export type TaxonomyAxis = "product_type" | "sector" | "audience" | "benefit";

/** Etiketin hangi kanıttan çıkarıldığı. */
export type CategorySource =
  | "url"
  | "bank_category"
  | "merchant"
  | "keyword"
  | "llm";

/**
 * Kampanyanın tek bir eksendeki tek bir etiketi.
 *
 * Her etiket KANITIYLA gelir: `source` hangi kaynaktan çıkarıldığını,
 * `evidence` hangi metne dayandığını söyler. Arayüz bunları gösterir ama
 * yeniden hesaplamaz — sınıflandırma backend'de yapılır.
 */
export interface CampaignCategory {
  axis: TaxonomyAxis;
  value: string;
  /** 0-1 arası. 1.00 bankanın kendi verisi, 0.30 çıkarılamadı demektir. */
  confidence: string;
  source: CategorySource;
  evidence: string | null;
}

export interface CampaignListItem {
  id: number;
  bank_code: string;
  bank_name: string;
  external_slug: string;
  title: string;
  category: string | null;
  /** Bankanın KENDİ kategori etiketi, ham hâliyle. */
  bank_category: string | null;
  /** Dört eksenli taksonomi etiketleri. */
  categories: CampaignCategory[];
  segment: string | null;
  target_customer: string | null;
  /** Bilinmiyorsa null — tarih uydurulmaz. */
  start_date: string | null;
  end_date: string | null;
  date_precision: DatePrecision;
  /** Tarihin kaynaktaki dayanağı; yoksa null. */
  date_evidence_text: string | null;
  /** structured | conditions | body */
  date_evidence_source: string | null;
  status: CampaignStatus;
  source_url: string;
  /** Dolu ise bu kayıt bir ALT kampanyadır. */
  parent_campaign_id: number | null;
  /** Aynı sayfada yayımlanan alt kampanya sayısı. */
  sub_campaign_count: number;
}

export interface SourceDocumentSummary {
  id: number;
  url: string;
  canonical_url: string | null;
  doc_type: string;
  http_status: number | null;
  fetched_at: string;
  scraper_name: string | null;
  scraper_version: string | null;
  raw_html_sha256: string | null;
}

export interface CampaignDetail extends CampaignListItem {
  description: string | null;
  conditions_text: string | null;
  exclusions_text: string | null;
  participation_method: string | null;
  participation_channel: string | null;
  sms_keyword: string | null;
  sms_number: string | null;
  coupon_code: string | null;
  is_archived: boolean;
  first_seen_at: string;
  last_seen_at: string;
  bank: Omit<Bank, "campaign_count">;
  source_document: SourceDocumentSummary | null;
  /** Aynı sayfada yayımlanan alt kampanyalar. */
  sub_campaigns: CampaignListItem[];
}

/** Sayfalı liste yanıtı. Boş `items` bir hata değildir. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface BankCampaignCount {
  bank_code: string;
  bank_name: string;
  count: number;
}

export interface CategoryCount {
  category: string | null;
  count: number;
}

export interface Stats {
  total_banks: number;
  banks_with_data: number;
  total_campaigns: number;
  active_campaigns: number;
  upcoming_campaigns: number;
  expired_campaigns: number;
  /** Tarihi bulunamayan kampanyalar — "süresi dolmuş" değildir. */
  unknown_status_campaigns: number;
  campaigns_by_bank: BankCampaignCount[];
  campaigns_by_category: CategoryCount[];
  last_scrape_at: string | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  db_ok: boolean;
  campaign_count: number;
}

/** Backend'in tek biçimli hata gövdesi. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    detail: string | null;
  };
}

/** `GET /campaigns` sorgu parametreleri. */
export interface CampaignQuery {
  bank?: string[];
  category?: string;
  segment?: string;
  status?: CampaignStatus;
  q?: string;
  sort?: "title" | "start_date" | "end_date" | "bank";
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}
