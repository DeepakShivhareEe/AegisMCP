FROM node:22-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json* ./
# Prefer the lockfile for reproducible installs; fall back when it is absent.
RUN npm ci || npm install

COPY . .

# NEXT_PUBLIC_* values are inlined by `next build`, so the API URL must exist at
# build time. Passing it only at runtime leaves the bundle pointing at localhost.
# Compose/Vercel must pass: --build-arg NEXT_PUBLIC_API_URL=https://<api-host>
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

CMD ["npm", "start"]
