import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import {
  BddkCheckForm,
  type BddkFormState,
} from "@/components/simulator/BddkCheckForm";
import { BddkCheckResult } from "@/components/simulator/BddkCheckResult";
import {
  FinancingForm,
  type FinancingFormState,
} from "@/components/simulator/FinancingForm";
import { FinancingResults } from "@/components/simulator/FinancingResults";
import { YieldForm, type YieldFormState } from "@/components/simulator/YieldForm";
import { YieldResults } from "@/components/simulator/YieldResults";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useBanks } from "@/hooks/useBanks";
import { ApiError, api } from "@/lib/api";
import type {
  BDDKLimitCheckResponse,
  FinancingSimulationResponse,
  ParticipationYieldResponse,
} from "@/types/api";

const DEFAULT_FINANCING_FORM: FinancingFormState = {
  amount_try: "400000",
  term_months: "48",
  product_type: "tasit_finansmani",
  bank_codes: [],
};

const DEFAULT_YIELD_FORM: YieldFormState = {
  deposit_try: "100000",
  term_days: "365",
  currency: "TRY",
};

const DEFAULT_BDDK_FORM: BddkFormState = {
  asset_type: "konut",
  asset_value_try: "5000000",
  energy_class: "A",
  first_home: true,
};

function financingFromParams(params: URLSearchParams): FinancingFormState {
  const amount = params.get("amount");
  const term = params.get("term");
  const productType = params.get("product_type");
  const bank = params.get("bank");
  return {
    ...DEFAULT_FINANCING_FORM,
    amount_try: amount && Number(amount) > 0 ? amount : DEFAULT_FINANCING_FORM.amount_try,
    term_months: term && Number(term) > 0 ? term : DEFAULT_FINANCING_FORM.term_months,
    product_type:
      productType === "tasit_finansmani" ||
      productType === "konut_finansmani" ||
      productType === "ihtiyac_finansmani"
        ? productType
        : DEFAULT_FINANCING_FORM.product_type,
    bank_codes: bank ? [bank] : [],
  };
}

function yieldFromParams(params: URLSearchParams): YieldFormState {
  const deposit = params.get("deposit");
  const termDays = params.get("term_days");
  const currency = params.get("currency");
  return {
    ...DEFAULT_YIELD_FORM,
    deposit_try: deposit && Number(deposit) > 0 ? deposit : DEFAULT_YIELD_FORM.deposit_try,
    term_days:
      termDays && Number(termDays) > 0 ? termDays : DEFAULT_YIELD_FORM.term_days,
    currency:
      currency === "TRY" ||
      currency === "USD" ||
      currency === "EUR" ||
      currency === "XAU" ||
      currency === "XAG"
        ? currency
        : DEFAULT_YIELD_FORM.currency,
  };
}

function bddkFromParams(params: URLSearchParams): BddkFormState {
  const assetType = params.get("asset_type");
  const assetValue = params.get("asset_value");
  const energy = params.get("energy_class");
  const firstHome = params.get("first_home");
  return {
    ...DEFAULT_BDDK_FORM,
    asset_type:
      assetType === "tasit" || assetType === "konut" || assetType === "ihtiyac"
        ? assetType
        : DEFAULT_BDDK_FORM.asset_type,
    asset_value_try:
      assetValue && Number(assetValue) > 0
        ? assetValue
        : DEFAULT_BDDK_FORM.asset_value_try,
    energy_class:
      energy === "A" || energy === "B" || energy === "C" || energy === "DIGER"
        ? energy === "B"
          ? "A"
          : energy
        : DEFAULT_BDDK_FORM.energy_class,
    first_home:
      firstHome === "false" ? false : firstHome === "true" ? true : DEFAULT_BDDK_FORM.first_home,
  };
}

function tabFromParams(params: URLSearchParams): string {
  const tab = params.get("tab");
  if (tab === "financing" || tab === "yield" || tab === "bddk") return tab;
  return "financing";
}

function toError(err: unknown): Error {
  if (err instanceof ApiError) return err;
  if (err instanceof Error) return err;
  return new Error(String(err));
}

