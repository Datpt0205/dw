# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1 — deps + build (Next.js standalone output)
# ---------------------------------------------------------------------------
FROM node:22-alpine AS builder

RUN corepack enable

WORKDIR /build

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml turbo.json tsconfig.base.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/typescript/ui/package.json packages/typescript/ui/package.json
COPY packages/typescript/contracts/package.json packages/typescript/contracts/package.json
COPY packages/typescript/api-client/package.json packages/typescript/api-client/package.json
COPY packages/typescript/agent-ui/package.json packages/typescript/agent-ui/package.json

RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY packages/typescript packages/typescript
COPY apps/web apps/web

# NEXT_PUBLIC_* are inlined at build time, so they must be present here (not just
# at runtime). Compose passes them as build args; defaults suit local Docker.
ARG NEXT_PUBLIC_AUTH_MODE=oidc
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_KEYCLOAK_URL=http://localhost:8080
ARG NEXT_PUBLIC_KEYCLOAK_REALM=dw
ARG NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=dw-web
ENV NEXT_PUBLIC_AUTH_MODE=$NEXT_PUBLIC_AUTH_MODE \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_KEYCLOAK_URL=$NEXT_PUBLIC_KEYCLOAK_URL \
    NEXT_PUBLIC_KEYCLOAK_REALM=$NEXT_PUBLIC_KEYCLOAK_REALM \
    NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=$NEXT_PUBLIC_KEYCLOAK_CLIENT_ID

ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_OPTIONS=--max-old-space-size=4096
# Persist Next.js's incremental compiler cache across builds so a rebuild after
# a code change recompiles only what changed (typically 2–5× faster) instead of
# starting from scratch. The mount only holds .next/cache; the standalone/static
# output is still produced fresh each build.
RUN --mount=type=cache,target=/build/apps/web/.next/cache \
    pnpm --filter @dw/web build

# ---------------------------------------------------------------------------
# Stage 2 — runtime: non-root standalone server
# ---------------------------------------------------------------------------
FROM node:22-alpine AS runtime

RUN addgroup -g 1001 dw && adduser -u 1001 -G dw -D dw

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder --chown=dw:dw /build/apps/web/.next/standalone ./
COPY --from=builder --chown=dw:dw /build/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=dw:dw /build/apps/web/public ./apps/web/public

USER dw
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "apps/web/server.js"]
