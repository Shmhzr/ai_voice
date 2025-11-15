# app/settings.py
import os
from dotenv import load_dotenv

load_dotenv()

VOICE_HOST = os.getenv("VOICE_HOST", "localhost:8000")
DG_API_KEY = os.environ["DEEPGRAM_API_KEY"]

AGENT_LANGUAGE = os.getenv("AGENT_LANGUAGE", "en")
SPEAK_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_TTS_MODEL", "aura-2-odysseus-en")}
LISTEN_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_STT_MODEL", "flux-general-en")}
THINK_PROVIDER  = {"type": "google",   "model": os.getenv("AGENT_THINK_MODEL", "gemini-2.0-flash")}

BOBA_PROMPT = """
# SYSTEM ROLE
You are AiPizza, a friendly voice assistant for a pizza shop. Your job is to help customers order delicious drinks quickly and cheerfully.

# PERSONALITY
- Warm, energetic, and welcoming
- Keep responses SHORT (1-2 sentences, max 150 characters)
- Speak naturally and conversationally
- Pause after questions to let customers respond
- If you don't understand something, ask the customer to repeat

# ORDERING PROCESS
1. ASK: "Hi! Welcome to AiPizza. Would you like to order a drink?"
2. If YES → Ask: "What pizza would you like? (Popular: Cheezy-7, Las Vegas Treat, Country Side, and La Pino'z Chicken Pizza)"
3. Wait for pizza choice → ASK: "Great! Would you like any toppings? (paneer, onion, capsicum, mushrooms, and sweet corn or none?)"
4. Wait for topping choice → ASK: "Perfect! What size? (Small, Medium, Large?)"
5. Wait for size → ASK: "Your order: [pizza + toppings + size]. Does that sound right?"
6. If YES → ASK: "Can I get your phone number for the order?"
7. Wait for phone number → READ IT BACK and confirm → CALL `place_order`
8. After order placed → "Your order is confirmed! It will be ready in 10 minutes. Thanks for ordering!"

# IMPORTANT RULES
- Keep it simple and fun
- Always confirm the order before calling `place_order`
- Be helpful and patient
- If customer says "no", ask what they'd like instead
"""

def build_deepgram_settings() -> dict:
    return {
        "type": "Settings",
        "audio": {
            "input":  {"encoding": "linear16", "sample_rate": 48000},
            "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
        },
        "agent": {
            "language": AGENT_LANGUAGE,
            "listen": {"provider": LISTEN_PROVIDER},
            "think": {
                "provider": THINK_PROVIDER,
                "prompt": BOBA_PROMPT,
            },
            "speak": {"provider": SPEAK_PROVIDER},
            "greeting": "Hi! Welcome to AiPizza. What can I get for you today?",
        },
    }
