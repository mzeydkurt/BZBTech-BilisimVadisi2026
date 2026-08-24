import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBanks } from "@/hooks/useBanks";
import { api } from "@/lib/api";
import type { AdminJob, AdminJobKind } from "@/types/api";

type ActionDef = {
  kind: AdminJobKind;
  label: string;
  needsBank: boolean;
  hint: string;
  group: "banka" | "tumu" | "katilma" | "sistem";
};

const ACTIONS: ActionDef[] = [
  {
    kind: "bank_pipeline",
    label: "Seçili banka — hepsini çalıştır",
    needsBank: true,
    hint: "Sırayla: kampanya HTML → JS listing → ürün/finansman oranları.",
    group: "banka",
  },
  {
    kind: "campaign",
    label: "Kampanya scrape",
    needsBank: true,
    hint: "Seçili bankanın kampanya sayfalarını çeker (HTML).",
    group: "banka",
  },
  {
    kind: "js_campaign",
    label: "JS kampanya scrape",
    needsBank: true,
    hint: "Playwright listesi + detay (Dünya / Kuveyt vb.).",
    group: "banka",
  },
  {
    kind: "product",
    label: "Ürün / finansman scrape",
    needsBank: true,
    hint: "Finansman ürünleri, oran ve limit tabloları.",
    group: "banka",
  },
  {
    kind: "campaign_all",
    label: "Tüm bankalar — kampanya",
    needsBank: false,
    hint: "Kayıtlı tüm kampanya scraper’larını çalıştırır.",
    group: "tumu",
  },
  {
    kind: "js_campaign_all",
    label: "Tüm bankalar — JS kampanya",
    needsBank: false,
    hint: "JS listing hedeflerinin tamamı.",
    group: "tumu",
  },
  {
    kind: "product_all",
    label: "Tüm bankalar — ürün/finansman",
    needsBank: false,
    hint: "Tüm bankaların ürün kazıması.",
    group: "tumu",
  },
  {
    kind: "tkbb",
    label: "Katılma oranları — TKBB canlı",
    needsBank: false,
    hint: "Veri Peteği API’sinden güncel oranları yazar (aynı DB).",
    group: "katilma",
  },
  {
    kind: "tkbb_seed",
    label: "Katılma oranları — seed yedek",
    needsBank: false,
    hint: "Ağ yoksa elle doğrulanmış seed dosyasını yükler.",
    group: "katilma",
  },
  {
    kind: "llm_health",
    label: "LLM sağlık kontrolü",
    needsBank: false,
    hint: "Yerel / yapılandırılmış model sağlayıcısını dener.",
    group: "sistem",
  },
];

const GROUP_LABEL: Record<ActionDef["group"], string> = {
  banka: "Seçili banka",
  tumu: "Tüm bankalar",
  katilma: "Katılma hesabı oranları",
  sistem: "Sistem",
};

function statusLabel(status: AdminJob["status"]): string {
  switch (status) {
    case "queued":
      return "Kuyrukta";
    case "running":
      return "Çalışıyor";
    case "succeeded":
      return "Tamamlandı";
    case "failed":
      return "Başarısız";
    default:
      return status;
  }
}

