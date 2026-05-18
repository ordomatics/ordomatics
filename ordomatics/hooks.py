import logging
import os

_logger = logging.getLogger(__name__)


def _setup_nomic_embedding(env):
    """Configure Nomic as the embedding provider using their OpenAI-compatible API.

    Reads:
      NOMIC_API_KEY     → api_key on the Nomic llm.provider record
      OLLAMA_API_BASE   → fallback for self-hosted Ollama (legacy)

    Creates (idempotent):
      - llm.provider  "Nomic"  service=nomic
      - llm.model     "nomic-embed-text-v1.5"  model_use=embedding  default=True
    """
    if env.get("llm.provider") is None:
        return

    api_key = os.environ.get("NOMIC_API_KEY", "").strip()
    if not api_key:
        api_base = os.environ.get("OLLAMA_API_BASE", "").strip()
        if api_base:
            env["ir.config_parameter"].sudo().set_param("llm_skills.ollama_api_base", api_base)
            _logger.info("ordomatics: NOMIC_API_KEY not set — using Ollama at %s", api_base)
        else:
            _logger.info("ordomatics: NOMIC_API_KEY not set — skipping embedding provider setup")
        return

    NOMIC_MODEL = "nomic-embed-text-v1.5"

    provider = env["llm.provider"].search([("name", "=", "Nomic")], limit=1)
    if not provider:
        provider = env["llm.provider"].sudo().create({
            "name": "Nomic",
            "service": "nomic",
            "api_key": api_key,
            "active": True,
        })
        _logger.info("ordomatics: created Nomic provider (id=%s)", provider.id)
    else:
        provider.sudo().write({"api_key": api_key, "service": "nomic", "api_base": False})
        _logger.info("ordomatics: updated Nomic provider (id=%s)", provider.id)

    model = env["llm.model"].search([
        ("provider_id", "=", provider.id),
        ("name", "=", NOMIC_MODEL),
    ], limit=1)
    if not model:
        env["llm.model"].sudo().create({
            "name": NOMIC_MODEL,
            "provider_id": provider.id,
            "model_use": "embedding",
            "default": True,
            "active": True,
        })
        _logger.info("ordomatics: registered embedding model '%s'", NOMIC_MODEL)

    _logger.info("ordomatics: Nomic embedding provider configured (%s)", NOMIC_MODEL)


def run_bootstrap(env):
    _setup_nomic_embedding(env)


def post_init_hook(env):
    run_bootstrap(env)
