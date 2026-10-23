# AiROS Staff web bundle — Vite build + express static host (server.ts)
FROM node:20-alpine
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked into the JS bundle at build time — public API base, never a secret.
# Defaults to localhost; pass --build-arg VITE_API_URL=<your-api>/api/v1 for
# real deployments (the old Railway production URL was removed on purpose).
ARG VITE_API_URL=http://localhost:8000/api/v1
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

ENV NODE_ENV=production
ENV PORT=3000
EXPOSE ${PORT}
CMD npx tsx server.ts
