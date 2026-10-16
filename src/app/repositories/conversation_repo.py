import json
from uuid import UUID

# Importa a conexao assincrona e a fabrica de dicionarios do psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row


# Cria a classe responsavel por falar com o banco de dados sobre as conversas (Repositorio)
class ConversationRepository:
    """Gerencia a persistencia de conversas, idempotencia e scoring no banco de dados."""

    # Recebe a conexao ativa do banco ao ser instanciado pelo controller
    def __init__(self, conn: AsyncConnection):
        # Guarda a conexao para ser usada pelos metodos
        self.conn = conn

    # Metodo que verifica se a mensagem especifica do WhatsApp ja foi processada (Idempotencia)
    async def is_message_processed(self, message_id: str) -> bool:
        """Verifica se a mensagem ja foi processada para evitar duplicidade."""
        # Inicia o cursor instruindo o psycopg a retornar linhas como dicionarios
        async with self.conn.cursor(row_factory=dict_row) as cur:
            # Faz uma consulta rapida procurando o ID na tabela de mensagens processadas
            # Como o search_path e o RLS estao ativos, o banco consulta no schema isolado do tenant
            await cur.execute(
                "SELECT 1 FROM processed_messages WHERE message_id = %s",
                (message_id,),
            )
            # Tenta pegar a primeira (e unica) linha de resultado
            result = await cur.fetchone()
            # Retorna booleano True se achar a mensagem (duplicada), ou False se for inedita
            return result is not None

    # Metodo que registra uma nova mensagem como processada, salvando no banco de dados
    async def mark_message_processed(self, message_id: str):
        """Registra a mensagem na tabela de idempotencia do tenant."""
        # Inicia o cursor
        async with self.conn.cursor() as cur:
            # Insere o ID da mensagem na tabela de idempotencia do banco
            # O campo 'tenant_id' e preenchido automaticamente pelo banco devido ao valor DEFAULT na tabela
            await cur.execute(
                "INSERT INTO processed_messages (message_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (message_id,),
            )

    # Busca a versao ativa das regras de qualificacao de leads cadastrada para o tenant
    async def get_active_scoring_rule_set(self) -> dict | None:
        """Recupera o conjunto de regras de scoring ativo para o tenant."""
        # Inicia o cursor com retorno em dicionario
        async with self.conn.cursor(row_factory=dict_row) as cur:
            # Busca a versao ativa de scoring do tenant
            await cur.execute(
                """
                SELECT id, version, rules, qualification_threshold
                FROM scoring_rule_sets
                WHERE is_active = true
                LIMIT 1
                """
            )
            # Retorna o registro com id, versao e regras em JSONB, ou None caso ainda nao cadastrado
            return await cur.fetchone()

    # Metodo para salvar a pontuacao final do lead na tabela de resultados
    async def save_scoring_result(
        self,
        phone_number: str,
        rule_set_id: str | UUID,
        final_score: int,
        is_qualified: bool,
        audit_trail: list[str],
    ):
        """Salva a decisao append-only de qualificacao associada a versao exata de regras."""
        # Inicia o cursor
        async with self.conn.cursor() as cur:
            # Insere o resultado do scoring no banco com FK composta amarrada a versao de regras
            await cur.execute(
                """
                INSERT INTO scoring_results (
                    phone_number,
                    rule_set_id,
                    final_score,
                    is_qualified,
                    audit_trail
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (phone_number, str(rule_set_id), final_score, is_qualified, json.dumps(audit_trail)),
            )
