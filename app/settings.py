# app/settings.py
import os
import logging
import json
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# --- Basic env-configurable values ---
DG_API_KEY = os.getenv("DG_API_KEY")
MENU_API_URL = os.getenv("MENU_API_URL")

# Providers (defaults, can be overridden via env)

AGENT_LANGUAGE = os.getenv("AGENT_LANGUAGE", "en-US")
LISTEN_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_STT_MODEL", "flux-general-en")}
THINK_PROVIDER  = {"type": "google",   "model": os.getenv("AGENT_THINK_MODEL", "gemini-2.0-flash")}
SPEAK_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_TTS_MODEL", "aura-2-odysseus-en")}

# Local fallback menu (import-time safe)
LOCAL_MENU: Dict[str, Any] = {
    "summary": "We offer a selection of pizzas with toppings and add-ons.",
    "flavors": ["Cheezy 7", "Las Vegas Treat", "Country Side", "La Pinoz Chicken Pizza"],
    "toppings": ["paneer", "onion", "capsicum", "mushrooms", "sweet corn"],
    "addons": ["coke", "garlic bread", "choco lava cake"],
    "sizes": ["Small", "Medium", "Large"],
}

# --- Safe remote fetch helpers (do NOT call at import-time unless you mean to) ---
def fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("MENU_API_URL returned status %s", resp.status_code)
            return None
        try:
            return resp.json()
        except ValueError as e:
            logger.warning("MENU_API_URL returned non-JSON response: %s", e)
            return None
    except requests.RequestException as e:
        logger.warning("Failed to fetch MENU_API_URL %s: %s", url, e)
        return None

_cached_menu: Optional[Dict[str, Any]] = None

