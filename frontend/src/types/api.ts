/**
 * Backend API sözleşmesinin TypeScript karşılıkları.
 *
 * ⚠️ Pydantic `Decimal` alanları JSON'da SAYI değil STRING olarak gelir
 * (ör. `"profit_rate_pct": "3.0500"`) — kesinlik kaybını önlemek için.
 * Bu dosyada `string` tipiyle işaretlenen parasal/yüzde/güven alanları
 * `lib/format.ts::parseDecimal` ile sayıya çevrilmeden toplanamaz/sıralanamaz.
 * İstisna: `ChatResultItem.profit_rate_pct` ve `ExtractedFieldOut.confidence`
 * backend'de gerçek `float` alanlardır, string DEĞİLDİR.
 */

// ==================== Ortak ====================

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ==================== Bankalar ====================

export type BddkStatus = "active" | "pre_launch";
export type DataStatus = "rich" | "limited" | "none";

export interface BankBase {
  id: number;
  code: string;
  name: string;
  legal_name: string | null;
  website: string;
  bddk_status: BddkStatus;
  tkbb_member: boolean;
  data_status: DataStatus;
  brand_color: string | null;
  notes: string | null;
}

export interface BankSummary extends BankBase {
  campaign_count: number;
}

export interface BankDetail extends BankSummary {
  legacy_domains: string[] | null;
}

/** `CampaignFilters`/`CampaignTable` mevcut kodda bu adı kullanıyor. */
export type Bank = BankSummary;

// ==================== İstatistik ====================

export interface BankCampaignCount {
  bank_code: string;
  bank_name: string;
  count: number;
}

export interface CategoryCount {
  category: string | null;
  count: number;
}

export interface SectorCount {
  sector: string;
  count: number;
}

/** Rekabet radarı ekseni. Eksen değerleri 0-100 GÖRELİ puandır, mutlak not değildir. */
export interface RadarScore {
  bank_code: string;
  bank_name: string;
  rate_competitiveness: number | null;
  campaign_volume: number;
  reward_generosity: number | null;
  term_flexibility: number | null;
  transparency_index: number | null;
  /** 5 eksenden kaçında gerçek ölçüm var. */
  measured_axes: number;
}

export interface StatsResponse {
  total_banks: number;
  banks_with_data: number;
  total_campaigns: number;
  active_campaigns: number;
  upcoming_campaigns: number;
  expired_campaigns: number;
  unknown_status_campaigns: number;
  products_total: number;
  rates_total: number;
  limits_total: number;
  ai_coverage_pct: number;
  green_campaigns_count: number;
  campaigns_by_bank: BankCampaignCount[];
  campaigns_by_category: CategoryCount[];
  sector_distribution: SectorCount[];
  radar_scores: RadarScore[];
  last_scrape_at: string | null;
}

// ==================== Kampanyalar ====================

export type CampaignStatus = "active" | "upcoming" | "expired" | "unknown";
export type DatePrecision = "exact" | "partial" | "inferred" | "unknown";
export type TaxonomyAxis = "product_type" | "sector" | "audience" | "benefit";
export type CampaignCategorySource = "url" | "bank_category" | "merchant" | "keyword" | "llm";
export type DateEvidenceSource = "structured" | "conditions" | "body";

export interface CampaignCategory {
  axis: TaxonomyAxis;
  value: string;
  /** Decimal → string. */
  confidence: string;
  source: CampaignCategorySource;
  evidence: string | null;
}

export interface CampaignQuery {
  bank?: string[];
  category?: string;
  segment?: string;
  target_customer?: string;
  status?: CampaignStatus;
  sector?: string;
  product_type?: string;
  audience?: string;
  benefit?: string;
  q?: string;
  start_after?: string;
  end_before?: string;
  sort?: "title" | "start_date" | "end_date" | "bank";
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
  include_children?: boolean;
  /** Varsayılan false: süresi kesin dolmuş kampanyalar gizlenir (KAPI 5). */
  include_expired?: boolean;
}

