# Dockerfile production-ready para WhatsApp Baileys sidecar.
# Funciona em Railway, Render, Fly.io etc.
FROM node:20-alpine

WORKDIR /app

# Copia primeiro package.json pra otimizar cache de build
COPY package.json ./

# Instala dependências de produção (Baileys 7 não precisa mais de compiladores
# nativos — não instalamos python3/make/g++ pra economizar memória no build)
RUN npm install --omit=dev --no-audit --no-fund \
    && npm cache clean --force

# Copia o restante do código
COPY server.js ./

# Defaults pra produção (override via env vars do Railway/Render)
ENV WA_HOST=0.0.0.0 \
    WA_AUTH_DIR=/data/auth_info \
    NODE_ENV=production

# Cria diretório do volume persistente (será montado em runtime)
RUN mkdir -p /data/auth_info

EXPOSE 3002

# Healthcheck (Railway/Render usam isso)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT:-3002}/health || exit 1

CMD ["node", "server.js"]
