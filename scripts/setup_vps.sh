#!/usr/bin/env bash
# Script de preparacao inicial para VPS Ubuntu 22.04 / 24.04 ou Debian 12
# Uso: curl -fsSL https://raw.githubusercontent.com/.../scripts/setup_vps.sh | bash
# Ou execute diretamente na VPS: sudo bash scripts/setup_vps.sh

set -euo pipefail

echo "======================================================"
echo " B2B Lead Qualifier - Setup de VPS Linux (Docker)"
echo "======================================================"

# Verifica se o script esta rodando como root
if [ "$EUID" -ne 0 ]; then
    echo "ERRO: Por favor, execute este script como root ou com sudo."
    exit 1
fi

# Atualiza listas de pacotes do sistema operacional
echo "[1/5] Atualizando pacotes do sistema..."
apt-get update -y && apt-get upgrade -y

# Instala ferramentas essenciais
echo "[2/5] Instalando utilitarios essenciais..."
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    git \
    ufw \
    jq

# Instala repositorio oficial do Docker
echo "[3/5] Instalando Docker Engine e Docker Compose Plugin..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc 2>/dev/null || \
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc

chmod a+r /etc/apt/keyrings/docker.asc

# Detecta distribuicao linux
DISTRO=$(. /etc/os-release && echo "$ID")
VERSION_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$DISTRO \
  $VERSION_CODENAME stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Inicia e habilita o servico do Docker na inicializacao
systemctl enable --now docker

# Adiciona o usuario nao-root atual (se houver SUDO_USER) ao grupo docker
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    usermod -aG docker "$SUDO_USER"
    echo "Usuario $SUDO_USER adicionado ao grupo docker."
fi

# Configura o firewall UFW
echo "[4/5] Configurando firewall UFW (Portas 22, 80, 443)..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP / Let''s Encrypt'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 QUIC'
# Habilita o firewall sem bloquear a sessao SSH ativa
ufw --force enable

# Cria o diretorio padrao da aplicacao em /opt
echo "[5/5] Criando diretorio da aplicacao em /opt/lead-qualifier..."
APP_DIR="/opt/lead-qualifier"
mkdir -p "$APP_DIR"
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    chown -R "$SUDO_USER":"$SUDO_USER" "$APP_DIR"
fi

echo "======================================================"
echo " Setup concluido com sucesso!"
echo " Docker instalado: $(docker --version)"
echo " Compose plugin: $(docker compose version)"
echo " Diretorio pronto: $APP_DIR"
echo "======================================================"
echo "Proximos passos na VPS:"
echo " 1. cd $APP_DIR"
echo " 2. git clone <url-do-repositorio> ."
echo " 3. cp .env.example .env && nano .env"
echo " 4. docker compose up -d"
echo "======================================================"
