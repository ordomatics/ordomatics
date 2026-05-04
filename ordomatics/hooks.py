import logging
import os

_logger = logging.getLogger(__name__)


def run_bootstrap(env):
    """Configure Ordomatics services from environment variables.

    Split into two groups:
      - Tenant-safe steps run on every DB (infrastructure, cleanup).
      - Canonical-only steps run only on the 'odoo' database (API keys,
        WhatsApp infra, billing, company identity, providers).
    """
    # Always — tenant-safe infrastructure
    _setup_base_url(env)
    _sync_fastapi_endpoints(env)
    _cleanup_stale_attachments(env)
    _recompute_menu_icons(env)
    _setup_s3_storage(env)

    # Canonical DB only — platform-wide configuration
    if not _is_canonical_db(env):
        _logger.info(
            "ordomatics: skipping canonical-only setup for non-canonical DB '%s'",
            env.cr.dbname,
        )
        return
    _load_canonical_data(env)
    _setup_currency_xof(env)
    _setup_company_identity(env)
    _setup_kajande_contacts(env)
    _setup_billing_config(env)
    _sync_billing_product_prices(env)
    _setup_replicate(env)
    _setup_fal_ai(env)
    _setup_whatsapp_account(env)
    _setup_whatsapp_endpoint(env)
    _setup_nomic_embedding(env)
    _setup_wave_provider(env)
    _sync_phone_numbers(env)
    _assign_operators(env)
    _mark_phones_connected(env)
    _opt_in_partners(env)
    _setup_assistants(env)
    _index_catalog_for_search(env)
    _setup_phone_number(env)
    _setup_whatsapp_catalog(env)
    _setup_whatsapp_templates(env)


def _is_canonical_db(env):
    return env.cr.dbname == "odoo"



def _load_canonical_data(env):
    """Load seed data XML files that should only exist in the canonical DB."""
    from pathlib import Path
    from odoo.modules.module import get_module_path
    from odoo.tools.convert import convert_file
    _CANONICAL_DATA_FILES = [
        "data/seed/partners.xml",
        "data/prompts/mrp.xml",
        "data/assistants/mrp.xml",
    ]
    _module_path = get_module_path("ordomatics")
    if not _module_path:
        _logger.warning("ordomatics: module path not found — skipping canonical data load")
        return
    module_root = Path(_module_path)
    for data_file in _CANONICAL_DATA_FILES:
        path = module_root / data_file
        if not path.is_file():
            _logger.warning("ordomatics: canonical data file not found: %s", path)
            continue
        convert_file(env, "ordomatics", data_file, {}, "init", True)

def _setup_s3_storage(env):
    """Configure the fs.storage S3 record if it exists.

    The fs.storage record is created by the XML data file. Its
    use_as_default_for_attachments / force_db_for_default_attachment_rules
    fields are server_env_mixin computed fields — they cannot be set reliably
    via XML.  This hook writes them programmatically after the record exists.

    If FS_FORCE_DB_RULES is set in the environment, use that value; otherwise
    use the OCA default (images <50 KB + JS/CSS in DB, large files to S3).
    """
    storage = env.ref(
        "ordomatics.fs_storage_s3_filestore", raise_if_not_found=False
    )
    if not storage:
        _logger.warning("ordomatics: fs_storage_s3_filestore not found, skipping S3 setup")
        return

    storage.use_as_default_for_attachments = True

    rules = os.environ.get("FS_FORCE_DB_RULES")
    if rules:
        storage.force_db_for_default_attachment_rules = rules
        _logger.info(
            "ordomatics: force_db_for_default_attachment_rules set to %s", rules
        )

    _logger.info("ordomatics: S3 storage enabled as default for attachments")


def _cleanup_stale_attachments(env):
    """Delete stale ir_attachment records that point to a non-existent PVC filestore.

    During fresh module installation, ir_attachment records are created with a
    store_fname but no fs_storage_id or db_datas — before the S3 routing rule
    is applied. These records reference non-existent files and cause errors.
    """
    env.cr.execute("""
        DELETE FROM ir_attachment
        WHERE store_fname IS NOT NULL
          AND fs_storage_id IS NULL
          AND db_datas IS NULL
          AND res_field IS DISTINCT FROM 'web_icon_data'
    """)
    deleted = env.cr.rowcount
    if deleted:
        _logger.info("ordomatics: deleted %d stale PVC-backed attachments", deleted)


def _recompute_menu_icons(env):
    """Recompute web_icon_data for all menus with a web_icon set.

    web_icon_data is a Binary(attachment=True) field whose data lives in
    ir_attachment. On fresh databases these records may be missing or stale.
    Writing web_icon back to itself triggers the ORM compute chain that
    regenerates the attachment data.
    """
    menus = env["ir.ui.menu"].sudo().search([("web_icon", "!=", False)])
    if not menus:
        return
    for menu in menus:
        menu.with_context(prefetch_fields=False).write({"web_icon": menu.web_icon})
    env.cr.commit()
    _logger.info(
        "ordomatics: recomputed web_icon_data for %d menus", len(menus)
    )


