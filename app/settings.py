import os
import logging
import json
from typing import Any, Dict, Optional,List

import requests

logger = logging.getLogger(__name__)

# --- Basic env-configurable values ---
DG_API_KEY = os.getenv("DG_API_KEY")
MENU_API_URL = os.getenv("MENU_API_URL")

# Providers (defaults, can be overridden via env)

AGENT_LANGUAGE = os.getenv("AGENT_LANGUAGE", "en-US")
LISTEN_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_STT_MODEL", "flux-general-en")}
THINK_PROVIDER  = {"type": "google",   "model": os.getenv("AGENT_THINK_MODEL", "gemini-2.0-flash")}
SPEAK_PROVIDER = {
        "type": "eleven_labs",
        "model_id": os.getenv("AGENT_TTS_MODEL", "eleven_multilingual_v2"),
        "voice_id": os.getenv("AGENT_TTS_VOICE", "cgSgspJ2msm6clMCkdW9")
      }

# Local fallback menu (import-time safe)
LOCAL_MENU: Dict[str, Any] = {
    "summary": "We offer a selection of pizzas with toppings and add-ons.",
    "flavors": ["Cheezy 7", "Las Vegas Treat", "Country Side", "La Pinoz Chicken Pizza"],
    "toppings": ["paneer", "onion", "capsicum", "mushrooms", "sweet corn"],
    "addons": ["coke", "garlic bread", "choco lava cake"],
    "sizes": ["Small", "Medium", "Large"],
}

def fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """
    Fetch a remote menu JSON. Be resilient to common JSONBin URL shapes and
    support private JSONBin v3 via JSONBIN_API_KEY env var (sent as X-Master-Key).

    Tries:
      - the provided URL
      - url + '/latest'
      - url + '/raw'
      - url + '/raw/latest'
      - url + '?meta=false'

    Returns the parsed JSON dict on success, otherwise None.
    """
    if not url:
        return None

    headers = {"Accept": "application/json"}
    api_key = os.getenv("JSONBIN_API_KEY") or os.getenv("JSONBIN_MASTER_KEY")
    if api_key:
        headers["X-Master-Key"] = api_key

    # Candidate URLs to try (preserve original, but try common JSONBin variants)
    base = url.rstrip("/")
    candidates = [
        url,
        f"{base}/latest",
        f"{base}/raw",
        f"{base}/raw/latest",
        f"{base}?meta=false",
    ]

    # Deduplicate while preserving order
    seen = set()
    tried = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            tried.append(c)

    last_exc = None
    for u in tried:
        try:
            resp = requests.get(u, timeout=timeout, headers=headers)
        except requests.RequestException as e:
            logger.warning("Failed to fetch MENU_API_URL %s: %s", u, e)
            last_exc = e
            continue

        if resp.status_code == 200:
            # Got something — try to parse JSON
            try:
                return resp.json()
            except ValueError as e:
                logger.warning("MENU_API_URL %s returned non-JSON response: %s", u, e)
                return None
        else:
            logger.debug("MENU_API_URL %s returned status %s", u, resp.status_code)
            last_exc = RuntimeError(f"status {resp.status_code} for {u}")

    # Nothing succeeded
    logger.warning("Failed to fetch MENU_API_URL. Tried URLs: %s. Last error: %s", tried, last_exc)
    return None

