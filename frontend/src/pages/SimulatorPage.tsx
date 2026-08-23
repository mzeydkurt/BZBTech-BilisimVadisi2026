import { useState } from "react";

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
import { useBddkCheck, useFinancingSimulation, useYieldSimulation } from "@/hooks/useSimulator";

const DEFAULT_FINANCING_FORM: FinancingFormState = {
  amount_try: "500000",
  term_months: "36",
  product_type: "tasit_finansmani",
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

export function SimulatorPage() {
  const [financingForm, setFinancingForm] = useState<FinancingFormState>(DEFAULT_FINANCING_FORM);
  const [yieldForm, setYieldForm] = useState<YieldFormState>(DEFAULT_YIELD_FORM);
  const [bddkForm, setBddkForm] = useState<BddkFormState>(DEFAULT_BDDK_FORM);

  const financingSimulation = useFinancingSimulation();
  const yieldSimulation = useYieldSimulation();
  const bddkCheck = useBddkCheck();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Simülatör</h1>
        <p className="mt-1 text-sm text-text-500">
          Taksit, katılma getirisi ve BDDK finansman limiti hesaplayıcıları.
        </p>
      </div>

      <Tabs defaultValue="financing">
        <TabsList>
          <TabsTrigger value="financing">Taksit</TabsTrigger>
          <TabsTrigger value="yield">Getiri</TabsTrigger>
          <TabsTrigger value="bddk">BDDK</TabsTrigger>
        </TabsList>

        <TabsContent value="financing" className="space-y-4">
          <FinancingForm
            value={financingForm}
            onChange={setFinancingForm}
            isPending={financingSimulation.isPending}
            onSubmit={() =>
              financingSimulation.mutate({
                amount_try: financingForm.amount_try,
                term_months: Number(financingForm.term_months),
                product_type: financingForm.product_type,
              })
            }
          />
          {financingSimulation.isPending && <LoadingState variant="table" />}
          {financingSimulation.isError && <ErrorState error={financingSimulation.error} />}
          {financingSimulation.isSuccess && (
            <FinancingResults result={financingSimulation.data} />
          )}
        </TabsContent>

        <TabsContent value="yield" className="space-y-4">
          <YieldForm
            value={yieldForm}
            onChange={setYieldForm}
            isPending={yieldSimulation.isPending}
            onSubmit={() =>
              yieldSimulation.mutate({
                deposit_try: yieldForm.deposit_try,
                term_days: Number(yieldForm.term_days),
                currency: yieldForm.currency,
              })
            }
          />
          {yieldSimulation.isPending && <LoadingState variant="table" />}
          {yieldSimulation.isError && <ErrorState error={yieldSimulation.error} />}
          {yieldSimulation.isSuccess && <YieldResults result={yieldSimulation.data} />}
        </TabsContent>

        <TabsContent value="bddk" className="space-y-4">
          <BddkCheckForm
            value={bddkForm}
            onChange={setBddkForm}
            isPending={bddkCheck.isPending}
            onSubmit={() =>
              bddkCheck.mutate({
                asset_type: bddkForm.asset_type,
                asset_value_try: bddkForm.asset_value_try,
                energy_class: bddkForm.asset_type === "konut" ? bddkForm.energy_class : null,
                first_home: bddkForm.asset_type === "konut" ? bddkForm.first_home : null,
              })
            }
          />
          {bddkCheck.isPending && <LoadingState variant="table" />}
          {bddkCheck.isError && <ErrorState error={bddkCheck.error} />}
          {bddkCheck.isSuccess && <BddkCheckResult result={bddkCheck.data} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}