def _setup_company_identity(env):
    """Set the base company/admin identity defaults for Ordomatics.

    These are operational defaults, so they should converge on every bootstrap
    rather than relying on Odoo's initial "My Company" placeholders.
    """
    company = env.ref("base.main_company", raise_if_not_found=False)
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    senegal = env.ref("base.sn", raise_if_not_found=False) or env["res.country"].search(
        [("code", "=", "SN")], limit=1
    )

    default_email = os.environ.get("DEFAULT_COMPANY_EMAIL", "").strip() or "admin@ordomatics.com"

    if company:
        vals = {}
        default_name = os.environ.get("DEFAULT_COMPANY_NAME", "Ordomatics").strip() or "Ordomatics"
        if company.name != default_name:
            vals["name"] = default_name
        if company.email != default_email:
            vals["email"] = default_email
        if senegal and company.country_id != senegal:
            vals["country_id"] = senegal.id
        if vals:
            company.write(vals)
            _logger.info("ordomatics: updated base company — %s", list(vals))

    if admin and admin.partner_id:
        vals = {}
        if admin.partner_id.email != default_email:
            vals["email"] = default_email
        if vals:
            admin.partner_id.write(vals)
            _logger.info("ordomatics: updated admin contact — %s", list(vals))


def _setup_currency_xof(env):
    """Activate XOF and set it as the main company currency."""
    xof = env['res.currency'].search([('name', '=', 'XOF')], limit=1)
    if not xof:
        _logger.warning("ordomatics: XOF currency not found in DB — skipping")
        return
    if not xof.active:
        xof.write({'active': True})
        _logger.info("ordomatics: activated XOF currency")
    company = env.ref('base.main_company', raise_if_not_found=False)
    if company and company.currency_id != xof:
        company.write({'currency_id': xof.id})
        _logger.info("ordomatics: company currency set to XOF")


def _setup_billing_config(env):
    """Seed billing ir.config_parameter values from environment variables.

    Runs before _sync_billing_product_prices so prices are computed with the
    correct margin and cost parameters already in place.
    """
    params = env['ir.config_parameter'].sudo()
    mapping = {
        'BILLING_DEFAULT_CREDIT_COST': 'billing_credits.default_cost',
        'BILLING_MINIMUM_TOPUP':       'billing.minimum_topup',
        'BILLING_WELCOME_BONUS':       'billing_credits.welcome_bonus',
        'BILLING_PROFIT':              'billing.profit',
    }
    for env_var, param_key in mapping.items():
        value = os.environ.get(env_var, '').strip()
        if value:
            params.set_param(param_key, value)
            _logger.info("ordomatics: %s → %s = %s", env_var, param_key, value)


def _sync_billing_product_prices(env):
    """Apply profit margin to list_price on all AI Service products.

    standard_price = credit cost (set in data XML).
    list_price = standard_price + billing.profit config param.
    """
    categ = env.ref('billing_products.product_categ_ai_service', raise_if_not_found=False)
    if categ is None:
        return
    products = env['product.template'].search([
        ('categ_id', '=', categ.id),
        ('standard_price', '>', 0),
    ])
    if not products:
        return
    profit = float(
        env['ir.config_parameter'].sudo().get_param('billing.profit', '0')
    )
    for product in products:
        product.write({'list_price': product.standard_price + profit})
    _logger.info(
        "ordomatics: synced list_price for %d AI Service products (profit=%.2f)",
        len(products), profit,
    )


def _setup_kajande_contacts(env):
    """Normalize Kajande/Moctar contact data used for WhatsApp operations.

    Only runs when ORDOMATICS_SEED_DATA=true — these contacts are specific to
    the Ordomatics deployment and must not appear in client instances.
    """
    if os.environ.get("ORDOMATICS_SEED_DATA", "").lower() != "true":
        return
    kajande = env.ref("ordomatics.partner_kajande", raise_if_not_found=False)
    moctar = env.ref("ordomatics.partner_moctar", raise_if_not_found=False)
    kajande_phone = "+221773649575"

    if kajande and kajande.phone != kajande_phone:
        kajande.write({"phone": kajande_phone})
        _logger.info("ordomatics: set Kajande phone to %s", kajande_phone)

    if moctar and moctar.phone != kajande_phone:
        moctar.write({"phone": kajande_phone})
        _logger.info("ordomatics: set Moctar operator phone to %s", kajande_phone)


def post_init_hook(env):
    """Run the Ordomatics bootstrap after first install."""
    run_bootstrap(env)


def _setup_whatsapp_endpoint(env):
    """Inject META_APP_SECRET and META_VERIFY_TOKEN into the webhook endpoint.

    The XML ships placeholder values; this overwrites them from env vars so
    each environment uses its own Meta app credentials without touching source.
    """
    app_secret = os.environ.get("META_APP_SECRET", "").strip()
    verify_token = os.environ.get("META_VERIFY_TOKEN", "").strip()

    if not any([app_secret, verify_token]):
        _logger.info("ordomatics: no env credentials for WhatsApp endpoint — skipping")
        return

    endpoint = env.ref("whatsapp_base.endpoint_whatsapp_webhook", raise_if_not_found=False)
    if not endpoint:
        _logger.warning("ordomatics: webhook endpoint not found — skipping")
        return

    vals = {}
    if app_secret:
        vals["whatsapp_app_secret"] = app_secret
    if verify_token:
        vals["whatsapp_verify_token"] = verify_token

    endpoint.write(vals)
    _logger.info("ordomatics: WhatsApp webhook endpoint credentials updated from env vars")