def _normalize_remote_menu(raw: Any) -> Dict[str, Any]:
    """
    Turn the remote menu (which may be nested or use keys like 'Pizza','Sides','Drinks')
    into a canonical simple menu containing:
      - flavors: list of item names (pizzas / main items)
      - toppings: unique list of toppings
      - addons: list of sides/drinks
      - sizes: unique list of size keys (e.g. 'regular','slice')
      - prices: optional mapping item -> size -> price (numbers or None)
    """
    # Always return a dict with the canonical keys (never None)
    if not raw:
        return {"flavors": [], "toppings": [], "addons": [], "sizes": ["regular"], "prices": {}}

    # unwrap potential {"record": {...}} wrappers
    if isinstance(raw, dict) and "record" in raw and isinstance(raw["record"], dict):
        raw = raw["record"]

    # If the menu is nested under "menu" key, descend.
    if isinstance(raw, dict) and "menu" in raw:
        raw = raw["menu"]

    flavors: List[str] = []
    toppings_set = set()
    addons: List[str] = []
    sizes_set = set()
    prices: Dict[str, Dict[str, Optional[float]]] = {}

    def _process_item(item: dict, treat_as_addon: bool = False):
        if not isinstance(item, dict):
            return
        name = item.get("name") or item.get("title")
        if not name:
            return
        name = str(name)
        if treat_as_addon:
            addons.append(name)
        else:
            flavors.append(name)

        # toppings or ingredients
        t = item.get("toppings") or item.get("ingredients") or []
        if isinstance(t, list):
            for top in t:
                if top:
                    toppings_set.add(str(top))
        elif isinstance(t, str):
            toppings_set.add(t)

        # sizes: dict of size -> {price: ...} or simple price
        s = item.get("sizes")
        if isinstance(s, dict):
            prices.setdefault(name, {})
            for size_key, size_val in s.items():
                sizes_set.add(size_key)
                price = None
                if isinstance(size_val, dict):
                    price = size_val.get("price") or size_val.get("cost")
                elif isinstance(size_val, (int, float)):
                    price = size_val
                try:
                    prices[name][size_key] = float(price) if price is not None else None
                except Exception:
                    prices[name][size_key] = None
        else:
            # maybe a direct "price" field
            price = item.get("price")
            if price is not None:
                sizes_set.add("default")
                try:
                    prices.setdefault(name, {})["default"] = float(price)
                except Exception:
                    prices.setdefault(name, {})["default"] = None

    # Candidate keys that commonly hold pizza items and addons
    if isinstance(raw, dict):
        main_sections = ["Pizza", "Pizzas", "pizza", "pizzas", "flavors", "items", "menu_items"]
        addon_sections = ["Sides", "Drinks", "addons", "extras", "sides", "drinks"]

        # First try explicit sections
        for sec in main_sections:
            sec_items = raw.get(sec)
            if isinstance(sec_items, list):
                for it in sec_items:
                    _process_item(it, treat_as_addon=False)

        for sec in addon_sections:
            sec_items = raw.get(sec)
            if isinstance(sec_items, list):
                for it in sec_items:
                    _process_item(it, treat_as_addon=True)

        # If we didn't find flavors, heuristically scan top-level lists
        if not flavors:
            for k, v in raw.items():
                if isinstance(v, list) and v:
                    sample = v[0]
                    if isinstance(sample, dict) and ("sizes" in sample or "toppings" in sample or "description" in sample):
                        for it in v:
                            _process_item(it, treat_as_addon=False)
                    else:
                        for it in v:
                            _process_item(it, treat_as_addon=True)

    elif isinstance(raw, list):
        for it in raw:
            _process_item(it, treat_as_addon=False)

    # Finalize sizes default
    sizes = sorted(sizes_set) if sizes_set else ["regular"]

    # Deduplicate toppings list and ensure deterministic ordering
    toppings = sorted(toppings_set)

    return {
        "flavors": flavors,
        "toppings": toppings,
        "addons": addons,
        "sizes": sizes,
        "prices": prices,
    }


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
            # Normalize the remote menu into the canonical shape our assistant expects.
            try:
                _cached_menu = _normalize_remote_menu(remote)
            except Exception:
                # If normalization fails for any reason, fall back to the raw remote object
                logger.exception("Failed to normalize remote menu; using raw remote menu.")
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
            "prompt": (
                "You are an AI-powered Pizza Ordering Assistant for phone-call customers.\n\n"

                "High-level: Greet the caller, determine whether they want to place a new order or check an order status, "
                "and then guide them step-by-step to complete or check the order. Use the provided tool functions (menu_summary, "
                "add_to_cart, modify_cart_item, remove_from_cart, get_cart, save_order_type, save_phone_number, confirm_phone_number, "
                "save_address, checkout_order, order_status, extract_phone_and_order) to perform actions — do not invent state or finalize an order "
                "without calling the appropriate tools.\n\n"

                "Staged ordering flow (follow exactly):\n"
                "1) Greeting: Say hello and ask whether they want to place an order or check an existing order. If checking, ask for phone or order number and call order_status.\n"
                "2) Menu: If ordering, call menu_summary when helpful and offer menu suggestions (flavors, sizes, toppings, add-ons).\n"
                "3) Build cart: Add pizzas using add_to_cart. If the caller wants adjustments, use modify_cart_item or remove_from_cart. Use set_size_quantity or quantity fields where required.\n"
                "4) Confirm cart: Call get_cart and read the cart back clearly (flavor, size, toppings, add-ons, quantity). Ask the caller to confirm the cart contents before proceeding.\n"
                "5) Order type (required): Ask whether the order is PICKUP or DELIVERY. Call save_order_type to persist the choice. Do not proceed to collect address for PICKUP orders.\n"
                "6) Contact details:\n"
                "   - For PICKUP: request phone number, call save_phone_number, then call confirm_phone_number to confirm.\n"
                "   - For DELIVERY: request phone and full delivery address, call save_phone_number and save_address, and confirm the phone with confirm_phone_number.\n"
                "7) Final validation: Before checkout, re-read cart, order type, phone, and address (if delivery). Ask: 'Is everything correct?' Only proceed when customer explicitly says 'yes' or 'confirm'.\n"
                "8) Checkout: Call checkout_order to generate an order number (do not auto-finalize outside this call). After checkout, tell the caller the order number and expected next steps.\n\n"

                "Tool usage rules and behavior:\n"
                "- Always use the provided tool that matches the intent (e.g., save_order_type for order type, save_address for delivery address).\n"
                "- If the caller gives free-form text containing numbers, use extract_phone_and_order to parse potential phone or 4-digit order numbers.\n"
                "- If a requested flavor, topping, or add-on is not on the menu, politely tell the caller and offer alternatives from menu_summary.\n"
                "- Enforce limits: do not add more than the maximum allowed pizzas; inform the caller clearly if limits are reached.\n"
                "- When saving phone numbers, normalize but ask the user to confirm the final format before checkout.\n"
                "- Never finalize or claim the order is placed unless checkout_order returned an order number and the caller explicitly confirmed.\n\n"

                "Tone and responsibilities:\n"
                "- Be friendly, calm, and professional. Speak clearly and avoid jargon.\n"
                "- Guide the caller step-by-step, ask concise clarifying questions only when needed.\n"
                "- Repeat back important details (cart contents, phone, address, order type) and request explicit confirmation.\n"
                "- If the caller asks about an existing order, gather phone or order number and use order_status to answer.\n\n"

                "Your goal is to ensure the order is accurate, complete, and explicitly confirmed before checkout."
            ),

            "functions": [
                {
                    "name": "menu_summary",
                    "description": "Retrieve the current pizza menu, including available flavors, toppings, add-ons, and sizes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "Optional category to filter menu items (e.g., 'flavors', 'toppings', 'addons', 'sizes').",
                            }
                        },
                        "required": [],
                    },
                },
                {
                    "name": "add_to_cart",
                    "description": "Place a new pizza order with customer details and order items.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item": {
                                "type": "string",
                                "description": "Pizza flavor or item name."
                            },
                            "flavor": {
                                "type": "string",
                                "description": "Pizza flavor (alias for item)."
                            },
                            "toppings": {
                                "type": "string",
                                "description": "Comma-separated list of toppings."
                            },
                            "size": 
                            {
                                "type": "string", 
                                "description": "Small | Medium | Large"
                            },
                            "quantity": 
                            {
                                "type": "integer", 
                                "minimum": 1
                            },
                            "address": 
                            {
                                "type": "string", 
                                "description": "Full delivery address of customer including street, city, state, and zip code."
                            },
                            "addons": 
                            {
                                "type": "array", 
                                "items": {"type": "string"}
                            },
                            "call_sid": 
                            {
                                "type": "string", 
                                "description": "Optional Twilio call SID to bind this function call to a specific phone call/session."
                            }
                        },
                        "required": ["flavor","size","quantity","call_sid"],
                    },
                },

                {
                    "name":"remove_from_cart",
                    "description": "Remove a pizza by index (0-based).",
                    "parameters": 
                    {
                        "type": "object",
                        "properties": {"index": {"type": "integer", "minimum": 0}},
                        "required": ["index"],
                    },
                },

                {
                    "name": "modify_cart_item",
                    "description": "Modify an existing pizza in the cart by index.",
                    "parameters": 
                    {
                        "type": "object",
                        "properties": 
                        {
                            "index": {"type": "integer", "minimum": 0},
                            "flavor": {"type": "string"},
                            "item": {"type": "string"},
                            "toppings": {"type": "array", "items": {"type": "string"}},
                            "size": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "addons": {"type": "array", "items": {"type": "string"}},
                            "call_sid": {"type": "string"}
                        },
                        "required": ["index"],
                    },
                },

                {
                    "name": "get_cart",
                    "description": "Get current cart contents to read back to customer.",
                    "parameters": {"type": "object", "properties": {"call_sid": {"type": "string"}},
                    "required": []},
                },

                {
                    "name": "order_is_placed",
                    "description": "Return whether an order number has been generated in this call session.",
                    "parameters": 
                    {"type": "object", 
                     "properties": {}, 
                     "required": []},
                },
                {
                    "name": "checkout_order",
                    "description": "Generate an order number (can be called once per order flow). This may be called after order_type, phone, and address have been saved. If some details are missing, the agent should collect them first or call the appropriate save_* functions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "phone": {"type": "string"},
                            "address": {
                                "type": "string",
                                "description":"Full delivery address of customer including street, city, state, and zip code."
                            },
                            "order_type": {
                                "type": "string",
                                "description":"Order type: pickup or delivery."
                            },
                            "call_sid": {"type": "string"}
                        },
                        "required": [], 
                    },
                },

                {
                    "name": "order_status",
                    "description": "Look up order status by phone or order number.",
                    "parameters": {
                        "type": "object",
                        "properties": {"phone": {"type": "string"}, "order_number": {"type": "string"}, "call_sid": {"type": "string"}},
                        "required": [],
                    },
                },
                
                {
                    "name": "extract_phone_and_order",
                    "description": "Extract phone and 4-digit order number from free text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}, "call_sid": {"type": "string"}},
                        "required": ["text"],
                    },
                },

                {
                    "name": "save_phone_number",
                    "description": "Save the customer's phone number for pickup/delivery (not confirmed).",
                    "parameters": {
                        "type": "object",
                        "properties": {"phone": {"type": "string"}, "call_sid": {"type": "string"}},
                        "required": ["phone"],
                    },
                },

                {
                    "name": "confirm_phone_number",
                    "description": "Confirm (true) or reject (false) the previously provided phone number.",
                    "parameters": {
                        "type": "object",
                        "properties": {"confirmed": {"type": "boolean"}, "call_sid": {"type": "string"}},
                        "required": ["confirmed"],
                    },
                },

                {
                    "name": "save_address",
                    "description": "Save the customer's delivery address (not confirmed). Can be empty or omitted for pickup orders.",
                    "parameters": {
                        "type": "object",
                        "properties": {"address": {"type": "string"}, "call_sid": {"type": "string"}},
                        "required": ["address"],
                    }
                },
                {
                    "name": "save_order_type",
                    "description": "Save the customer's order type (PICKUP or DELIVERY).",
                    "parameters": {
                        "type": "object",
                        "properties": {"order_type": {"type": "string"}, "call_sid": {"type": "string"}},
                        "required": ["order_type"],
                    }
                },

            ],
        },
        "speak": {"provider": SPEAK_PROVIDER},
        "greeting": os.getenv("AGENT_GREETING", "Hi! Welcome to Lapinoz-Pizza, i am clara your AI assitant.How can i help you today ? I can check your order status or help you place a new order."),
    },
}


