import { NextResponse } from "next/server";

/** Liveness endpoint used by the container healthcheck. */
export function GET() {
  return NextResponse.json({ status: "ok" });
}
