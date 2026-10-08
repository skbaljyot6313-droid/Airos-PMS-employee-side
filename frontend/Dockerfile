# AiROS Staff web bundle — Vite build + express static host (server.ts)
FROM node:20-alpine
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked into the JS bundle at build time — public API base, never a secret.
ARG VITE_API_URL=https://airos-backend-production.up.railway.app/api/v1
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

ENV NODE_ENV=production
ENV PORT=3000
EXPOSE ${PORT}
CMD npx tsx server.ts