def get_default_prompt(force_refresh: bool = False) -> str:
    if force_refresh:
        global _cached_menu
        _cached_menu = None
    return build_prompt_from_menu()


# # Old Logic without variable menu support - kept for reference
# import os
# import logging
# import json
# from typing import Any, Dict, Optional

# import requests

# logger = logging.getLogger(__name__)

# # --- Basic env-configurable values ---
# DG_API_KEY = os.getenv("DG_API_KEY")
# MENU_API_URL = os.getenv("MENU_API_URL")

# # Providers (defaults, can be overridden via env)

# AGENT_LANGUAGE = os.getenv("AGENT_LANGUAGE", "en-US")
# LISTEN_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_STT_MODEL", "flux-general-en")}
# THINK_PROVIDER  = {"type": "google",   "model": os.getenv("AGENT_THINK_MODEL", "gemini-2.0-flash")}
# SPEAK_PROVIDER = {
#         "type": "eleven_labs",
#         "model_id": os.getenv("AGENT_TTS_MODEL", "eleven_multilingual_v2"),
#         "voice_id": os.getenv("AGENT_TTS_VOICE", "cgSgspJ2msm6clMCkdW9")
#       }

# # Local fallback menu (import-time safe)
# LOCAL_MENU: Dict[str, Any] = {
#     "summary": "We offer a selection of pizzas with toppings and add-ons.",
#     "flavors": ["Cheezy 7", "Las Vegas Treat", "Country Side", "La Pinoz Chicken Pizza"],
#     "toppings": ["paneer", "onion", "capsicum", "mushrooms", "sweet corn"],
#     "addons": ["coke", "garlic bread", "choco lava cake"],
#     "sizes": ["Small", "Medium", "Large"],
# }

