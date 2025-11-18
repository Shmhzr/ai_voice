# call.py
from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

def trigger_test_call() -> str:
    """
    Place a Twilio call using environment variables:
      - TWILIO_ACCOUNT_SID
      - TWILIO_AUTH_TOKEN
      - TWILIO_FROM_E164
      - VOICE_HOST
      - TWILIO_TO_E164   (destination)
    Returns the Twilio Call SID on success.
    Raises RuntimeError with a helpful message on failure.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_number = os.getenv("TWILIO_FROM_E164")
    voice_host = os.getenv("VOICE_HOST")
    to_number = os.getenv("TWILIO_TO_E164")

    missing = [k for k, v in (
        ("TWILIO_ACCOUNT_SID", account_sid),
        ("TWILIO_AUTH_TOKEN", auth_token),
        ("TWILIO_FROM_E164", twilio_number),
        ("VOICE_HOST", voice_host),
        ("TWILIO_TO_E164", to_number),
    ) if not v]

    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))

    # Optionally: basic sanity check for E.164 (very simple)
    if not to_number.startswith("+") or not to_number[1:].isdigit():
        raise RuntimeError("TWILIO_TO_E164 must be a valid E.164 string, e.g. +919876543210")

    client = Client(account_sid, auth_token)

    print("📞 Initiating voice call simulation...")
    print(f"From: {twilio_number}")
    print(f"To:   {to_number}")
    print(f"Webhook: https://{voice_host}/voice")

    try:
        call = client.calls.create(
            to=to_number,
            from_=twilio_number,
            url=f"https://{voice_host}/voice",
        )
    except Exception as e:
        raise RuntimeError(f"Twilio call failed: {e}") from e

    print(f"✅ Call initiated: {call.sid}")
    return call.sid


if __name__ == "__main__":
    # CLI-friendly: run as a script, optionally override dest via env or prompt
    try:
        sid = trigger_test_call()
        print("Call SID:", sid)
    except Exception as err:
        print("ERROR:", err)
