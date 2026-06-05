# Build arg: see backend.Dockerfile for details. Default empty = Docker Hub.
ARG REGISTRY=

# --- builder ---
FROM ${REGISTRY}node:22-slim AS builder

WORKDIR /app

COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY web/ ./

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runtime ---
FROM ${REGISTRY}node:22-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# We dropped Next.js standalone output mode because its CSS pipeline silently
# emitted no stylesheets in our setup. Bundle full node_modules instead — the
# image is ~250 MB but pages render with styling.
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs

RUN groupadd --system --gid 1001 nodejs && \
    useradd --system --uid 1001 --gid 1001 nextjs && \
    chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000

CMD ["npx", "next", "start", "-p", "3000", "-H", "0.0.0.0"]
