import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Add MRP Functional Expert Consultant prompt and assistant.

    Also reorganises data/ into subfolders (seed/, storage/, prompts/, assistants/).
    No schema changes — new records are loaded via data files.
    """
    _logger.info("ordomatics_setup 18.0.1.0.7: MRP consultant assistant installed")
