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

export interface HealthResponse {
  status: string;
  version: string;
  db_ok: boolean;
  campaign_count: number;
}

export type AdminJobKind =
  | "campaign"
  | "js_campaign"
  | "product"
  | "bank_pipeline"
  | "campaign_all"
  | "js_campaign_all"
  | "product_all"
  | "tkbb"
  | "tkbb_seed"
  | "llm_health";

export type AdminJobStatus = "queued" | "running" | "succeeded" | "failed";

export interface AdminJob {
  id: string;
  kind: AdminJobKind;
  bank_code: string | null;
  status: AdminJobStatus;
  command: string[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  log: string;
  error: string | null;
  summary: string | null;
}

export interface AdminJobCreateRequest {
  kind: AdminJobKind;
  bank_code?: string | null;
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

export interface TaxonomyCount {
  value: string;
  count: number;
}

export interface BankCoverage {
  bank_code: string;
  bank_name: string;
  active: number;
  total: number;
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
  /** Sınıflandırma kapsamı (%): en az bir taksonomi etiketi olan kök kampanya oranı. */
  ai_coverage_pct: number;
  green_campaigns_count: number;
  ending_soon_count: number;
  campaigns_by_bank: BankCampaignCount[];
  campaigns_by_category: CategoryCount[];
  sector_distribution: SectorCount[];
  audience_distribution: TaxonomyCount[];
  benefit_distribution: TaxonomyCount[];
  active_by_bank: BankCoverage[];
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

export type CampaignRankingCriterion =
  | "en_yuksek_odul"
  | "en_dusuk_kar_payi"
  | "en_uzun_vade"
  | "en_yuksek_taksit"
  | "en_yuksek_iade_orani"
  | "en_yuksek_indirim";

/** `POST /campaigns/compare` istek gövdesi (§5.7). */
export interface CampaignCompareRequest {
  criterion: CampaignRankingCriterion | string;
  bank_codes?: string[] | null;
  product_type?: string | null;
  only_active?: boolean;
  limit?: number;
}

export interface RankedCampaign {
  rank: number | null;
  campaign_id: number;
  title: string;
  bank_code: string;
  bank_name: string;
  status: string;
  reward_amount_try: string | null;
  reward_type: string | null;
  profit_rate_pct: string | null;
  term_months_max: number | null;
  installment_count: number | null;
  cashback_pct: string | null;
  discount_pct: string | null;
  min_spend_try: string | null;
  has_no_fee: boolean | null;
  end_date: string | null;
  source_url: string | null;
  missing_reason: string | null;
}

export interface CampaignRankingResponse {
  criterion: string;
  sort_field: string;
  descending: boolean;
  winner: RankedCampaign | null;
  winner_reason: string | null;
  ranked: RankedCampaign[];
  without_data: RankedCampaign[];
  note: string;
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
  is_binding: boolean;
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
  bddk_limits: BddkCanonicalLimitsOut | null;
  bank_limit_deviations: BankLimitDeviationOut[];
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
  /** Oranın yürürlük / yayımlanma tarihi. */
  effective_date?: string | null;
  rate_source?: string | null;
  is_binding?: boolean | null;
  variant_label?: string | null;
  account_tier?: string | null;
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
  /** Karışık varyant/kademe sıralamasında kullanıcıya gösterilecek uyarılar. */
  comparability_warnings?: string[];
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
  products_with_limits_only: string[];
  coverage_note: string;
  bddk_limits: BddkCanonicalLimitsOut | null;
  bddk_limits_by_family: Record<string, BddkCanonicalLimitsOut>;
}

export interface BddkBandOut {
  label: string;
  amount_min: string | null;
  amount_max: string | null;
  value_min: string | null;
  value_max: string | null;
  max_term_months: number | null;
  max_ratio_pct: string | null;
  rates: Record<string, string> | null;
}

export interface BddkCanonicalLimitsOut {
  family: string;
  kind: string;
  decision_no: string;
  decision_date: string;
  legal_reference: string;
  source_url: string;
  bands: BddkBandOut[];
  max_term_months: number | null;
  second_home_reduction_pct: string | null;
  second_home_note: string | null;
  as_of: string | null;
}

export interface BankLimitDeviationOut {
  limit_id: number;
  message: string;
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
  bank_codes?: string[] | null;
}

export interface MissingDataBank {
  bank_code: string;
  bank_name: string;
  reason: string;
}

/** Eşit taksitli ödeme planının tek ay satırı. */
export interface InstallmentRow {
  month: number;
  installment: string;
  profit_share: string;
  principal: string;
  remaining_balance: string;
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
  allocation_fee_try?: string | null;
  total_cost_try?: string | null;
  annual_cost_pct?: string | null;
  installments?: InstallmentRow[];
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
  bank_codes?: string[] | null;
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
  asset_type: "tasit" | "konut" | "ihtiyac";
  asset_value_try: string;
  energy_class?: string | null;
  first_home?: boolean | null;
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
  first_home: boolean | null;
}

// ==================== Sohbet ====================

export interface ChatRequest {
  query: string;
  /** `GET /chat/models` anahtarı. ⚠️ Yalnızca bu isteği etkiler; .env yazılmaz. */
  model_id?: string | null;
  bank_code?: string | null;
  limit?: number;
  /** Sunucu oturum anahtarı (`session_key`); yoksa yeni oturum açılır. */
  session_id?: string | null;
  /**
   * Bu sorunun takip ettiği cevabın kimliği. Verilmezse sunucu oturumun SON
   * turunu kullanır; geçmişten eski bir tura dönüldüğünde bu yanlış olur.
   */
  parent_completion_id?: string | null;
}

export interface ChatSessionCreateResponse {
  session_id: string;
  title?: string | null;
  created_at?: string;
}

export interface ChatSessionMessage {
  turn_index: number;
  role: "user" | "assistant";
  content: string;
  /** Assistant turlarında dolu; geçmiş yüklenince zincir kopmasın. */
  completion_id?: string | null;
  /** Assistant turlarında dolu; geçmiş yüklenince kartlar geri gelir. */
  response_json?: ChatResponse | null;
  /** Bazı backend sürümleri `response` adını kullanabilir. */
  response?: ChatResponse | null;
  intent?: string | null;
  source_domain?: string | null;
  answer_source?: string | null;
  created_at?: string;
}

export interface ChatSessionDetail {
  session_id?: string;
  session_key?: string;
  title: string | null;
  ended_at: string | null;
  created_at?: string;
  last_activity_at?: string | null;
  messages: ChatSessionMessage[];
}

export interface ChatMetric {
  field: string;
  label: string;
  /** Decimal string (Pydantic). */
  value: string;
  unit: string;
}

export interface ChatResultItem {
  campaign_id: number;
  bank_code: string;
  bank_name: string;
  title: string;
  status: string;
  source_url: string;
  summary: string | null;
  card_text: string;
  metrics: ChatMetric[];
  channels: string[];
  matched_terms: string[];
}

export interface UnderstoodFilter {
  kind: string;
  value: string;
  label: string;
  display: string;
  evidence: string;
}

export interface UnverifiedNumberOut {
  value: string;
  cited: number[];
}

export interface TerminologyWarningOut {
  term: string;
  suggestion: string | null;
}

export interface AnswerBlock {
  text: string;
  source: "model" | "template" | "refusal" | "computed" | string;
  citations: number[];
  unverified_numbers: UnverifiedNumberOut[];
  terminology_warnings: TerminologyWarningOut[];
  is_grounded: boolean;
  model_name: string | null;
  model_error: string | null;
  latency_ms: number | null;
}

export interface FilterRejection {
  filter: string;
  label: string;
  count: number;
}

export interface RetrievalReport {
  corpus_size: number;
  returned: number;
  lexical_used: boolean;
  semantic_used: boolean;
  semantic_note: string | null;
  rejected: FilterRejection[];
  total_rejected: number;
  elapsed_ms: number;
}

export interface RelaxationHintOut {
  kind: string;
  value: string;
  label: string;
  hit_count: number;
}

export interface AggregateBlock {
  kind: string;
  field: string | null;
  field_label: string | null;
  value: string | null;
  unit: string | null;
  winner_campaign_id: number | null;
  with_value: number;
  without_value: number;
  total: number;
  tie_count: number;
  /** ⚠️ Sıfır sayılı bankalar da bulunur: "veri yok" da bir bulgudur. */
  by_bank: Record<string, number> | null;
  /** `count_banks` / `absence`: kriteri karşılayan banka adları. */
  banks_with?: string[];
  /**
   * Kriteri karşılayan KAYDI OLMAYAN banka adları.
   * ⚠️ Boş dizi "hepsinde var" demektir, "alan yok" demez — yokluk sorusunun
   * yanıtı `banks_with` DEĞİLDİR, bu alandır.
   */
  banks_without?: string[];
}

export interface ChatProductItem {
  product_id: number;
  product_name: string;
  bank_code: string;
  bank_name: string;
  product_type: string | null;
  rate_type: string | null;
  rate_id: number | null;
  card_text: string;
  profit_rate_pct: string | null;
  investor_share_pct: string | null;
  term_months: number | null;
  source_url: string | null;
}

export interface ChatGlossaryItem {
  term_id: number;
  term: string;
  definition: string;
  conventional_equivalent: string | null;
}

export interface ChatComparisonBlock {
  rate_type: string;
  criterion: string;
  winner_product_id: number | null;
  winner_bank_code: string | null;
  winner_reason: string | null;
  ranked: ChatProductItem[];
  without_data: ChatProductItem[];
  note: string | null;
}

export interface ChatTopMatch {
  entity_type: string;
  id: number;
  title: string;
  bank_name: string | null;
  score: string;
  source_url: string | null;
  reason: string | null;
  detail_path: string | null;
}

export interface ChatSessionSummary {
  session_key: string;
  title: string | null;
  created_at: string;
  last_activity_at: string;
  ended_at: string | null;
  turn_count: number;
  first_query: string | null;
}

export interface ChatSessionList {
  items: ChatSessionSummary[];
  total: number;
}

export interface ChatModelOption {
  /** `provider:model` biçiminde kararlı anahtar. */
  id: string;
  provider: string;
  model: string;
  label: string;
  /** Kapalı ağda çalışır mı? */
  is_local: boolean;
  is_active: boolean;
  /** Sağlık yoklaması geçti mi? Geçmediyse listede DEVRE DIŞI gösterilir. */
  available: boolean;
  note: string | null;
}

export interface ChatModelsResponse {
  active_id: string;
  items: ChatModelOption[];
}

export interface ChatResponse {
  query: string;
  intent: string;
  understood: UnderstoodFilter[];
  answer: AnswerBlock;
  aggregate: AggregateBlock | null;
  results: ChatResultItem[];
  retrieval: RetrievalReport;
  relaxation_hints: RelaxationHintOut[];
  forbidden_terms_warning: string | null;
  clarification_needed: boolean;
  clarification_question: string | null;
  direction_note: string | null;
  products: ChatProductItem[];
  glossary: ChatGlossaryItem[];
  comparison: ChatComparisonBlock | null;
  source_domain?: string | null;
  top_matches?: ChatTopMatch[];
  /** Sunucu oturum anahtarı — localStorage'da saklanır. */
  session_id?: string | null;
  turn_index?: number | null;
  /** Bu cevabın kimliği; sıradaki soruda `parent_completion_id` olarak gider. */
  completion_id?: string | null;
  /** Bağlamın devralındığı cevabın kimliği; devir olmadıysa null. */
  parent_completion_id?: string | null;
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