def _setup_whatsapp_account(env):
    """Create or update the WhatsApp account from env vars.

    Reads:
      WHATSAPP_BUSINESS_ACCOUNT_ID → waba_id
      META_ACCESS_TOKEN            → access_token (encrypted at rest)
      META_APP_SECRET              → app_secret (encrypted at rest)

    No-op if whatsapp_base is not installed or WHATSAPP_BUSINESS_ACCOUNT_ID is unset.
    """
    if env.get("whatsapp.account") is None:
        return

    waba_id = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()
    access_token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    app_secret = os.environ.get("META_APP_SECRET", "").strip()

    if not waba_id:
        _logger.info(
            "ordomatics: WHATSAPP_BUSINESS_ACCOUNT_ID not set — skipping WhatsApp account setup"
        )
        return

    company = env.company
    account = env["whatsapp.account"].search(
        [("waba_id", "=", waba_id), ("platform_company_id", "=", company.id)], limit=1
    )

    account_name = os.environ.get("WHATSAPP_ACCOUNT_NAME", "Kajande").strip() or "Kajande"
    kajande = env.ref("ordomatics.partner_kajande", raise_if_not_found=False)

    vals = {"waba_id": waba_id, "platform_company_id": company.id}
    if access_token:
        vals["access_token"] = access_token
    if app_secret:
        vals["app_secret"] = app_secret
    if kajande:
        vals["client_company_id"] = kajande.id

    if account:
        account.write(vals)
        _logger.info("ordomatics: updated WhatsApp account waba_id=%s", waba_id)
    else:
        vals["name"] = account_name
        env["whatsapp.account"].create(vals)
        _logger.info("ordomatics: created WhatsApp account '%s' waba_id=%s", account_name, waba_id)


def _setup_replicate(env):
    """Auto-create Replicate provider and preload selected generation models."""
    LLMProvider = env.get("llm.provider")
    if LLMProvider is None:
        _logger.info("ordomatics: llm.provider not available, skipping Replicate setup")
        return

    provider = LLMProvider.search([("service", "=", "replicate")], limit=1)
    if not provider:
        provider = LLMProvider.create({"name": "Replicate", "service": "replicate"})
        _logger.info("ordomatics: created Replicate provider id=%s", provider.id)

    api_key = os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if api_key and not provider.api_key:
        provider.sudo().write({"api_key": api_key})
        _logger.info("ordomatics: set Replicate API key from REPLICATE_API_TOKEN env var")
    elif not api_key and not provider.api_key:
        _logger.warning(
            "ordomatics: REPLICATE_API_TOKEN not set — enter key manually in LLM > Providers"
        )
        return

    flux = _ensure_replicate_model(
        env,
        provider,
        model_name="black-forest-labs/flux-schnell",
        model_use="image_generation",
    )
    if flux:
        # LLMModel.create() triggers _auto_generate_io_schema() via llm_generate's create override
        _patch_flux_schnell_output_format(flux)

    replicate_models = [
        # Image Generation
        ("black-forest-labs/flux-pro",                  "image_generation"),
        ("black-forest-labs/flux-1.1-pro",              "image_generation"),
        ("bria-ai/bria-2.3-fast",                       "image_generation"),
        ("bytedance/seedream-3",                        "image_generation"),
        # Image Editing — background removal
        ("bria/remove-background",                      "image_generation"),
        ("bria/replace-background",                     "image_generation"),
        ("bria/generate-background",                    "image_generation"),
        ("recraft-ai/recraft-remove-background",        "image_generation"),
        ("pixelcut/background-removal",                 "image_generation"),
        ("lucataco/dis-background-removal",             "image_generation"),
        # Image Editing — erase / inpaint / retouch / product
        ("black-forest-labs/flux-fill-pro",             "image_generation"),
        ("black-forest-labs/flux-redux-dev",            "image_generation"),
        ("bria/eraser",                                 "image_generation"),
        ("bria/genfill",                                "image_generation"),
        ("bria/expand-image",                           "image_generation"),
        ("bria/product-shot",                           "image_generation"),
        ("bria/product-shadow",                         "image_generation"),
        ("bria/product-cutout",                         "image_generation"),
        ("bria/product-packshot",                       "image_generation"),
        # Image Upscaling
        ("philz1337x/clarity-upscaler",                 "image_generation"),
        ("nightmareai/real-esrgan",                     "image_generation"),
        # Video Generation
        ("minimax/video-01",                            "generation"),
        ("wan-video/wan-2.1-1.3b",                      "generation"),
        ("bytedance/seedance-1-pro-fast",               "generation"),
        ("cogvideox/cogvideox-5b-i2v",                  "generation"),
        # Music Generation
        ("minimax/music-2.5",                           "generation"),
        # Audio Generation
        ("stability-ai/stable-audio-2.5",               "generation"),
        # Text-to-Speech
        ("elevenlabs/elevenlabs-tts",                   "generation"),
        # Speech-to-Text
        ("openai/whisper",                              "transcription"),
        # Avatar / Lip Sync
        ("sync-labs/sync-1.6-lipsync",                  "generation"),
        # Google Veo — Video Generation
        ("google/veo-2",                                "generation"),
        ("google/veo-3",                                "generation"),
        ("google/veo-3-fast",                           "generation"),
        ("google/veo-3.1",                              "generation"),
        ("google/veo-3.1-fast",                         "generation"),
        ("google/veo-3.1-lite",                         "generation"),
        # Google Imagen — Image Generation
        ("google/imagen-3",                             "image_generation"),
        ("google/imagen-3-fast",                        "image_generation"),
        ("google/imagen-4",                             "image_generation"),
        ("google/imagen-4-fast",                        "image_generation"),
        ("google/imagen-4-ultra",                       "image_generation"),
        ("google/gemini-2.5-flash-image",               "image_generation"),
        ("google/upscaler",                             "image_generation"),
        # Google Lyria — Music Generation
        ("google/lyria-2",                              "generation"),
        ("google/lyria-3",                              "generation"),
    ]
    for model_name, model_use in replicate_models:
        _ensure_replicate_model(env, provider, model_name=model_name, model_use=model_use)