export function AdminPage() {
  const { data: banks, isLoading: banksLoading } = useBanks();
  const [bankCode, setBankCode] = useState<string>("");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const healthQuery = useQuery({
    queryKey: ["admin-health"],
    queryFn: api.adminHealth,
    refetchInterval: 30_000,
  });

  const jobQuery = useQuery({
    queryKey: ["admin-job", activeJobId],
    queryFn: () => api.adminJob(activeJobId as string),
    enabled: Boolean(activeJobId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "queued" || s === "running" ? 1500 : false;
    },
  });

  const createJob = useMutation({
    mutationFn: api.createAdminJob,
    onSuccess: (job) => {
      setActiveJobId(job.id);
      void queryClient.invalidateQueries({ queryKey: ["admin-job"] });
    },
  });

  useEffect(() => {
    if (banks?.length && !bankCode) {
      setBankCode(banks[0]?.code ?? "");
    }
  }, [banks, bankCode]);

  // TKBB bittiyse katılma hesabı önbelleğini düşür.
  useEffect(() => {
    const job = jobQuery.data;
    if (!job || job.status !== "succeeded") return;
    if (job.kind === "tkbb" || job.kind === "tkbb_seed") {
      void queryClient.invalidateQueries({ queryKey: ["katilim-hesabi"] });
    }
  }, [jobQuery.data, queryClient]);

  const busy =
    createJob.isPending ||
    jobQuery.data?.status === "queued" ||
    jobQuery.data?.status === "running";

  const run = (kind: AdminJobKind, needsBank: boolean) => {
    createJob.mutate({
      kind,
      bank_code: needsBank ? bankCode || null : null,
    });
  };

  const groups: ActionDef["group"][] = ["banka", "tumu", "katilma", "sistem"];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Admin</h1>
        <p className="mt-1 text-sm text-text-500">
          Sağlık, scrape ve TKBB güncelleme. Kimlik doğrulama yok — yalnızca yerel
          demo. İşler sırayla çalışır (aynı anda tek job).
        </p>
      </div>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-900">Sistem sağlığı</h2>
        {healthQuery.isLoading && <LoadingState variant="cards" />}
        {healthQuery.isError && (
          <ErrorState error={healthQuery.error} title="Sağlık okunamadı" />
        )}
        {healthQuery.data && (
          <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-text-500">Durum</dt>
              <dd className="font-medium text-text-900">{healthQuery.data.status}</dd>
            </div>
            <div>
              <dt className="text-text-500">Sürüm</dt>
              <dd className="font-medium text-text-900">{healthQuery.data.version}</dd>
            </div>
            <div>
              <dt className="text-text-500">Veritabanı</dt>
              <dd className="font-medium text-text-900">
                {healthQuery.data.db_ok ? "Bağlı" : "Hata"}
              </dd>
            </div>
            <div>
              <dt className="text-text-500">Kampanya sayısı</dt>
              <dd className="font-medium text-text-900">{healthQuery.data.campaign_count}</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="space-y-4 rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-900">İşler</h2>
        <div className="max-w-xs">
          <label className="mb-1 block text-xs text-text-500">Banka (seçili banka işleri için)</label>
          {banksLoading ? (
            <p className="text-sm text-text-500">Bankalar yükleniyor…</p>
          ) : (
            <Select value={bankCode} onValueChange={setBankCode}>
              <SelectTrigger>
                <SelectValue placeholder="Banka seçin" />
              </SelectTrigger>
              <SelectContent>
                {(banks ?? []).map((b) => (
                  <SelectItem key={b.code} value={b.code}>
                    {b.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {groups.map((group) => (
          <div key={group} className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-text-500">
              {GROUP_LABEL[group]}
            </h3>
            <div className="grid gap-3 sm:grid-cols-2">
              {ACTIONS.filter((a) => a.group === group).map((a) => (
                <div
                  key={a.kind}
                  className="flex flex-col rounded-lg border border-border px-3 py-3"
                >
                  <p className="text-sm font-medium text-text-900">{a.label}</p>
                  <p className="mt-1 flex-1 text-xs text-text-500">{a.hint}</p>
                  <Button
                    type="button"
                    size="sm"
                    className="mt-3 self-start"
                    disabled={busy || (a.needsBank && !bankCode)}
                    onClick={() => run(a.kind, a.needsBank)}
                  >
                    Çalıştır
                  </Button>
                </div>
              ))}
            </div>
          </div>
        ))}

        {createJob.isError && (
          <ErrorState error={createJob.error} title="İş başlatılamadı" />
        )}
      </section>

      {activeJobId && (
        <section className="rounded-lg border border-border bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-text-900">Son iş çıktısı</h2>
            {jobQuery.data && (
              <span className="text-xs text-text-500">
                {statusLabel(jobQuery.data.status)}
                {jobQuery.data.exit_code != null ? ` · kod ${jobQuery.data.exit_code}` : ""}
              </span>
            )}
          </div>
          {jobQuery.data?.summary && (
            <p className="mt-2 text-sm font-medium text-brand-800">{jobQuery.data.summary}</p>
          )}
          {jobQuery.data?.error && (
            <p className="mt-2 text-sm text-warn-600">{jobQuery.data.error}</p>
          )}
          {(jobQuery.data?.kind === "tkbb" || jobQuery.data?.kind === "tkbb_seed") &&
            jobQuery.data.status === "succeeded" && (
              <p className="mt-2 text-sm text-text-700">
                Oranlar yazıldı.{" "}
                <Link to="/katilim-hesabi" className="font-medium text-brand-700 hover:underline">
                  Katılım Hesabı
                </Link>{" "}
                sayfasını açarak kontrol edin (önbellek temizlendi).
              </p>
            )}
          <p className="mt-2 font-mono text-[11px] text-text-500">
            {(jobQuery.data?.command ?? []).join(" ")}
          </p>
          <pre className="mt-3 max-h-80 overflow-auto rounded border border-border bg-neutral-50 p-3 text-xs leading-relaxed text-text-900">
            {jobQuery.data?.log || (busy ? "Çıktı bekleniyor…" : "Log yok.")}
          </pre>
        </section>
      )}
    </div>
  );
}
