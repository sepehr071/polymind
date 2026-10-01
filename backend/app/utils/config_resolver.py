from app.models.llm_config import LLMConfigModel
from app.prompts.canvas import CANVAS_SYSTEM_PROMPT
from app.utils.quick_models import QUICK_MODELS

AGENT_CONFIGS = {
    'canvas': {
        'name': 'Canvas Coder',
        'model_id': 'moonshotai/kimi-k2.6',
        'system_prompt': CANVAS_SYSTEM_PROMPT,
        'parameters': {'temperature': 0.4, 'max_tokens': 32000},
    },
}


def resolve_config(config_id, user_id=None, project_id=None):
    """
    Resolve a config ID to a config dict.

    Supports:
      - Quick models (prefixed `quick:`) — never project-scoped.
      - Agent templates (prefixed `agent:`) — never project-scoped.
      - Real LLMConfig docs from MongoDB — may be personal OR project-scoped.

    Project gating (v1):
      A LLMConfig with `project_id` set is considered project-scoped. The
      caller must:
        1. provide a non-None `project_id` argument that matches the config's
           project_id, AND
        2. either own the config OR have at least 'viewer' access to that
           project (via workspace fallback or explicit project membership).

      If `project_id` is None (e.g. personal chat), project-scoped configs are
      invisible — `resolve_config` returns None as if the config did not exist.

      Personal/public/template configs (project_id is None / missing) are
      gated here too: only the owner (matching ``user_id``) or a
      ``public`` / ``template`` visibility resolves. Any other user's
      ``private`` config returns None as if it did not exist (IDOR fix).

    Args:
      config_id:  The config identifier (string). May be `quick:<model>`,
                  `agent:<key>`, or a Mongo ObjectId hex string.
      user_id:    The acting user's id. Required for project-access checks
                  on project-scoped configs; ignored for quick/agent paths
                  and personal configs (the caller validates ownership).
      project_id: The caller's *active* project context. Pass None for
                  personal flows (chat). Project-scoped configs are only
                  resolvable when this matches.

    Returns: the config dict, or None if not found / blocked.
    """
    config_id = str(config_id)
    if config_id.startswith('quick:'):
        model_id = config_id.replace('quick:', '')
        # Allowlist gate (denial-of-wallet): a `quick:<id>` only resolves when the
        # bare id is a curated quick model. Without this, any authed user could
        # route to ANY OpenRouter model (incl. premium) on the shared key by
        # crafting `quick:<arbitrary/model>`. QUICK_MODELS keys are the bare,
        # `quick:`-stripped ids, so legit curated models still resolve.
        if model_id not in QUICK_MODELS:
            return None
        return {
            '_id': config_id,
            'model_id': model_id,
            'name': QUICK_MODELS.get(model_id, model_id),
            'system_prompt': '',
            # 32000 (not 2048): reasoning/"thinking" models (e.g. gemini-3.x flash)
            # bill reasoning tokens AGAINST this output budget, so a small cap let
            # hidden reasoning starve the visible answer -> truncated replies that
            # still report thousands of tokens. max_tokens is a CAP (billed per
            # real token + clamped by OpenRouter to each model's real output
            # limit), so short replies are unaffected; only long answers use the
            # headroom. Reasoning stays at the provider default.
            'parameters': {'temperature': 0.7, 'max_tokens': 32000},
        }
    if config_id.startswith('agent:'):
        agent_key = config_id.split(':', 1)[1]
        cfg = AGENT_CONFIGS.get(agent_key)
        if not cfg:
            return None
        return {
            '_id': config_id,
            'name': cfg['name'],
            'model_id': cfg['model_id'],
            'system_prompt': cfg['system_prompt'],
            'parameters': cfg['parameters'],
            'is_agent': True,
        }

    config = LLMConfigModel.find_by_id(config_id)
    if not config:
        return None

    cfg_pid = config.get('project_id')
    if cfg_pid:
        # Project-scoped config — gated.
        # 1. Caller must have provided an active project context.
        if project_id is None:
            return None
        # 2. Active project must match the config's project.
        if str(project_id) != str(cfg_pid):
            return None
        # 3. Caller must own the config OR have at least viewer on the project.
        owner_id = config.get('owner_id')
        if user_id is not None and str(owner_id) != str(user_id):
            from app.utils.permissions import check_project_access
            if not check_project_access(user_id, cfg_pid, 'viewer'):
                return None
        # If user_id is None we cannot prove access — treat as not-found.
        if user_id is None:
            return None
    else:
        # Personal-scope config (no project_id). Gate ownership/visibility here
        # — the chat routes do NOT re-validate, so a missing check here is an
        # IDOR: any user could run another user's private persona by raw id,
        # leaking its system_prompt + model_id and mutating its usage stats.
        # Allow only public/template configs or the caller's own config.
        if config.get('visibility') not in ('public', 'template'):
            owner_id = config.get('owner_id')
            if user_id is None or str(owner_id) != str(user_id):
                return None

    return config
