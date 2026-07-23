"use client";

import { useEffect, useState } from "react";
import type { Integration } from "@dw/contracts";
import { Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../../lib/session";

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient()
      .listIntegrations()
      .then(setIntegrations)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Integrations</h1>
        <p className="text-xs text-slate-500">
          Tool/connector đã đăng ký trong release hiện tại — đúng những định
          nghĩa mà tool executor cưỡng chế (không thể lệch)
        </p>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {integrations === null && !error && <p className="text-sm">Đang tải…</p>}
      <div className="grid gap-4 md:grid-cols-2">
        {integrations?.map((integration) => (
          <Card key={`${integration.tool}@${integration.version}`}>
            <CardHeader>
              <CardTitle>
                {integration.tool}{" "}
                <span className="font-mono text-xs text-slate-500">
                  v{integration.version}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p>{integration.description}</p>
              <div className="flex flex-wrap gap-1 text-xs">
                <span className="rounded bg-red-100 px-2 py-0.5 text-red-700 dark:bg-red-950 dark:text-red-300">
                  side-effect: {integration.side_effect_level}
                </span>
                <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                  approval: {integration.approval_policy}
                </span>
                {integration.idempotent && (
                  <span className="rounded bg-green-100 px-2 py-0.5 text-green-700 dark:bg-green-950 dark:text-green-300">
                    idempotent
                  </span>
                )}
                <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
                  timeout {integration.timeout_seconds}s
                </span>
              </div>
              <p className="text-xs text-slate-500">
                scopes: {integration.required_scopes.join(", ") || "—"}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