def get_menu(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Return the effective menu. This will try the remote MENU_API_URL once
    and fall back to LOCAL_MENU when unavailable. Safe to call at runtime.
    """
    global _cached_menu
    if _cached_menu is not None and not force_refresh:
        return _cached_menu

    if MENU_API_URL:
        remote = fetch_remote_menu(MENU_API_URL)
        if isinstance(remote, dict) and remote:
            # support both top-level schema and {"record": {...}} wrappers
            if "record" in remote and isinstance(remote["record"], dict):
                remote = {**remote["record"], **{k: v for k, v in remote.items() if k != "record"}}
            _cached_menu = remote
            return _cached_menu
        logger.info("Using LOCAL_MENU fallback because remote menu was unavailable or invalid.")
    else:
        logger.info("MENU_API_URL not set; using LOCAL_MENU.")

    _cached_menu = LOCAL_MENU
    return _cached_menu

# --- Prompt builder that tolerates missing keys ---
def build_prompt_from_menu(menu: Optional[Dict[str, Any]] = None) -> str:
    m = menu or get_menu()
    flavors = m.get("flavors") or m.get("pizzas") or m.get("items") or []
    toppings = m.get("toppings") or []
    addons = m.get("addons") or m.get("extras") or []
    sizes = m.get("sizes") or []

    def to_list_of_strings(x):
        if not x:
            return []
        if isinstance(x, dict):
            return list(x.keys())
        if isinstance(x, list):
            return [str(i) for i in x]
        return [str(x)]

    flavors = to_list_of_strings(flavors)
    toppings = to_list_of_strings(toppings)
    addons = to_list_of_strings(addons)
    sizes = to_list_of_strings(sizes)

    snippet = {
        "flavors": flavors,
        "toppings": toppings,
        "addons": addons,
        "sizes": sizes,
    }
    try:
        menu_snippet = json.dumps(snippet, indent=2, ensure_ascii=False)
    except Exception:
        menu_snippet = (
            "Flavors: " + ", ".join(flavors) + ". "
            "Toppings: " + ", ".join(toppings) + ". "
            "Add-ons: " + ", ".join(addons) + ". "
            "Sizes: " + ", ".join(sizes) + "."
        )

    prompt = (
        "You are an AI pizza ordering assistant.\n\n"
        "Use the following menu when making suggestions and validating user choices:\n"
        f"{menu_snippet}\n\n"
        "Ask clarifying questions when necessary (size, quantity, toppings, address). "
        "Always confirm phone numbers before checkout. Do not finalize orders without explicit confirmation."
    )
    return prompt

# --- Re-introduce build_deepgram_settings so other modules can import it ---
def build_deepgram_settings(prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Build the Deepgram 'Settings' payload expected by agent_client / agent setup.
    If prompt is not provided, it will be generated from the current menu.
    """
    effective_prompt = prompt or build_prompt_from_menu()
    return {
        "type": "Settings",
        "audio": {
            "input": {"encoding": "linear16", "sample_rate": 48000},
            "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
        },
        "agent": {
            "language": AGENT_LANGUAGE,
            "listen": {"provider": LISTEN_PROVIDER},
            "think": {
                "provider": THINK_PROVIDER,
                "prompt": effective_prompt,
                # NOTE: functions are often supplied elsewhere (agent_functions), keep this compact
                # If you prefer the full function definitions here, you can load them dynamically.
            },
            "speak": {"provider": SPEAK_PROVIDER},
            "greeting": os.getenv("AGENT_GREETING", "Hi! Welcome to AI-Pizza. What can I get for you today?"),
        },
    }

# Optional convenience: a cached default PROMPT (call at startup if you want)
def get_default_prompt(force_refresh: bool = False) -> str:
    if force_refresh:
        global _cached_menu
        _cached_menu = None
    return build_prompt_from_menu()

# Exported names: DG_API_KEY, build_deepgram_settings, get_menu, get_default_prompt
# app/settings.py
import os
import logging
import json
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# --- Basic env-configurable values ---
DG_API_KEY = os.getenv("DG_API_KEY")
MENU_API_URL = os.getenv("MENU_API_URL")

# Providers (defaults, can be overridden via env)
AGENT_LANGUAGE = os.getenv("AGENT_LANGUAGE", "en-US")
LISTEN_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_STT_MODEL", "flux-general-en")}
THINK_PROVIDER  = {"type": "google",   "model": os.getenv("AGENT_THINK_MODEL", "gemini-2.0-flash")}
SPEAK_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_TTS_MODEL", "aura-2-odysseus-en")}
# Local fallback menu (import-time safe)
LOCAL_MENU: Dict[str, Any] = {
    "summary": "We offer a selection of pizzas with toppings and add-ons.",
    "flavors": ["Cheezy 7", "Las Vegas Treat", "Country Side", "La Pinoz Chicken Pizza"],
    "toppings": ["paneer", "onion", "capsicum", "mushrooms", "sweet corn"],
    "addons": ["coke", "garlic bread", "choco lava cake"],
    "sizes": ["Small", "Medium", "Large"],
}

# --- Safe remote fetch helpers (do NOT call at import-time unless you mean to) ---
def fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("MENU_API_URL returned status %s", resp.status_code)
            return None
        try:
            return resp.json()
        except ValueError as e:
            logger.warning("MENU_API_URL returned non-JSON response: %s", e)
            return None
    except requests.RequestException as e:
        logger.warning("Failed to fetch MENU_API_URL %s: %s", url, e)
        return None

_cached_menu: Optional[Dict[str, Any]] = None

def get_menu(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Return the effective menu. This will try the remote MENU_API_URL once
    and fall back to LOCAL_MENU when unavailable. Safe to call at runtime.
    """
    global _cached_menu
    if _cached_menu is not None and not force_refresh:
        return _cached_menu

    if MENU_API_URL:
        remote = fetch_remote_menu(MENU_API_URL)
        if isinstance(remote, dict) and remote:
            # support both top-level schema and {"record": {...}} wrappers
            if "record" in remote and isinstance(remote["record"], dict):
                remote = {**remote["record"], **{k: v for k, v in remote.items() if k != "record"}}
            _cached_menu = remote
            return _cached_menu
        logger.info("Using LOCAL_MENU fallback because remote menu was unavailable or invalid.")
    else:
        logger.info("MENU_API_URL not set; using LOCAL_MENU.")

    _cached_menu = LOCAL_MENU
    return _cached_menu

# --- Prompt builder that tolerates missing keys ---
def build_prompt_from_menu(menu: Optional[Dict[str, Any]] = None) -> str:
    m = menu or get_menu()
    flavors = m.get("flavors") or m.get("pizzas") or m.get("items") or []
    toppings = m.get("toppings") or []
    addons = m.get("addons") or m.get("extras") or []
    sizes = m.get("sizes") or []

    def to_list_of_strings(x):
        if not x:
            return []
        if isinstance(x, dict):
            return list(x.keys())
        if isinstance(x, list):
            return [str(i) for i in x]
        return [str(x)]

    flavors = to_list_of_strings(flavors)
    toppings = to_list_of_strings(toppings)
    addons = to_list_of_strings(addons)
    sizes = to_list_of_strings(sizes)

    snippet = {
        "flavors": flavors,
        "toppings": toppings,
        "addons": addons,
        "sizes": sizes,
    }
    try:
        menu_snippet = json.dumps(snippet, indent=2, ensure_ascii=False)
    except Exception:
        menu_snippet = (
            "Flavors: " + ", ".join(flavors) + ". "
            "Toppings: " + ", ".join(toppings) + ". "
            "Add-ons: " + ", ".join(addons) + ". "
            "Sizes: " + ", ".join(sizes) + "."
        )

    prompt = (
        "You are an AI pizza ordering assistant.\n\n"
        "Use the following menu when making suggestions and validating user choices:\n"
        f"{menu_snippet}\n\n"
        "Ask clarifying questions when necessary (size, quantity, toppings, address). "
        "Always confirm phone numbers before checkout. Do not finalize orders without explicit confirmation."
    )
    return prompt

# --- Re-introduce build_deepgram_settings so other modules can import it ---
def build_deepgram_settings(prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Build the Deepgram 'Settings' payload expected by agent_client / agent setup.
    If prompt is not provided, it will be generated from the current menu.
    """
    effective_prompt = prompt or build_prompt_from_menu()
    return {
        "type": "Settings",
        "audio": {
            "input": {"encoding": "linear16", "sample_rate": 48000},
            "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
        },
        "agent": {
            "language": AGENT_LANGUAGE,
            "listen": {"provider": LISTEN_PROVIDER},
            "think": {
                "provider": THINK_PROVIDER,
                "prompt": effective_prompt,
                # NOTE: functions are often supplied elsewhere (agent_functions), keep this compact
                # If you prefer the full function definitions here, you can load them dynamically.
            },
            "speak": {"provider": SPEAK_PROVIDER},
            "greeting": os.getenv("AGENT_GREETING", "Hi! Welcome to AI-Pizza. What can I get for you today?"),
        },
    }

# Optional convenience: a cached default PROMPT (call at startup if you want)
def get_default_prompt(force_refresh: bool = False) -> str:
    if force_refresh:
        global _cached_menu
        _cached_menu = None
    return build_prompt_from_menu()

# Exported names: DG_API_KEY, build_deepgram_settings, get_menu, get_default_prompt
