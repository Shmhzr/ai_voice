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
SPEAK_PROVIDER = {"type": "eleven_labs", "model_id": os.getenv("AGENT_TTS_MODEL","aura-2-helena-en"),
        "voice_id": "cgSgspJ2msm6clMCkdW9"}

# Local fallback menu (import-time safe)
LOCAL_MENU: Dict[str, Any] = {
    "summary": "We offer a selection of pizzas with toppings and add-ons.",
    "flavors": ["Cheezy 7", "Las Vegas Treat", "Country Side", "La Pinoz Chicken Pizza"],
    "toppings": ["paneer", "onion", "capsicum", "mushrooms", "sweet corn"],
    "addons": ["coke", "garlic bread", "choco lava cake"],
    "sizes": ["Small", "Medium", "Large"],
}

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
            "prompt": (
                "You are an AI-powered Pizza Ordering Assistant for phone-call customers. "
                "Your job is to help customers browse the menu, build their pizza order, review it, and check out smoothly. "

                "You can use the provided functions to: "
                "1) Retrieve the current menu (flavors, toppings, sizes, and add-ons). "
                "2) Add items to the cart with flavor, toppings, size, quantity, and add-ons. "
                "3) Modify cart items (change flavor, toppings, size, quantity, add-ons). "
                "4) Remove items from the cart if the customer changes their mind. "
                "5) Read back the current cart so the customer can confirm the order. "
                "6) Save and confirm the customer’s phone number and address for the order. "
                "7) Check whether an order has already been placed in this call session. "
                "8) Begin checkout and generate an order number when the customer is ready to finalize. "
                "9) Look up an order status by phone number or order number. "
                "10) Extract phone numbers or order numbers or Order address from free-form speech when needed. "

                "Your responsibilities: "
                "- Be friendly, professional, and clear. "
                "- Guide the customer through ordering step-by-step. "
                "- Always confirm pizza flavor, size, quantity, toppings, add-ons, and phone number before checkout. "
                "- If the customer wants to modify something, use the modify or remove functions as needed. "
                "- If instructions are unclear, politely ask clarifying questions. "
                "- Before finalizing checkout, read the entire cart back to the customer and get explicit confirmation. "
                "- If the customer asks about an order status, gather either their phone or order number and use the appropriate function. "

                "Your goal is to ensure the order is accurate, complete, and confirmed before moving to checkout."

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
                    "description": "Generate order number but don't finalize yet. Can be called once per order flow.",
                    "parameters": {
                        "type": "object",
                        "properties": {"phone": {"type": "string"}, "address": {"type": "string"}},
                        "required": ["phone","address"],
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
                }

            ],
        },
        "speak": {"provider": SPEAK_PROVIDER},
        "greeting": os.getenv("AGENT_GREETING", "Hi! Welcome to AI-Pizza. What can I get for you today?"),
    },
}


def get_default_prompt(force_refresh: bool = False) -> str:
    if force_refresh:
        global _cached_menu
        _cached_menu = None
    return build_prompt_from_menu()

