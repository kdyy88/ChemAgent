ARG NODE_IMAGE=node:20-alpine

FROM ${NODE_IMAGE} AS deps

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile


FROM ${NODE_IMAGE} AS builder

WORKDIR /app

ARG NEXT_PUBLIC_WS_URL

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NODE_ENV=production
ENV NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_OPTIONS="--max-old-space-size=1024"

RUN corepack enable && pnpm build


FROM ${NODE_IMAGE} AS runner

ARG NEXT_PUBLIC_WS_URL

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=80 \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Ensure `curl` is available for healthchecks in the runtime image
RUN apk add --no-cache curl

EXPOSE 80

CMD ["node", "server.js"]