def _setup_fal_ai(env):
    """Auto-create Fal.ai provider and preload selected generation models."""
    LLMProvider = env.get("llm.provider")
    if LLMProvider is None:
        _logger.info("ordomatics: llm.provider not available, skipping Fal.ai setup")
        return

    provider = LLMProvider.search([("service", "=", "fal_ai")], limit=1)
    if not provider:
        provider = LLMProvider.create({"name": "Fal.ai", "service": "fal_ai"})
        _logger.info("ordomatics: created Fal.ai provider id=%s", provider.id)

    api_key = os.environ.get("FAL_KEY", "").strip()
    if api_key and not provider.api_key:
        provider.sudo().write({"api_key": api_key})
        _logger.info("ordomatics: set Fal.ai API key from FAL_KEY env var")
    elif not api_key and not provider.api_key:
        _logger.warning(
            "ordomatics: FAL_KEY not set — enter key manually in LLM > Providers"
        )
        return

    fal_models = [
        # Image Generation
        ("fal-ai/flux/dev",                                         "image_generation"),
        ("fal-ai/flux-pro/v1.1",                                    "image_generation"),
        ("fal-ai/bytedance/seedream/v5/lite/text-to-image",         "image_generation"),
        ("fal-ai/nano-banana-2",                                    "image_generation"),
        # Image Editing — background removal
        ("fal-ai/bria/background/remove",                           "image_generation"),
        ("fal-ai/bria/background/replace",                          "image_generation"),
        ("fal-ai/image-editing/background-change",                  "image_generation"),
        ("fal-ai/ideogram/v3/replace-background",                   "image_generation"),
        # Image Editing — erase / inpaint / retouch
        ("fal-ai/bria/eraser",                                      "image_generation"),
        ("fal-ai/bria/genfill",                                     "image_generation"),
        ("fal-ai/flux/dev/image-to-image",                          "image_generation"),
        ("fal-ai/flux-pro/kontext",                                 "image_generation"),
        ("fal-ai/nano-banana-2/edit",                               "image_generation"),
        # Image Upscaling
        ("fal-ai/clarity-upscaler",                                 "image_generation"),
        ("clarityai/crystal-upscaler",                              "image_generation"),
        ("fal-ai/seedvr/upscale/image",                             "image_generation"),
        # Video Generation
        ("fal-ai/bytedance/seedance/v1/pro/fast/text-to-video",     "generation"),
        ("fal-ai/kling-video/v2.6/pro/text-to-video",               "generation"),
        # Video Editing
        ("fal-ai/kling-video/o1/video-to-video/edit",               "generation"),
        # Image-to-Video
        ("fal-ai/bytedance/seedance/v1/pro/image-to-video",         "generation"),
        ("fal-ai/kling-video/v2.6/pro/image-to-video",              "generation"),
        ("fal-ai/wan-i2v",                                          "generation"),
        # Music Generation
        ("fal-ai/minimax-music/v2",                                 "generation"),
        # Audio Generation
        ("fal-ai/stable-audio",                                     "generation"),
        ("fal-ai/ace-step/prompt-to-audio",                         "generation"),
        # Audio Editing
        ("fal-ai/ace-step/audio-to-audio",                          "generation"),
        ("fal-ai/stable-audio-25/audio-to-audio",                   "generation"),
        # Text-to-Speech
        ("fal-ai/elevenlabs/tts/multilingual-v2",                   "generation"),
        # Speech-to-Text
        ("fal-ai/whisper",                                          "transcription"),
        ("fal-ai/wizper",                                           "transcription"),
        # Voice Cloning
        ("fal-ai/elevenlabs/voice-changer",                         "generation"),
        ("fal-ai/dia-tts/voice-clone",                              "generation"),
        ("fal-ai/minimax/voice-clone",                              "generation"),
        ("fal-ai/vibevoice",                                        "generation"),
        ("fal-ai/vibevoice/7b",                                     "generation"),
        ("fal-ai/vibevoice/0.5b",                                   "generation"),
        # 3D Generation
        ("fal-ai/trellis-2",                                        "generation"),
        # Avatar / Lip Sync
        ("fal-ai/kling-video/ai-avatar/v2/pro",                     "generation"),
        ("fal-ai/sync-lipsync/v3",                                  "generation"),
    ]
    for model_name, model_use in fal_models:
        _ensure_provider_model(
            env, provider, fetch_method="fal_ai_models",
            model_name=model_name, model_use=model_use,
        )


def _ensure_replicate_model(env, provider, model_name, model_use):
    """Ensure a Replicate model exists in Odoo with the expected use."""
    return _ensure_provider_model(
        env,
        provider,
        fetch_method="replicate_models",
        model_name=model_name,
        model_use=model_use,
    )


def _ensure_provider_model(env, provider, fetch_method, model_name, model_use):
    """Ensure a provider-backed model exists in Odoo with the expected use."""
    LLMModel = env["llm.model"]
    model = LLMModel.search(
        [("name", "=", model_name), ("provider_id", "=", provider.id)], limit=1
    )
    if model:
        vals = {}
        if model.model_use != model_use:
            vals["model_use"] = model_use
        if vals:
            model.write(vals)
            _logger.info(
                "ordomatics: updated %s id=%s with %s",
                model_name, model.id, ", ".join(vals.keys()),
            )
        else:
            _logger.info("ordomatics: %s already exists id=%s", model_name, model.id)
        return model

    try:
        model_fetcher = getattr(provider, fetch_method)
        model_data = next(model_fetcher(model_id=model_name), None)
    except Exception as e:
        _logger.warning(
            "ordomatics: could not fetch %s from provider %s: %s",
            model_name,
            provider.service,
            e,
        )
        model_data = None

    vals = {"name": model_name, "provider_id": provider.id, "model_use": model_use}
    if model_data:
        vals["details"] = model_data.get("details", {})

    model = LLMModel.create(vals)
    _logger.info("ordomatics: created %s id=%s", model_name, model.id)
    return model