# def fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
#     if not url:
#         return None
#     try:
#         resp = requests.get(url, timeout=timeout)
#         if resp.status_code != 200:
#             logger.warning("MENU_API_URL returned status %s", resp.status_code)
#             return None
#         try:
#             return resp.json()
#         except ValueError as e:
#             logger.warning("MENU_API_URL returned non-JSON response: %s", e)
#             return None
#     except requests.RequestException as e:
#         logger.warning("Failed to fetch MENU_API_URL %s: %s", url, e)
#         return None
# def _normalize_remote_menu(raw: Any) -> Dict[str, Any]:
#     """
#     Turn the remote menu (which may be nested or use keys like 'Pizza','Sides','Drinks')
#     into a canonical simple menu containing:
#       - flavors: list of item names (pizzas / main items)
#       - toppings: unique list of toppings
#       - addons: list of sides/drinks
#       - sizes: unique list of size keys (e.g. 'regular','slice')
#       - prices: optional mapping item -> size -> price (numbers or None)
#     """
#     if not raw:
#         return {}

#     # unwrap potential {"record": {...}} wrappers
#     if isinstance(raw, dict) and "record" in raw and isinstance(raw["record"], dict):
#         raw = raw["record"]

#     # If the menu is nested under "menu" key, descend.
#     if isinstance(raw, dict) and "menu" in raw:
#         raw = raw["menu"]

