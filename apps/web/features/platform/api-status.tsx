"use client";

import { useEffect, useState } from "react";
import { ApiClient } from "@dw/api-client";
import type { ReadinessResponse } from "@dw/contracts";
import { Card, CardContent, CardHeader, CardTitle } from "@dw/ui";

const client = new ApiClient({
  baseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
});

type Status =
  | { kind: "loading" }
  | { kind: "ok"; readiness: ReadinessResponse }
  | { kind: "error"; message: string };

export function ApiStatus() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    client
      .getReadiness()
      .then((readiness) => {
        if (!cancelled) setStatus({ kind: "ok", readiness });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setStatus({
            kind: "error",
            message: error instanceof Error ? error.message : "unknown error",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Card className="max-w-3xl">
      <CardHeader>
        <CardTitle>API status</CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {status.kind === "loading" && <span>Đang kiểm tra…</span>}
        {status.kind === "error" && (
          <span className="text-red-600">
            Không kết nối được API: {status.message}
          </span>
        )}
        {status.kind === "ok" && (
          <ul className="space-y-1">
            <li>
              Trạng thái: <strong>{status.readiness.status}</strong>
            </li>
            {Object.entries(status.readiness.checks).map(([name, state]) => (
              <li key={name}>
                {name}: <strong>{state}</strong>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