def _patch_flux_schnell_output_format(model):
    """Override output_format default to 'png' — Meta WhatsApp rejects WebP."""
    details = model.details
    if not details:
        return
    input_schema = details.get("input_schema", {})
    props = input_schema.get("properties", {})
    output_format = props.get("output_format")
    if not output_format or output_format.get("default") == "png":
        return
    new_details = dict(details)
    new_input_schema = dict(input_schema)
    new_props = dict(props)
    new_props["output_format"] = dict(output_format, default="png")
    new_input_schema["properties"] = new_props
    new_details["input_schema"] = new_input_schema
    model.write({"details": new_details})
    _logger.info("ordomatics: patched flux-schnell output_format default → png")


# ---------------------------------------------------------------------------
# Base URL
# ---------------------------------------------------------------------------

def _setup_base_url(env):
    """Set web.base.url from SERVER_URL env var.

    Falls back to the existing value (auto-detected by Odoo on first request)
    if SERVER_URL is not set. This ensures Wave callback URLs, email links,
    and portal URLs all use the correct public hostname.
    """
    server_url = os.environ.get("SERVER_URL", "").strip().rstrip("/")
    if not server_url:
        _logger.info("ordomatics: SERVER_URL not set — web.base.url left as-is")
        return
    params = env["ir.config_parameter"].sudo()
    params.set_param("web.base.url", server_url)
    params.set_param("web.base.url.freeze", "True")
    _logger.info("ordomatics: web.base.url set to %s (frozen)", server_url)


def _setup_nomic_embedding(env):
    """Configure Nomic as the embedding provider using their OpenAI-compatible API.

    Reads:
      NOMIC_API_KEY → api_key on the Nomic llm.provider record

    Creates (idempotent):
      - llm.provider  "Nomic"  service=openai  api_base=https://api-atlas.nomic.ai/v1
      - llm.model     "nomic-embed-text-v1.5"  model_use=embedding  default=True

    The llm_skills embedding pipeline searches for a model with model_use=embedding
    and default=True — this record satisfies that lookup without any further config.

    Falls back to the Ollama-based setup if NOMIC_API_KEY is absent (self-hosted Ollama
    pointed at OLLAMA_API_BASE, preserved for backward compatibility).
    """
    api_key = os.environ.get("NOMIC_API_KEY", "").strip()
    if not api_key:
        # Fallback: configure Ollama API base if set (legacy / self-hosted path)
        api_base = os.environ.get("OLLAMA_API_BASE", "").strip()
        if api_base:
            env["ir.config_parameter"].sudo().set_param("llm_skills.ollama_api_base", api_base)
            _logger.info("ordomatics: NOMIC_API_KEY not set — using Ollama at %s", api_base)
        else:
            _logger.info("ordomatics: NOMIC_API_KEY not set — skipping embedding provider setup")
        return

    if env.get("llm.provider") is None:
        _logger.info("ordomatics: llm.provider model not available — skipping Nomic setup")
        return

    NOMIC_MODEL = "nomic-embed-text-v1.5"

    # Find or create the Nomic provider
    provider = env["llm.provider"].search([("name", "=", "Nomic")], limit=1)
    if not provider:
        provider = env["llm.provider"].sudo().create({
            "name": "Nomic",
            "service": "nomic",
            "api_key": api_key,
            "active": True,
        })
        _logger.info("ordomatics: Created Nomic provider (id=%s)", provider.id)
    else:
        provider.sudo().write({"api_key": api_key, "service": "nomic", "api_base": False})
        _logger.info("ordomatics: Updated Nomic provider (id=%s)", provider.id)

    # Find or create the embedding model record
    model = env["llm.model"].search([
        ("provider_id", "=", provider.id),
        ("name", "=", NOMIC_MODEL),
    ], limit=1)
    if not model:
        model = env["llm.model"].sudo().create({
            "name": NOMIC_MODEL,
            "provider_id": provider.id,
            "model_use": "embedding",
            "default": True,
            "active": True,
        })
        _logger.info("ordomatics: Registered embedding model '%s'", NOMIC_MODEL)

    # Migrate existing collections still pointing to a stale embedding model.
    # The "|" catches two cases:
    #   1. Model is on the Nomic provider but isn't the target (e.g. old API-created record)
    #   2. Model name contains "nomic-embed-text" regardless of provider (e.g. old Ollama model)
    if "llm.knowledge.collection" in env:
        stale_collections = env["llm.knowledge.collection"].sudo().search([
            ("embedding_model_id", "!=", model.id),
            "|",
            ("embedding_model_id.provider_id", "=", provider.id),
            ("embedding_model_id.name", "ilike", "nomic-embed-text"),
        ])
        if stale_collections:
            stale_collections.write({"embedding_model_id": model.id})
            _logger.info(
                "ordomatics: Migrated %d collection(s) to embedding model '%s'",
                len(stale_collections),
                NOMIC_MODEL,
            )

    _logger.info("ordomatics: Nomic embedding provider configured (%s)", NOMIC_MODEL)


# ---------------------------------------------------------------------------
# Wave payment provider setup
# ---------------------------------------------------------------------------

