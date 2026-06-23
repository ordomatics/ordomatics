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


def _setup_chart_of_accounts(env):
    """Create minimal chart of accounts for the sales pipeline.

    Idempotent: skips any account/journal that already exists. Creates:
    - 120000 Accounts Receivable (asset_receivable)
    - 200000 Accounts Payable    (liability_payable)
    - 400000 Product Sales       (income)
    - 500000 Expenses            (expense)
    - Sales journal (INV)

    Also sets the receivable/payable as defaults on the company partner and
    the income account on the root product category.
    """
    Account = env["account.account"]
    Journal = env["account.journal"]

    accounts = {
        "120000": ("Accounts Receivable", "asset_receivable", True),
        "200000": ("Accounts Payable", "liability_payable", True),
        "400000": ("Product Sales", "income", False),
        "500000": ("Expenses", "expense", False),
    }
    created = {}
    for code, (name, account_type, reconcile) in accounts.items():
        existing = Account.search([("code", "=", code)], limit=1)
        if existing:
            created[code] = existing
            continue
        created[code] = Account.create({
            "name": name,
            "code": code,
            "account_type": account_type,
            "reconcile": reconcile,
        })
        _logger.info("ordomatics: created account %s %s", code, name)

    if not Journal.search([("type", "=", "sale")], limit=1):
        Journal.create({"name": "Customer Invoices", "type": "sale", "code": "INV"})
        _logger.info("ordomatics: created Customer Invoices journal")

    if not Journal.search([("type", "=", "purchase")], limit=1):
        Journal.create({"name": "Vendor Bills", "type": "purchase", "code": "BILL"})
        _logger.info("ordomatics: created Vendor Bills journal")

    company_partner = env.company.partner_id
    if company_partner:
        vals = {}
        if not company_partner.property_account_receivable_id:
            vals["property_account_receivable_id"] = created["120000"].id
        if not company_partner.property_account_payable_id:
            vals["property_account_payable_id"] = created["200000"].id
        if vals:
            company_partner.write(vals)
            _logger.info("ordomatics: set default receivable/payable on company partner")

    root_categ = env["product.category"].search(
        [("parent_id", "=", False)], order="id", limit=1
    )
    if root_categ and not root_categ.property_account_income_categ_id:
        root_categ.property_account_income_categ_id = created["400000"].id
        _logger.info("ordomatics: set default income account on root product category")
    if root_categ and not root_categ.property_account_expense_categ_id:
        root_categ.property_account_expense_categ_id = created["500000"].id
        _logger.info("ordomatics: set default expense account on root product category")


def run_bootstrap(env):
    _setup_chart_of_accounts(env)
    _setup_nomic_embedding(env)


def post_init_hook(env):
    run_bootstrap(env)
