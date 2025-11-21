
# Create a test file
from twilio.rest import Client
import os
from dotenv import load_dotenv
import time


load_dotenv()


account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = os.getenv("TWILIO_FROM_E164")
voice_host = os.getenv("VOICE_HOST")

client = Client(account_sid, auth_token)

print("📞 Initiating voice call simulation...")
print(f"From: {twilio_number}")
print(f"Webhook: https://{voice_host}/voice")

# Make the call
# In trial mode, you can only call verified numbers
# Use YOUR OWN PHONE NUMBER here
your_verified_number = os.getenv("TWILIO_TO_E164", "+918777684725")

call = client.calls.create(
    # to="+919007209713",
    to="+918777684725",  # Your own verified phone number
    from_=twilio_number,      # Your Twilio number
    url=f"https://{voice_host}/voice",  # Your webhook
)

print(f"✅ Call initiated: {call.sid}")
print("Check your server logs to see the AI response...")