def _setup_wave_provider(env):
    """Configure the Wave payment provider from environment variables.

    Reads:
      WAVE_API_KEY                → wave_api_key
      WAVE_WEBHOOK_SIGNING_SECRET → wave_signing_secret

    Enables the provider if at least WAVE_API_KEY is set.
    No-op if payment_wave is not installed.
    """
    if env.get("payment.provider") is None:
        return

    api_key = os.environ.get("WAVE_API_KEY", "").strip()
    signing_secret = os.environ.get("WAVE_WEBHOOK_SIGNING_SECRET", "").strip()

    if not api_key or not signing_secret:
        _logger.info(
            "ordomatics: WAVE_API_KEY or WAVE_WEBHOOK_SIGNING_SECRET not set — skipping Wave provider setup"
        )
        return

    provider = env["payment.provider"].search([("code", "=", "wave")], limit=1)
    if not provider:
        _logger.warning("ordomatics: Wave payment provider not found — is payment_wave installed?")
        return

    vals = {
        "wave_api_key": api_key,
        "wave_signing_secret": signing_secret,
        "state": "enabled",
    }
    provider.sudo().write(vals)
    _logger.info(
        "ordomatics: Wave provider enabled (signing_secret=%s)",
        "set" if signing_secret else "not set",
    )


# ---------------------------------------------------------------------------
# WhatsApp operational bootstrap
# ---------------------------------------------------------------------------

def _sync_phone_numbers(env):
    """Pull phone numbers from Meta for all active WhatsApp accounts."""
    if env.get("whatsapp.account") is None:
        return
    accounts = env["whatsapp.account"].search([
        ("waba_id", "!=", False),
        ("active", "=", True),
    ])
    for account in accounts:
        account_name = account.name  # read before savepoint — stays cached if TX aborts
        try:
            with env.cr.savepoint():
                account.action_sync_phone_numbers()
            _logger.info("ordomatics: synced phone numbers for account '%s'", account_name)
        except Exception as exc:
            _logger.error(
                "ordomatics: could not sync phone numbers for '%s': %s", account_name, exc
            )


def _assign_operators(env):
    """Assign the admin operator (DEFAULT_ADMIN_PHONE) to every phone number.

    Reads DEFAULT_ADMIN_PHONE from the environment (E.164 format, e.g. +221XXXXXXXX).
    Matches against res.partner.mobile or .phone.  No-op if the env var is unset.
    """
    if env.get("whatsapp.phone.number") is None:
        return
    admin_phone = os.environ.get("DEFAULT_ADMIN_PHONE", "").strip()
    if not admin_phone:
        _logger.info("ordomatics: DEFAULT_ADMIN_PHONE not set — skipping operator assignment")
        return
    digits = admin_phone.lstrip("+")
    partner = (
        env["res.partner"].search([("mobile", "like", digits)], limit=1)
        or env["res.partner"].search([("phone", "like", digits)], limit=1)
    )
    if not partner:
        _logger.warning(
            "ordomatics: no partner found for DEFAULT_ADMIN_PHONE=%s — skipping", admin_phone
        )
        return
    phones = env["whatsapp.phone.number"].search([])
    for phone in phones:
        if partner not in phone.assigned_partner_ids:
            phone.assigned_partner_ids = [(4, partner.id)]
            _logger.info(
                "ordomatics: assigned %s as operator on %s",
                partner.name, phone.display_phone_number,
            )


def _mark_phones_connected(env):
    """Mark all pending WhatsApp phone numbers as connected."""
    if env.get("whatsapp.phone.number") is None:
        return
    phones = env["whatsapp.phone.number"].search([("status", "=", "pending")])
    for phone in phones:
        try:
            phone.action_mark_as_connected()
            _logger.info("ordomatics: marked %s as connected", phone.display_phone_number)
        except Exception as exc:
            _logger.warning(
                "ordomatics: could not mark %s connected: %s",
                phone.display_phone_number, exc,
            )


def _opt_in_partners(env):
    """Opt-in any whatsapp_enabled partner that is not yet opted in."""
    partners = env["res.partner"].search([
        ("whatsapp_enabled", "=", True),
        ("whatsapp_opt_in", "=", False),
        ("mobile", "!=", False),
    ])
    for partner in partners:
        try:
            partner.write({"whatsapp_opt_in": True, "whatsapp_opt_in_method": "admin"})
            _logger.info("ordomatics: opted in %s (%s)", partner.name, partner.mobile)
        except Exception as exc:
            _logger.error("ordomatics: could not opt-in %s: %s", partner.name, exc)


# ---------------------------------------------------------------------------
# WhatsApp LLM assistant bootstrap
# ---------------------------------------------------------------------------

def _setup_assistants(env):
    """Configure provider, model, and send_whatsapp tool on both WhatsApp assistants."""
    if env.get("llm.provider") is None:
        return
    provider = env["llm.provider"].search([("service", "=", "anthropic")], limit=1)
    if not provider:
        _logger.warning(
            "ordomatics: Anthropic provider not found — "
            "set provider_id and model_id manually on the WhatsApp assistants."
        )

    model = None
    if provider:
        model = (
            env["llm.model"].search(
                [("provider_id", "=", provider.id), ("name", "=", "claude-haiku-4-5-20251001")],
                limit=1,
            )
            or env["llm.model"].search([("provider_id", "=", provider.id)], limit=1)
        )

    send_whatsapp = env["llm.tool"].search([("name", "=", "send_whatsapp")], limit=1)
    payment_manager = env["llm.tool"].search([("name", "=", "odoo_payment_manager")], limit=1)
    ai_model_finder = env["llm.tool"].search([("name", "=", "odoo_ai_model_finder")], limit=1)

    for ref_id, label in [
        ("whatsapp_llm.whatsapp_default_assistant", "whatsapp_default"),
        ("whatsapp_llm.whatsapp_owner_assistant", "whatsapp_owner"),
    ]:
        asst = env.ref(ref_id, raise_if_not_found=False)
        if not asst:
            continue
        vals = {}
        if provider and not asst.provider_id:
            vals["provider_id"] = provider.id
        if model and not asst.model_id:
            vals["model_id"] = model.id
        tool_ids = []
        if send_whatsapp and send_whatsapp not in asst.tool_ids:
            tool_ids.append((4, send_whatsapp.id))
        if payment_manager and payment_manager not in asst.tool_ids:
            tool_ids.append((4, payment_manager.id))
        if ai_model_finder and ai_model_finder not in asst.tool_ids:
            tool_ids.append((4, ai_model_finder.id))
        if tool_ids:
            vals["tool_ids"] = tool_ids
        if vals:
            asst.write(vals)
            _logger.info(
                "ordomatics: configured assistant '%s' — %s", label, list(vals)
            )
        else:
            _logger.info("ordomatics: assistant '%s' already configured", label)