export interface CampaignListItem {
  id: number;
  bank_code: string;
  bank_name: string;
  external_slug: string;
  title: string;
  category: string | null;
  bank_category: string | null;
  categories: CampaignCategory[];
  segment: string | null;
  target_customer: string | null;
  start_date: string | null;
  end_date: string | null;
  date_precision: DatePrecision;
  date_evidence_text: string | null;
  date_evidence_source: DateEvidenceSource | null;
  status: CampaignStatus;
  source_url: string;
  parent_campaign_id: number | null;
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

export type CampaignProductMatchMethod = "title" | "slug" | "body";

export interface LinkedProduct {
  product_id: number;
  product_name: string;
  product_type: string | null;
  variant_label: string | null;
  match_method: CampaignProductMatchMethod;
  /** Decimal → string. Bağın sağlamlığını söyler, ürünün iyiliğini değil. */
  confidence: string;
  evidence: string | null;
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
  bank: BankBase;
  source_document: SourceDocumentSummary | null;
  sub_campaigns: CampaignListItem[];
  products: LinkedProduct[];
}

/**
 * `POST /campaigns/compare` istek gövdesi. ⚠️ Yanıt şeması bu geçişte
 * doğrulanmadı — hiçbir sayfa bu uca bağlanmıyor. Kullanmadan önce backend
 * kaynağından `CampaignRankingResponse` şeması teyit edilmeli.
 */
export interface CampaignCompareRequest {
  criterion: string;
  bank_codes?: string[] | null;
  product_type?: string | null;
  only_active?: boolean;
  limit?: number;
}

// ==================== Ürünler ====================

/** Sıralamaya (`/compare`) girebilen oran türleri. */
export type ComparableRateType = "financing_rate" | "participation_yield" | "profit_sharing_ratio";

/**
 * Tüm depolanabilir oran türleri. `interest_free_benevolent_loan` (karz-ı
 * hasen / vade farksız eğitim finansmanı) KASITLI OLARAK `ComparableRateType`'ta
 * YOK — bu ürünler sıralamaya hiç giremez (bkz. backend `RATE_TYPE_COMPARABLE_FIELD`).
 */
export type RateType = ComparableRateType | "interest_free_benevolent_loan";

export interface ProductRateOut {
  id: number;
  rate_type: RateType;
  profit_rate_pct: string | null;
  investor_share_pct: string | null;
  bank_share_pct: string | null;
  allocation_fee_pct: string | null;
  monthly_cost_pct: string | null;
  annual_cost_pct: string | null;
  term_months: number | null;
  term_days_min: number | null;
  term_days_max: number | null;
  term_label: string | null;
  amount_min: string | null;
  amount_max: string | null;
  currency: string;
  account_tier: string | null;
  customer_type: string | null;
  is_gross: boolean | null;
  variant: string | null;
  effective_date: string | null;
  rate_source: string;
  confidence: string;
  evidence_text: string | null;
  /** bank_site | tkbb_veripetegi — KATİP KAPI 4 */
  data_source: string;
}

export interface ProductLimitOut {
  id: number;
  asset_value_min: string | null;
  asset_value_max: string | null;
  financing_ratio_pct: string | null;
  term_months_min: number | null;
  term_months_max: number | null;
  amount_max: string | null;
  energy_class: string | null;
  vehicle_age_min: number | null;
  vehicle_age_max: number | null;
  currency: string;
  extraction_method: "html_table" | "pdf_table" | "text";
  source_url: string;
  evidence_text: string | null;
}

export interface ProductOut {
  id: number;
  bank_code: string | null;
  bank_name: string | null;
  external_key: string;
  name: string;
  product_type: string | null;
  segment: string | null;
  currency: string;
  variant_key: string | null;
  variant_label: string | null;
  parent_product_id: number | null;
  is_active: boolean;
  /** ilk_alim | sonraki_alim | null — KATİP KAPI 1.2 */
  purchase_order: string | null;
  brand: string | null;
  model: string | null;
  /** offered | not_offered | unknown — KATİP KAPI 1.5 */
  availability_status: string;
  amount_min: string | null;
  amount_max: string | null;
  term_months_min: number | null;
  term_months_max: number | null;
  rates: ProductRateOut[];
  limits: ProductLimitOut[];
}

export type CollateralType = "konut" | "tasit" | "yok" | "diger";

export interface ProductDetailOut extends ProductOut {
  description: string | null;
  allowed_terms: number[] | null;
  collateral_type: CollateralType | null;
  has_calculator: boolean;
  calculator_url: string | null;
  limits_source: string | null;
  limits_evidence: string | null;
  is_binding: boolean;
  non_binding_notice: string | null;
  source_url: string | null;
  source_fetched_at: string | null;
  variants: ProductOut[];
}

export interface ProductQuery {
  bank_code?: string;
  product_type?: string;
  rate_type?: RateType;
  limit?: number;
}

export type RankingCriterion =
  | "en_dusuk_kar_payi"
  | "en_dusuk_masraf"
  | "en_dusuk_toplam_maliyet"
  | "en_yuksek_getiri"
  | "en_yuksek_paylasim_orani"
  | "en_uzun_vade"
  | "en_avantajli";

export interface RankingWeights {
  rate_weight?: string;
  fee_weight?: string;
  term_weight?: string;
}

export interface ProductRankingRequest {
  rate_type: ComparableRateType;
  criterion: RankingCriterion;
  product_type?: string | null;
  bank_codes?: string[] | null;
  term_months?: number | null;
  term_days?: number | null;
  currency?: string;
  amount_try?: string | null;
  weights?: RankingWeights;
  limit?: number;
}

export interface RankedProduct {
  rank: number | null;
  product_id: number;
  product_name: string;
  bank_code: string;
  bank_name: string;
  product_type: string | null;
  rate_type: string;
  profit_rate_pct: string | null;
  allocation_fee_pct: string | null;
  annual_cost_pct: string | null;
  investor_share_pct: string | null;
  bank_share_pct: string | null;
  term_months: number | null;
  term_label: string | null;
  currency: string;
  score: string | null;
  evidence_text: string | null;
  source_url: string | null;
  missing_reason: string | null;
}

export interface ProductRankingResponse {
  rate_type: string;
  criterion: string;
  sort_field: string;
  descending: boolean;
  winner: RankedProduct | null;
  winner_reason: string | null;
  ranked: RankedProduct[];
  without_data: RankedProduct[];
  note: string;
}

// ==================== Finansmanlar (KATİP KAPI 6) ====================

export interface FinancingQuery {
  bank_code?: string;
  product_type?: string;
  limit?: number;
}

export interface FinancingResponse {
  financing: ProductOut[];
  no_data_products: string[];
  coverage_note: string;
}

// ==================== Katılım Hesabı (KATİP KAPI 7) ====================

export type KatilimHesabiRateType = "participation_yield" | "profit_sharing_ratio";
export type KatilimHesabiVariant = "normal" | "ara_odemeli";
export type KatilimHesabiTerm = "aylik" | "3_aylik" | "6_aylik" | "yillik";

export interface KatilimHesabiQuery {
  rate_type?: KatilimHesabiRateType;
  variant?: KatilimHesabiVariant;
  currency?: string;
  term?: KatilimHesabiTerm;
}

export interface KatilimHesabiCrossCheck {
  bank_site_value: string | null;
  tkbb_value: string | null;
  match: "ayni" | "yakin" | "farkli";
}

export interface KatilimHesabiRow {
  bank_code: string;
  bank_name: string;
  /** "{vade}|{para_birimi}" -> değer, ör. "aylik|TRY" */
  values: Record<string, string>;
  data_source: string;
  cross_check: KatilimHesabiCrossCheck | null;
}

export interface KatilimHesabiResponse {
  rate_type: string;
  variant: string;
  rows: KatilimHesabiRow[];
  not_offered_banks: string[];
  data_quality_notes: string[];
}

// ==================== Simülatör ====================

export interface FinancingSimulationRequest {
  amount_try: string;
  term_months: number;
  product_type?: string;
}

export interface MissingDataBank {
  bank_code: string;
  bank_name: string;
  reason: string;
}

export interface BankFinancingOffer {
  bank_code: string;
  bank_name: string;
  product_id: number;
  product_name: string;
  profit_rate_pct: string;
  rate_term_months: number | null;
  is_exact_term_match: boolean;
  monthly_payment_try: string;
  total_profit_try: string;
  total_payment_try: string;
  is_best_offer: boolean;
  source_url: string | null;
  evidence_text: string | null;
}

export interface FinancingSimulationResponse {
  amount_try: string;
  term_months: number;
  product_type: string;
  best_bank_code: string | null;
  offers: BankFinancingOffer[];
  banks_without_data: MissingDataBank[];
  method_note: string;
}

export interface ParticipationYieldRequest {
  deposit_try: string;
  term_days: number;
  currency?: string;
}

export interface BankYieldOffer {
  bank_code: string;
  bank_name: string;
  product_id: number;
  product_name: string;
  annual_yield_gross_pct: string;
  rate_term_label: string | null;
  is_exact_term_match: boolean;
  investor_share_pct: string | null;
  bank_share_pct: string | null;
  gross_profit_try: string;
  withholding_pct: string;
  withholding_try: string;
  net_profit_try: string;
  is_best_yield: boolean;
  source_url: string | null;
  evidence_text: string | null;
}

export interface ParticipationYieldResponse {
  deposit_try: string;
  term_days: number;
  currency: string;
  best_yield_bank_code: string | null;
  offers: BankYieldOffer[];
  banks_without_data: MissingDataBank[];
  withholding_note: string;
  method_note: string;
}

export interface BDDKLimitCheckRequest {
  asset_type: "tasit" | "konut";
  asset_value_try: string;
  energy_class?: string | null;
}

export interface BDDKLimitCheckResponse {
  asset_type: string;
  asset_value_try: string;
  energy_class: string | null;
  value_band_label: string;
  max_financing_ratio_pct: string;
  max_financing_amount_try: string;
  max_allowed_term_months: number | null;
  is_financing_allowed: boolean;
  legal_reference: string;
}

// ==================== Sohbet ====================

export interface ChatRequest {
  query: string;
  bank_code?: string | null;
}

export interface ChatResultItem {
  campaign_id: number;
  bank_code: string;
  bank_name: string;
  title: string;
  summary: string | null;
  evidence_text: string | null;
  source_url: string | null;
  /** ⚠️ Diğerlerinin aksine gerçek `float` — Decimal string DEĞİL. */
  profit_rate_pct: number | null;
}

export interface ChatResponse {
  query: string;
  answer_text: string;
  forbidden_terms_warning: string | null;
  results: ChatResultItem[];
}

// ==================== Canlı Çıkarım ====================

export type ExtractMode = "rule_only" | "hybrid" | "llm_only";

export interface ExtractRequest {
  text: string;
  mode?: ExtractMode;
}

export interface ExtractedFieldOut {
  value: string;
  unit: string;
  /** ⚠️ Gerçek `float` (0-1) — Decimal string DEĞİL. */
  confidence: number;
  method: "table" | "rule" | "llm";
  evidence: string | null;
  evidence_span: [number, number] | null;
  validation_note: string | null;
}

export interface RejectedFieldOut {
  field_name: string;
  value: string;
  method: string;
  reason: string;
  evidence: string | null;
}

export interface ModelInfoOut {
  name: string;
  license: string;
  local: boolean;
}

export interface ExtractResponse {
  fields: Record<string, ExtractedFieldOut>;
  labels: Record<string, string[]>;
  summary: string | null;
  rejected: RejectedFieldOut[];
  logic_violations: Record<string, string>;
  model: ModelInfoOut;
  latency_ms: number;
  mode: string;
  extras: Record<string, unknown>;
}