#     flavors = []
#     toppings_set = set()
#     addons = []
#     sizes_set = set()
#     prices: Dict[str, Dict[str, Optional[float]]] = {}

#     def process_item(item: dict, treat_as_addon=False):
#         # item expected to be dict with 'name', optional 'toppings', optional 'sizes' or 'price'
#         name = item.get("name") if isinstance(item, dict) else None
#         if not name:
#             return
#         name = str(name)
#         if treat_as_addon:
#             addons.append(name)
#         else:
#             flavors.append(name)

#         # toppings may be list of strings
#         t = item.get("toppings") or item.get("ingredients") or []
#         if isinstance(t, list):
#             for top in t:
#                 if top:
#                     toppings_set.add(str(top))
#         elif isinstance(t, str):
#             toppings_set.add(t)

#         # sizes: could be dict of size_key -> {...price...}
#         s = item.get("sizes")
#         if isinstance(s, dict):
#             # e.g. "regular": {"price": 215, ...}
#             prices[name] = {}
#             for size_key, size_val in s.items():
#                 sizes_set.add(size_key)
#                 # try to extract a numeric price
#                 price = None
#                 if isinstance(size_val, dict):
#                     price = size_val.get("price") or size_val.get("cost") or None
#                 elif isinstance(size_val, (int, float)):
#                     price = size_val
#                 try:
#                     prices[name][size_key] = float(price) if price is not None else None
#                 except Exception:
#                     prices[name][size_key] = None
#         else:
#             # maybe a simple "price" field
#             price = item.get("price")
#             if price is not None:
#                 sizes_set.add("default")
#                 prices.setdefault(name, {})["default"] = float(price)

#     # If raw contains sections like Pizza, Sides, Drinks
#     if isinstance(raw, dict):
#         # Common section names that contain main flavors
#         main_sections = ["Pizza", "Pizzas", "flavors", "items", "menu_items"]
#         addon_sections = ["Sides", "Drinks", "addons", "extras"]
#         # first process main sections
#         for sec in main_sections:
#             if sec in raw and isinstance(raw[sec], list):
#                 for it in raw[sec]:
#                     process_item(it, treat_as_addon=False)
#         # then addons
#         for sec in addon_sections:
#             if sec in raw and isinstance(raw[sec], list):
#                 for it in raw[sec]:
#                     process_item(it, treat_as_addon=True)
#         # If above didn't find anything, attempt to treat keys at top-level as lists of items
#         if not flavors:
#             for k, v in raw.items():
#                 if isinstance(v, list):
#                     # heuristics: if items look pizza-like (have sizes/toppings) treat as flavors else addons
#                     sample = v[0] if v else None
#                     if isinstance(sample, dict) and ("sizes" in sample or "toppings" in sample or "description" in sample):
#                         for it in v:
#                             process_item(it, treat_as_addon=False)
#                     else:
#                         for it in v:
#                             process_item(it, treat_as_addon=True)
#     elif isinstance(raw, list):
#         # raw is list of items
#         for it in raw:
#             if isinstance(it, dict):
#                 process_item(it, treat_as_addon=False)