def _index_catalog_for_search(env):
    """Index AI Service product.template records into the 'Products and Services' vector collection.

    Follows the same bypass pattern as llm_skills_loader:
    - One llm.resource per product.template (state=ready, no pipeline)
    - One llm.knowledge.chunk per resource (content = description_sale)
    - collection.embed_resources() to generate and store the vector

    Only re-embeds records whose description_sale has changed.
    No-op if llm.knowledge.collection or billing_products category is not available.
    """
    categ = env.ref('billing_products.product_categ_ai_service', raise_if_not_found=False)
    if env.get("llm.knowledge.collection") is None or categ is None:
        return

    collection = env["llm.knowledge.collection"].search(
        [("name", "=", "Products and Services")], limit=1
    )
    # Resolve the canonical embedding model: prefer the Nomic provider's default
    # embedding model so both collections always share the same vector space.
    nomic_provider = env["llm.provider"].search([("name", "=", "Nomic")], limit=1)
    canonical_embedding_model = (
        env["llm.model"].search(
            [("provider_id", "=", nomic_provider.id), ("name", "=", "nomic-embed-text-v1.5")],
            limit=1,
        )
        if nomic_provider
        else env["llm.model"].search([("name", "ilike", "nomic-embed-text")], limit=1)
    )

    if not collection:
        store = env["llm.store"].search([("service", "=", "pgvector")], limit=1)
        if not store or not canonical_embedding_model:
            _logger.warning(
                "ordomatics: cannot create 'Products and Services' collection — "
                "pgvector store or embedding model not found"
            )
            return
        collection = env["llm.knowledge.collection"].create({
            "name": "Products and Services",
            "description": "AI service catalog — one chunk per product for semantic model discovery.",
            "store_id": store.id,
            "embedding_model_id": canonical_embedding_model.id,
            "active": True,
        })
        _logger.info("ordomatics: created 'Products and Services' collection")
    elif canonical_embedding_model and collection.embedding_model_id != canonical_embedding_model:
        collection.embedding_model_id = canonical_embedding_model
        _logger.info(
            "ordomatics: updated 'Products and Services' collection embedding model to '%s'",
            canonical_embedding_model.name,
        )

    ir_model = env["ir.model"].search([("model", "=", "product.template")], limit=1)
    if not ir_model:
        _logger.warning("ordomatics: ir.model for product.template not found")
        return

    products = env["product.template"].search([
        ("categ_id", "=", categ.id),
        ("description_sale", "!=", False),
    ])
    resources_to_embed = []

    for product in products:
        content = (product.description_sale or "").strip()
        if not content:
            continue

        resource = env["llm.resource"].search(
            [("model_id", "=", ir_model.id), ("res_id", "=", product.id)],
            limit=1,
        )
        if not resource:
            resource = env["llm.resource"].create({
                "name": product.name,
                "model_id": ir_model.id,
                "res_id": product.id,
                "state": "ready",
                "collection_ids": [(4, collection.id)],
            })
            _logger.info("ordomatics: created resource for product '%s'", product.name)
        elif collection.id not in resource.collection_ids.ids:
            resource.collection_ids = [(4, collection.id)]

        # Check if chunk content matches — skip if already up to date
        existing_chunk = env["llm.knowledge.chunk"].search(
            [("resource_id", "=", resource.id)], limit=1
        )
        if existing_chunk and existing_chunk.content == content:
            continue

        # Delete stale chunk(s) and create fresh one
        if existing_chunk:
            existing_chunk.unlink()
        env["llm.knowledge.chunk"].create({
            "resource_id": resource.id,
            "content": content,
            "sequence": 1,
            "metadata": {"product_name": product.name},
        })
        resources_to_embed.append(resource.id)

    if resources_to_embed:
        try:
            collection.embed_resources(specific_resource_ids=resources_to_embed)
            _logger.info(
                "ordomatics: embedded %d AI Service product resources into 'Products and Services'",
                len(resources_to_embed),
            )
        except Exception as e:
            _logger.error(
                "ordomatics: embedding failed for 'Products and Services': %s", e, exc_info=True
            )
    else:
        _logger.info("ordomatics: 'Products and Services' catalog index is up to date")


def _setup_phone_number(env):
    """Link the WhatsApp phone number to both assistants and the owner partner.

    Phone selection: match WHATSAPP_PHONE_NUMBER env var if set, else first phone.
    Owner partner: matched by DEFAULT_ADMIN_PHONE env var.
    """
    if env.get("whatsapp.phone.number") is None:
        return
    phone = _find_phone_number(env)
    if not phone:
        _logger.info(
            "ordomatics: no phone number found — "
            "configure default_assistant_id manually after syncing."
        )
        return

    vals = {}
    default_asst = env.ref("whatsapp_llm.whatsapp_default_assistant", raise_if_not_found=False)
    if default_asst and not phone.default_assistant_id:
        vals["default_assistant_id"] = default_asst.id

    owner_asst = env.ref("whatsapp_llm.whatsapp_owner_assistant", raise_if_not_found=False)
    if owner_asst and not phone.owner_assistant_id:
        vals["owner_assistant_id"] = owner_asst.id

    if not phone.owner_partner_id:
        partner = _find_admin_partner(env)
        if partner:
            vals["owner_partner_id"] = partner.id

    if vals:
        phone.write(vals)
        _logger.info(
            "ordomatics: configured phone %s — %s",
            phone.display_phone_number, list(vals),
        )
    else:
        _logger.info(
            "ordomatics: phone %s already configured", phone.display_phone_number
        )