export function SimulatorPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState(() => tabFromParams(searchParams));
  const [financingForm, setFinancingForm] = useState<FinancingFormState>(() =>
    financingFromParams(searchParams),
  );
  const [yieldForm, setYieldForm] = useState<YieldFormState>(() =>
    yieldFromParams(searchParams),
  );
  const [bddkForm, setBddkForm] = useState<BddkFormState>(() => bddkFromParams(searchParams));

  const [financingLoading, setFinancingLoading] = useState(false);
  const [financingError, setFinancingError] = useState<Error | null>(null);
  const [financingResult, setFinancingResult] = useState<FinancingSimulationResponse | null>(
    null,
  );

  const [yieldLoading, setYieldLoading] = useState(false);
  const [yieldError, setYieldError] = useState<Error | null>(null);
  const [yieldResult, setYieldResult] = useState<ParticipationYieldResponse | null>(null);

  const [bddkLoading, setBddkLoading] = useState(false);
  const [bddkError, setBddkError] = useState<Error | null>(null);
  const [bddkResult, setBddkResult] = useState<BDDKLimitCheckResponse | null>(null);

  const { data: banks } = useBanks();
  const autorunKeyRef = useRef<string | null>(null);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const runFinancing = async (form: FinancingFormState = financingForm) => {
    const amount = String(form.amount_try).replace(/\s/g, "").replace(",", ".");
    const term = Number(form.term_months);
    if (!amount || Number(amount) <= 0 || !Number.isFinite(term) || term <= 0) {
      setFinancingError(new Error("Geçerli tutar ve vade girin."));
      return;
    }
    setFinancingLoading(true);
    setFinancingError(null);
    try {
      const data = await api.simulateFinancing({
        amount_try: amount,
        term_months: term,
        product_type: form.product_type,
        bank_codes: form.bank_codes.length > 0 ? form.bank_codes : undefined,
      });
      if (!aliveRef.current) return;
      setFinancingResult(data);
    } catch (err) {
      if (!aliveRef.current) return;
      setFinancingResult(null);
      setFinancingError(toError(err));
    } finally {
      if (aliveRef.current) setFinancingLoading(false);
    }
  };

  const runYield = async (form: YieldFormState = yieldForm) => {
    setYieldLoading(true);
    setYieldError(null);
    try {
      const data = await api.simulateYield({
        deposit_try: form.deposit_try,
        term_days: Number(form.term_days),
        currency: form.currency,
      });
      if (!aliveRef.current) return;
      setYieldResult(data);
    } catch (err) {
      if (!aliveRef.current) return;
      setYieldResult(null);
      setYieldError(toError(err));
    } finally {
      if (aliveRef.current) setYieldLoading(false);
    }
  };

  const runBddk = async (form: BddkFormState = bddkForm) => {
    setBddkLoading(true);
    setBddkError(null);
    try {
      const data = await api.checkBddkLimit({
        asset_type: form.asset_type,
        asset_value_try: form.asset_value_try,
        energy_class: form.asset_type === "konut" ? form.energy_class : null,
        first_home: form.asset_type === "konut" ? form.first_home : null,
      });
      if (!aliveRef.current) return;
      setBddkResult(data);
    } catch (err) {
      if (!aliveRef.current) return;
      setBddkResult(null);
      setBddkError(toError(err));
    } finally {
      if (aliveRef.current) setBddkLoading(false);
    }
  };

  // Sohbet deeplink: formu doldur, autorun'u URL'den düş, bir kez hesapla.
  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    if (params.get("autorun") !== "1") return;

    const key = params.toString();
    if (autorunKeyRef.current === key) return;
    autorunKeyRef.current = key;

    const t = tabFromParams(params);
    setTab(t);

    // Tekrar tetiklenmesin diye autorun bayrağını kaldır.
    const cleaned = new URLSearchParams(params);
    cleaned.delete("autorun");
    setSearchParams(cleaned, { replace: true });

    if (t === "financing") {
      const form = financingFromParams(params);
      setFinancingForm(form);
      void runFinancing(form);
      return;
    }
    if (t === "yield") {
      const form = yieldFromParams(params);
      setYieldForm(form);
      void runYield(form);
      return;
    }
    if (t === "bddk") {
      const form = bddkFromParams(params);
      setBddkForm(form);
      if (Number(form.asset_value_try) > 0) void runBddk(form);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Simülatör</h1>
        <p className="mt-1 text-sm text-text-500">
          Bankaların güncel kâr payı oranlarıyla finansman taksitlerini hesaplayın, katılma hesabı
          getirilerini simüle edin ve yasal BDDK limitlerini sorgulayın.
        </p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="financing">Finansman Hesaplama</TabsTrigger>
          <TabsTrigger value="yield">Katılma Hesabı Getirisi</TabsTrigger>
          <TabsTrigger value="bddk">BDDK Limit Sorgulama</TabsTrigger>
        </TabsList>

        <TabsContent value="financing" className="space-y-4" forceMount>
          <div className={tab === "financing" ? "block" : "hidden"}>
            <FinancingForm
              value={financingForm}
              onChange={setFinancingForm}
              banks={banks ?? []}
              isPending={financingLoading}
              onSubmit={() => void runFinancing()}
            />
            {financingLoading && <LoadingState variant="table" />}
            {financingError && <ErrorState error={financingError} />}
            {!financingLoading && financingResult && (
              <FinancingResults result={financingResult} />
            )}
          </div>
        </TabsContent>

        <TabsContent value="yield" className="space-y-4" forceMount>
          <div className={tab === "yield" ? "block" : "hidden"}>
            <YieldForm
              value={yieldForm}
              onChange={setYieldForm}
              isPending={yieldLoading}
              onSubmit={() => void runYield()}
            />
            {yieldLoading && <LoadingState variant="table" />}
            {yieldError && <ErrorState error={yieldError} />}
            {!yieldLoading && yieldResult && (
              <YieldResults
                result={yieldResult}
                onLadderSelect={(termDays) => {
                  const next = { ...yieldForm, term_days: String(termDays) };
                  setYieldForm(next);
                  void runYield(next);
                }}
              />
            )}
          </div>
        </TabsContent>

        <TabsContent value="bddk" className="space-y-4" forceMount>
          <div className={tab === "bddk" ? "block" : "hidden"}>
            <BddkCheckForm
              value={bddkForm}
              onChange={setBddkForm}
              isPending={bddkLoading}
              onSubmit={() => void runBddk()}
            />
            {bddkLoading && <LoadingState variant="table" />}
            {bddkError && <ErrorState error={bddkError} />}
            {!bddkLoading && bddkResult && <BddkCheckResult result={bddkResult} />}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
