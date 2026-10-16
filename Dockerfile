# Imagem base oficial do uv com Python 3.12 slim para construcao rapida
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Define o diretorio de trabalho para compilacao de dependencias
WORKDIR /app

# Habilita compilacao antecipada de bytecode
ENV UV_COMPILE_BYTECODE=1

# Copia apenas as definicoes de dependencias para aproveitar cache de camadas
COPY pyproject.toml uv.lock ./

# Instala apenas dependencias de producao (sem extras de teste/lint)
RUN uv sync --frozen --no-dev --no-install-project

# Estagio final minimo e seguro para execucao
FROM python:3.12-slim-bookworm

# Instala utilitarios basicos e limpa cache do apt
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Cria usuario de sistema sem privilegios de root
RUN useradd -m -u 1000 -s /bin/bash appuser

# Define o diretorio da aplicacao
WORKDIR /app

# Copia o ambiente virtual pre-compilado do builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copia o codigo-fonte da aplicacao
COPY --chown=appuser:appuser src/ /app/src/

# Configura o PATH para priorizar o ambiente virtual isolado
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Executa com usuario restrito
USER appuser

# Expoe a porta padrao da API
EXPOSE 8000

# Healthcheck interno do container contra o endpoint /health da API
HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=5s \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Inicializa o servidor ASGI Uvicorn em modo de producao
CMD ["uvicorn", "src.app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
