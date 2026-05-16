# Dockerfile — production-ready WhatsApp Baileys sidecar
# Funciona em Railway, Render, Fly.io, qualquer plataforma que rode Docker.
FROM node:20-alpine

# Diretório de trabalho
WORKDIR /app

# Dependências de sistema mínimas pro Baileys (libsignal, libcrypto)
RUN apk add --no-cache python3 make g++ \
    && rm -rf /var/cache/apk/*

# Copia somente arquivos de dependência primeiro (cache de build)
COPY package.json yarn.lock ./

# Instala deps de produção (yarn install é mais determinístico que npm)
RUN yarn install --frozen-lockfile --production --network-timeout 600000 \
    && yarn cache clean

# Copia o restante do código
COPY server.js ./

# Cria diretório de auth e força bind em 0.0.0.0 em produção
ENV WA_HOST=0.0.0.0 \
    WA_AUTH_DIR=/data/auth_info \
    NODE_ENV=production

# IMPORTANTE: monte um volume persistente em /data para preservar a sessão
# do WhatsApp entre redeploys (senão você precisa escanear o QR toda vez).
# Railway: configurar volume em /data
# Render:  Disk persistente em /data
RUN mkdir -p /data/auth_info

EXPOSE 3002

# Healthcheck (Railway/Render/Docker)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT:-3002}/health || exit 1

CMD ["node", "server.js"]