#     # fallback: if no sizes detected, include common defaults if any
#     sizes = sorted(sizes_set) if sizes_set else ["regular"]

#     return {
#         "flavors": flavors,
#         "toppings": sorted(toppings_set),
#         "addons": addons,
#         "sizes": sizes,
#         "prices": prices,
#     }

# _cached_menu: Optional[Dict[str, Any]] = None

# def get_menu(force_refresh: bool = False) -> Dict[str, Any]:
#     """
#     Return the effective menu. This will try the remote MENU_API_URL once
#     and fall back to LOCAL_MENU when unavailable. Safe to call at runtime.
#     """
#     global _cached_menu
#     if _cached_menu is not None and not force_refresh:
#         return _cached_menu

#     if MENU_API_URL:
#         remote = fetch_remote_menu(MENU_API_URL)
#         if isinstance(remote, dict) and remote:
#             # support both top-level schema and {"record": {...}} wrappers
#             if "record" in remote and isinstance(remote["record"], dict):
#                 remote = {**remote["record"], **{k: v for k, v in remote.items() if k != "record"}}
#             _cached_menu = remote
#             return _cached_menu
#         logger.info("Using LOCAL_MENU fallback because remote menu was unavailable or invalid.")
#     else:
#         logger.info("MENU_API_URL not set; using LOCAL_MENU.")

#     _cached_menu = LOCAL_MENU
#     return _cached_menu

# # --- Prompt builder that tolerates missing keys ---
# def build_prompt_from_menu(menu: Optional[Dict[str, Any]] = None) -> str:
#     m = menu or get_menu()
#     flavors = m.get("flavors") or m.get("pizzas") or m.get("items") or []
#     toppings = m.get("toppings") or []
#     addons = m.get("addons") or m.get("extras") or []
#     sizes = m.get("sizes") or []

#     def to_list_of_strings(x):
#         if not x:
#             return []
#         if isinstance(x, dict):
#             return list(x.keys())
#         if isinstance(x, list):
#             return [str(i) for i in x]
#         return [str(x)]

#     flavors = to_list_of_strings(flavors)
#     toppings = to_list_of_strings(toppings)
#     addons = to_list_of_strings(addons)
#     sizes = to_list_of_strings(sizes)

#     snippet = {
#         "flavors": flavors,
#         "toppings": toppings,
#         "addons": addons,
#         "sizes": sizes,
#     }
#     try:
#         menu_snippet = json.dumps(snippet, indent=2, ensure_ascii=False)
#     except Exception:
#         menu_snippet = (
#             "Flavors: " + ", ".join(flavors) + ". "
#             "Toppings: " + ", ".join(toppings) + ". "
#             "Add-ons: " + ", ".join(addons) + ". "
#             "Sizes: " + ", ".join(sizes) + "."
#         )

#     prompt = (
#         "You are an AI pizza ordering assistant.\n\n"
#         "Use the following menu when making suggestions and validating user choices:\n"
#         f"{menu_snippet}\n\n"
#         "Ask clarifying questions when necessary (size, quantity, toppings, address). "
#         "Always confirm phone numbers before checkout. Do not finalize orders without explicit confirmation."
#     )
#     return prompt

# # --- Re-introduce build_deepgram_settings so other modules can import it ---
# def build_deepgram_settings(prompt: Optional[str] = None) -> Dict[str, Any]:
#     """
#     Build the Deepgram 'Settings' payload expected by agent_client / agent setup.
#     If prompt is not provided, it will be generated from the current menu.
#     """
#     effective_prompt = prompt or build_prompt_from_menu()
#     return {
#     "type": "Settings",
#     "audio": {
#         "input": {"encoding": "linear16", "sample_rate": 48000},
#         "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
#     },
#     "agent": {
#         "language": AGENT_LANGUAGE,
#         "listen": {"provider": LISTEN_PROVIDER},
#         "think": {
#             "provider": THINK_PROVIDER,
#             "prompt": (
#                 "You are an AI-powered Pizza Ordering Assistant for phone-call customers.\n\n"

