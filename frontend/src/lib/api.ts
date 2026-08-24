import type {
  BankDetail,
  BankSummary,
  BDDKLimitCheckRequest,
  BDDKLimitCheckResponse,
  CampaignCompareRequest,
  CampaignDetail,
  CampaignListItem,
  CampaignQuery,
  CampaignRankingResponse,
  ChatRequest,
  ChatResponse,
  ChatSessionCreateResponse,
  ChatSessionDetail,
  ExtractRequest,
  ExtractResponse,
  FinancingQuery,
  FinancingResponse,
  FinancingSimulationRequest,
  FinancingSimulationResponse,
  KatilimHesabiQuery,
  KatilimHesabiResponse,
  Page,
  ParticipationYieldRequest,
  ParticipationYieldResponse,
  ProductDetailOut,
  ProductOut,
  ProductQuery,
  ProductRankingRequest,
  ProductRankingResponse,
  StatsResponse,
} from "@/types/api";

const BASE_URL = "/api/v1";

interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    detail: string | null;
  };
}

/**
 * Ağ hatası ve 4xx/5xx bu sınıfı fırlatır. Boş sonuç ASLA `ApiError` DEĞİLDİR
 * — API çöktüğünde "kampanya yok" demek bu projede kabul edilemez bir hata
 * sınıfıdır (bkz. `ErrorState` vs `EmptyState` ayrımı).
 */
export class ApiError extends Error {
  code: string;
  detail: string | null;

  constructor(code: string, message: string, detail: string | null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail;
  }
}

/**
 * Query parametrelerini backend'in beklediği biçimde kodlar: diziler
 * TEKRARLANAN key olarak eklenir (`?bank=A&bank=B`), `bank[]=` DEĞİL —
 * FastAPI'nin `Query(list[str])` bağlaması bunu bekler.
 */
function buildQuery(params: Record<string, unknown>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === "") continue;
        usp.append(key, String(item));
      }
    } else {
      usp.append(key, String(value));
    }
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(
      "NETWORK_ERROR",
      "Sunucuya bağlanılamadı. İnternet bağlantınızı ve backend'in çalıştığını kontrol edin.",
      null,
    );
  }

  if (res.status === 204) return undefined as T;

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // Boş ya da JSON olmayan gövde; aşağıdaki durum kontrolleri devam eder.
  }

  if (!res.ok) {
    const envelope = body as Partial<ApiErrorEnvelope> | null;
    const err = envelope?.error;
    throw new ApiError(
      err?.code ?? `HTTP_${res.status}`,
      err?.message ?? "Beklenmeyen bir sunucu hatası oluştu.",
      err?.detail ?? null,
    );
  }

  return body as T;
}

function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>(`${path}${params ? buildQuery(params) : ""}`);
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

export const api = {
  banks: () => get<BankSummary[]>("/banks"),
  bank: (code: string) => get<BankDetail>(`/banks/${code}`),

  stats: () => get<StatsResponse>("/stats"),

  campaigns: (query: CampaignQuery) =>
    get<Page<CampaignListItem>>("/campaigns", query as Record<string, unknown>),
  campaign: (id: number) => get<CampaignDetail>(`/campaigns/${id}`),
  compareCampaigns: (body: CampaignCompareRequest) =>
    post<CampaignRankingResponse>("/campaigns/compare", body),

  products: (query: ProductQuery) => get<ProductOut[]>("/products", query as Record<string, unknown>),
  product: (id: number) => get<ProductDetailOut>(`/products/${id}`),
  compareProducts: (body: ProductRankingRequest) =>
    post<ProductRankingResponse>("/products/compare", body),

  financing: (query: FinancingQuery) =>
    get<FinancingResponse>("/financing", query as Record<string, unknown>),

  katilimHesabi: (query: KatilimHesabiQuery) =>
    get<KatilimHesabiResponse>("/katilim-hesabi", query as Record<string, unknown>),

  simulateFinancing: (body: FinancingSimulationRequest) =>
    post<FinancingSimulationResponse>("/simulator/financing", body),
  simulateYield: (body: ParticipationYieldRequest) =>
    post<ParticipationYieldResponse>("/simulator/yield", body),
  checkBddkLimit: (body: BDDKLimitCheckRequest) =>
    post<BDDKLimitCheckResponse>("/simulator/bddk-check", body),

  chat: (body: ChatRequest) => post<ChatResponse>("/chat", body),
  createChatSession: () => post<ChatSessionCreateResponse>("/chat/sessions", {}),
  getChatSession: (sessionKey: string) =>
    get<ChatSessionDetail>(`/chat/sessions/${encodeURIComponent(sessionKey)}`),
  /** Oturumu sonlandırır (`ended_at`); satırları silmez. */
  endChatSession: (sessionKey: string) =>
    del<void>(`/chat/sessions/${encodeURIComponent(sessionKey)}`),

  extract: (body: ExtractRequest) => post<ExtractResponse>("/extract", body),
};