def _find_phone_number(env):
    target = os.environ.get("WHATSAPP_PHONE_NUMBER", "").strip().replace(" ", "")
    if target:
        digits = target.lstrip("+")
        phone = env["whatsapp.phone.number"].search(
            [("display_phone_number", "like", "%" + digits[-7:])], limit=1
        )
        if phone:
            return phone
        _logger.warning(
            "ordomatics: WHATSAPP_PHONE_NUMBER=%s not matched — "
            "falling back to first phone number.", target
        )
    return env["whatsapp.phone.number"].search([], limit=1)


def _find_admin_partner(env):
    admin_phone = os.environ.get("DEFAULT_ADMIN_PHONE", "").strip().replace(" ", "")
    if not admin_phone:
        return None
    digits = admin_phone.lstrip("+")
    partner = (
        env["res.partner"].search([("mobile", "like", digits)], limit=1)
        or env["res.partner"].search([("phone", "like", digits)], limit=1)
    )
    if not partner:
        _logger.warning(
            "ordomatics: no partner found for DEFAULT_ADMIN_PHONE=%s", admin_phone
        )
    return partner


def _setup_whatsapp_catalog(env):
    """Create/update the WhatsApp catalog record and pull items from Meta.

    Reads:
      WHATSAPP_CATALOG_ID   → Meta catalog ID (required)
      WHATSAPP_CATALOG_NAME → display name (default: 'AI Services')

    Steps:
      1. Find (or create) a whatsapp.catalog record for the active WABA account.
      2. Link it to the phone number as catalog_id.
      3. Call action_pull_from_meta() to sync catalog items from Meta.

    No-op if whatsapp_catalog is not installed or WHATSAPP_CATALOG_ID is unset.
    """
    if env.get("whatsapp.catalog") is None:
        return

    meta_catalog_id = os.environ.get("WHATSAPP_CATALOG_ID", "").strip()
    if not meta_catalog_id:
        _logger.info(
            "ordomatics: WHATSAPP_CATALOG_ID not set — skipping catalog setup"
        )
        return

    waba_id = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()
    account = (
        env["whatsapp.account"].search([("waba_id", "=", waba_id)], limit=1)
        if waba_id
        else env["whatsapp.account"].search([("active", "=", True)], limit=1)
    )
    if not account:
        _logger.warning("ordomatics: no WhatsApp account found — skipping catalog setup")
        return

    catalog_name = os.environ.get("WHATSAPP_CATALOG_NAME", "AI Services").strip() or "AI Services"

    catalog = env["whatsapp.catalog"].search(
        [("account_id", "=", account.id), ("catalog_id", "=", meta_catalog_id)], limit=1
    )
    if catalog:
        if catalog.name != catalog_name:
            catalog.write({"name": catalog_name, "is_default": True})
        _logger.info(
            "ordomatics: whatsapp.catalog '%s' (meta_id=%s) already exists",
            catalog_name, meta_catalog_id,
        )
    else:
        catalog = env["whatsapp.catalog"].create({
            "name": catalog_name,
            "catalog_id": meta_catalog_id,
            "account_id": account.id,
            "is_default": True,
        })
        _logger.info(
            "ordomatics: created whatsapp.catalog '%s' (meta_id=%s)",
            catalog_name, meta_catalog_id,
        )

    # Link catalog to the phone number
    phone = _find_phone_number(env)
    if phone and not phone.catalog_id:
        phone.write({"catalog_id": catalog.id})
        _logger.info(
            "ordomatics: linked catalog '%s' to phone %s",
            catalog_name, phone.display_phone_number,
        )

    # Pull items from Meta (idempotent — upserts by retailer_id)
    try:
        catalog.action_pull_from_meta()
        _logger.info(
            "ordomatics: pulled %d catalog items from Meta for '%s'",
            catalog.item_count, catalog_name,
        )
    except Exception as exc:
        _logger.warning(
            "ordomatics: catalog item pull from Meta failed: %s", exc
        )


def _setup_whatsapp_templates(env):
    """Pull approved templates from Meta for all active WhatsApp accounts.

    No-op if whatsapp_template is not installed.
    """
    if env.get("whatsapp.template") is None:
        return
    accounts = env["whatsapp.account"].search([("waba_id", "!=", False)])
    for account in accounts:
        account_name = account.name
        try:
            with env.cr.savepoint():
                account.action_pull_templates()
            _logger.info(
                "ordomatics: pulled templates for account '%s' (%d total)",
                account_name, account.template_count,
            )
        except Exception as exc:
            _logger.warning(
                "ordomatics: template pull failed for '%s': %s", account_name, exc,
            )


def _sync_fastapi_endpoints(env):
    """Sync all FastAPI endpoint routes so inbound webhook POSTs are routed correctly."""
    if env.get("fastapi.endpoint") is None:
        return
    endpoints = env["fastapi.endpoint"].search([])
    if not endpoints:
        _logger.warning("ordomatics: no fastapi.endpoint records found — skipping sync")
        return
    try:
        endpoints.action_sync_registry()
        _logger.info(
            "ordomatics: synced %d FastAPI endpoint(s): %s",
            len(endpoints), [e.name for e in endpoints],
        )
    except Exception:
        _logger.warning("ordomatics: FastAPI endpoint sync failed", exc_info=True)
