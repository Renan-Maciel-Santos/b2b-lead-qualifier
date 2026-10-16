#!/usr/bin/env bash
# Script de deploy e atualizacao continua na VPS
# Executado diretamente na maquina ou acionado remotamente pelo GitHub Actions via SSH.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/lead-qualifier}"
cd "$APP_DIR"

echo "======================================================"
echo " Lead Qualifier - Deploy Continuo"
echo " Diretorio: $APP_DIR"
echo " Data: $(date -u +"%Y-%m-%d %H:%M:%SZ")"
echo "======================================================"

# Verifica a existencia do arquivo de configuracao essencial
if [ ! -f .env ]; then
    echo "ERRO CRITICO: Arquivo .env nao encontrado em $APP_DIR!"
    echo "Copie .env.example para .env e preencha as senhas e a OPENAI_API_KEY."
    exit 1
fi

# Atualiza o codigo para a versao mais recente da branch main
echo "[1/5] Sincronizando repositorio Git..."
git fetch origin main
git checkout main
git pull --ff-only origin main

# Constrói a imagem da API com as novas alteracoes
echo "[2/5] Compilando imagem Docker da API..."
docker compose build api

# Executa as migracoes pendentes no PostgreSQL
echo "[3/5] Aplicando migracoes de banco de dados..."
docker compose run --rm dbmate up

# Se o parametro --seed foi passado, executa o seed de desenvolvimento/demo
if [ "${1:-}" = "--seed" ]; then
    echo "Populando dados de seed..."
    docker compose exec -T postgres psql -U "${DB_ADMIN_USER:-postgres}" -d "${DB_NAME:-b2b_lead_qualifier}" -f /db/seeds/demo.sql || true
fi

# Reinicia os containers mantendo os volumes de dados intactos
echo "[4/5] Reiniciando containers em producao..."
# Se DOMAIN estiver preenchido no .env, ativa o perfil do Caddy com SSL
if grep -q "^DOMAIN=." .env 2>/dev/null; then
    echo "Perfil com Caddy (SSL automatico) detectado."
    docker compose --profile prod up -d --remove-orphans
else
    echo "Subindo servicos padrao (Postgres + API)."
    docker compose up -d --remove-orphans
fi

# Valida o healthcheck da aplicacao
echo "[5/5] Verificando saude da aplicacao..."
MAX_RETRIES=12
COUNTER=0
HEALTHY=false

while [ $COUNTER -lt $MAX_RETRIES ]; do
    if curl -s -f http://127.0.0.1:8000/health > /dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    COUNTER=$((COUNTER + 1))
    echo "Aguardando API responder (tentativa $COUNTER/$MAX_RETRIES)..."
    sleep 3
done

if [ "$HEALTHY" = true ]; then
    echo "======================================================"
    echo " Deploy finalizado com sucesso! API online e saudavel."
    echo "======================================================"
    # Limpa imagens antigas orfas para economizar espaco em disco da VPS
    docker image prune -f > /dev/null 2>&1 || true
else
    echo "ERRO: A API nao respondeu ao healthcheck apos $MAX_RETRIES tentativas."
    echo "Logs do container b2b_api:"
    docker compose logs --tail=50 api
    exit 1
fi