#                 "High-level: Greet the caller, determine whether they want to place a new order or check an order status, "
#                 "and then guide them step-by-step to complete or check the order. Use the provided tool functions (menu_summary, "
#                 "add_to_cart, modify_cart_item, remove_from_cart, get_cart, save_order_type, save_phone_number, confirm_phone_number, "
#                 "save_address, checkout_order, order_status, extract_phone_and_order) to perform actions — do not invent state or finalize an order "
#                 "without calling the appropriate tools.\n\n"

#                 "Staged ordering flow (follow exactly):\n"
#                 "1) Greeting: Say hello and ask whether they want to place an order or check an existing order. If checking, ask for phone or order number and call order_status.\n"
#                 "2) Menu: If ordering, call menu_summary when helpful and offer menu suggestions (flavors, sizes, toppings, add-ons).\n"
#                 "3) Build cart: Add pizzas using add_to_cart. If the caller wants adjustments, use modify_cart_item or remove_from_cart. Use set_size_quantity or quantity fields where required.\n"
#                 "4) Confirm cart: Call get_cart and read the cart back clearly (flavor, size, toppings, add-ons, quantity). Ask the caller to confirm the cart contents before proceeding.\n"
#                 "5) Order type (required): Ask whether the order is PICKUP or DELIVERY. Call save_order_type to persist the choice. Do not proceed to collect address for PICKUP orders.\n"
#                 "6) Contact details:\n"
#                 "   - For PICKUP: request phone number, call save_phone_number, then call confirm_phone_number to confirm.\n"
#                 "   - For DELIVERY: request phone and full delivery address, call save_phone_number and save_address, and confirm the phone with confirm_phone_number.\n"
#                 "7) Final validation: Before checkout, re-read cart, order type, phone, and address (if delivery). Ask: 'Is everything correct?' Only proceed when customer explicitly says 'yes' or 'confirm'.\n"
#                 "8) Checkout: Call checkout_order to generate an order number (do not auto-finalize outside this call). After checkout, tell the caller the order number and expected next steps.\n\n"

#                 "Tool usage rules and behavior:\n"
#                 "- Always use the provided tool that matches the intent (e.g., save_order_type for order type, save_address for delivery address).\n"
#                 "- If the caller gives free-form text containing numbers, use extract_phone_and_order to parse potential phone or 4-digit order numbers.\n"
#                 "- If a requested flavor, topping, or add-on is not on the menu, politely tell the caller and offer alternatives from menu_summary.\n"
#                 "- Enforce limits: do not add more than the maximum allowed pizzas; inform the caller clearly if limits are reached.\n"
#                 "- When saving phone numbers, normalize but ask the user to confirm the final format before checkout.\n"
#                 "- Never finalize or claim the order is placed unless checkout_order returned an order number and the caller explicitly confirmed.\n\n"

#                 "Tone and responsibilities:\n"
#                 "- Be friendly, calm, and professional. Speak clearly and avoid jargon.\n"
#                 "- Guide the caller step-by-step, ask concise clarifying questions only when needed.\n"
#                 "- Repeat back important details (cart contents, phone, address, order type) and request explicit confirmation.\n"
#                 "- If the caller asks about an existing order, gather phone or order number and use order_status to answer.\n\n"

#                 "Your goal is to ensure the order is accurate, complete, and explicitly confirmed before checkout."
#             ),

#             "functions": [
#                 {
#                     "name": "menu_summary",
#                     "description": "Retrieve the current pizza menu, including available flavors, toppings, add-ons, and sizes.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "category": {
#                                 "type": "string",
#                                 "description": "Optional category to filter menu items (e.g., 'flavors', 'toppings', 'addons', 'sizes').",
#                             }
#                         },
#                         "required": [],
#                     },
#                 },
#                 {
#                     "name": "add_to_cart",
#                     "description": "Place a new pizza order with customer details and order items.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "item": {
#                                 "type": "string",
#                                 "description": "Pizza flavor or item name."
#                             },
#                             "flavor": {
#                                 "type": "string",
#                                 "description": "Pizza flavor (alias for item)."
#                             },
#                             "toppings": {
#                                 "type": "string",
#                                 "description": "Comma-separated list of toppings."
#                             },
#                             "size": 
#                             {
#                                 "type": "string", 
#                                 "description": "Small | Medium | Large"
#                             },
#                             "quantity": 
#                             {
#                                 "type": "integer", 
#                                 "minimum": 1
#                             },
#                             "address": 
#                             {
#                                 "type": "string", 
#                                 "description": "Full delivery address of customer including street, city, state, and zip code."
#                             },
#                             "addons": 
#                             {
#                                 "type": "array", 
#                                 "items": {"type": "string"}
#                             },
#                             "call_sid": 
#                             {
#                                 "type": "string", 
#                                 "description": "Optional Twilio call SID to bind this function call to a specific phone call/session."
#                             }
#                         },
#                         "required": ["flavor","size","quantity","call_sid"],
#                     },
#                 },

