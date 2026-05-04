import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Switch Nomic provider from service=openai to service=nomic.

    llm_nomic now handles the /v1/embedding/text endpoint natively;
    the openai service was hitting /v1/embeddings which Nomic doesn't serve.
    """
    cr.execute("""
        UPDATE llm_provider
           SET service = 'nomic',
               api_base = NULL
         WHERE name = 'Nomic'
           AND service = 'openai'
    """)
    if cr.rowcount:
        _logger.info("ordomatics 18.0.1.0.6: migrated Nomic provider to service=nomic (%d row)", cr.rowcount)