#                 {
#                     "name":"remove_from_cart",
#                     "description": "Remove a pizza by index (0-based).",
#                     "parameters": 
#                     {
#                         "type": "object",
#                         "properties": {"index": {"type": "integer", "minimum": 0}},
#                         "required": ["index"],
#                     },
#                 },

#                 {
#                     "name": "modify_cart_item",
#                     "description": "Modify an existing pizza in the cart by index.",
#                     "parameters": 
#                     {
#                         "type": "object",
#                         "properties": 
#                         {
#                             "index": {"type": "integer", "minimum": 0},
#                             "flavor": {"type": "string"},
#                             "item": {"type": "string"},
#                             "toppings": {"type": "array", "items": {"type": "string"}},
#                             "size": {"type": "string"},
#                             "quantity": {"type": "integer"},
#                             "addons": {"type": "array", "items": {"type": "string"}},
#                             "call_sid": {"type": "string"}
#                         },
#                         "required": ["index"],
#                     },
#                 },

#                 {
#                     "name": "get_cart",
#                     "description": "Get current cart contents to read back to customer.",
#                     "parameters": {"type": "object", "properties": {"call_sid": {"type": "string"}},
#                     "required": []},
#                 },

#                 {
#                     "name": "order_is_placed",
#                     "description": "Return whether an order number has been generated in this call session.",
#                     "parameters": 
#                     {"type": "object", 
#                      "properties": {}, 
#                      "required": []},
#                 },
#                 {
#                     "name": "checkout_order",
#                     "description": "Generate an order number (can be called once per order flow). This may be called after order_type, phone, and address have been saved. If some details are missing, the agent should collect them first or call the appropriate save_* functions.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "phone": {"type": "string"},
#                             "address": {
#                                 "type": "string",
#                                 "description":"Full delivery address of customer including street, city, state, and zip code."
#                             },
#                             "order_type": {
#                                 "type": "string",
#                                 "description":"Order type: pickup or delivery."
#                             },
#                             "call_sid": {"type": "string"}
#                         },
#                         "required": [], 
#                     },
#                 },

#                 {
#                     "name": "order_status",
#                     "description": "Look up order status by phone or order number.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"phone": {"type": "string"}, "order_number": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": [],
#                     },
#                 },
                
#                 {
#                     "name": "extract_phone_and_order",
#                     "description": "Extract phone and 4-digit order number from free text.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"text": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["text"],
#                     },
#                 },

#                 {
#                     "name": "save_phone_number",
#                     "description": "Save the customer's phone number for pickup/delivery (not confirmed).",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"phone": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["phone"],
#                     },
#                 },

#                 {
#                     "name": "confirm_phone_number",
#                     "description": "Confirm (true) or reject (false) the previously provided phone number.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"confirmed": {"type": "boolean"}, "call_sid": {"type": "string"}},
#                         "required": ["confirmed"],
#                     },
#                 },

#                 {
#                     "name": "save_address",
#                     "description": "Save the customer's delivery address (not confirmed). Can be empty or omitted for pickup orders.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"address": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["address"],
#                     }
#                 },
#                 {
#                     "name": "save_order_type",
#                     "description": "Save the customer's order type (PICKUP or DELIVERY).",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"order_type": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["order_type"],
#                     }
#                 },

#             ],
#         },
#         "speak": {"provider": SPEAK_PROVIDER},
#         "greeting": os.getenv("AGENT_GREETING", "Hi! Welcome to Lapinoz-Pizza, i am clara your AI assitant.How can i help you today ? I can check your order status or help you place a new order."),
#     },
# }


# def get_default_prompt(force_refresh: bool = False) -> str:
#     if force_refresh:
#         global _cached_menu
#         _cached_menu = None
#     return build_prompt_from_menu()

