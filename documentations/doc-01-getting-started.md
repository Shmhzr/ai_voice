# Getting Started - Local Development

This guide walks you through setting up Deepgram BobaRista on your local machine using Podman and ngrok.

## Prerequisites

Before you begin, make sure you have:

- **Podman** or Docker installed
  - macOS: `brew install podman`
  - Linux: Check your distribution's package manager
  - Windows: [Podman Desktop](https://podman-desktop.io/)
- **ngrok** account and CLI
  - Sign up at https://ngrok.com
  - Install: `brew install ngrok/ngrok/ngrok` (macOS)
- **Twilio account** with A2P 10DLC approval 
- **Deepgram API key** from https://console.deepgram.com

## Step 1: Clone the Repository

```bash
git clone https://github.com/your-username/DG-Boba-Assitant.git
cd DG-Boba-Assitant
```

## Step 2: Configure Environment Variables

Create your `.env` file from the template:

```bash
cp sample.env.txt .env
```

Edit `.env` with your credentials:

```bash
# Server (will be updated with ngrok URL)
VOICE_HOST=localhost:8000

# Deepgram API Key (from console.deepgram.com)
DEEPGRAM_API_KEY=your_deepgram_api_key_here

# Agent Configuration
AGENT_LANGUAGE=en
AGENT_TTS_MODEL=aura-2-odysseus-en
AGENT_STT_MODEL=nova-3

# Twilio Voice (for calls)
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_FROM_E164=+1234567890

# Twilio Messaging (for SMS notifications)
MSG_TWILIO_ACCOUNT_SID=your_msg_twilio_account_sid_here
MSG_TWILIO_AUTH_TOKEN=your_msg_twilio_auth_token_here
MSG_TWILIO_FROM_E164=+1234567890
```

**Note**: You'll update `VOICE_HOST` after starting ngrok in Step 4.

## Step 3: Start the Application

### Using Podman (Recommended)

```bash
# Start the container
./podman-start.sh
```

This script will:
1. Check if Podman VM is running (macOS)
2. Remove any existing `boba-voice` container
3. Build the Docker image
4. Start the container on port 8000

### Using Docker

```bash
# Build the image
docker build -t boba-voice:local .

# Run the container
docker run -d --name boba-voice \
  -p 8000:8000 \
  --env-file .env \
  boba-voice:local
```

### Verify It's Running

```bash
# Check container status
podman ps
# or
docker ps

# View logs
podman logs -f boba-voice
# or
docker logs -f boba-voice

# Test the server
curl http://localhost:8000
```

You should see the landing page HTML.

## Step 4: Expose with ngrok

In a new terminal, start ngrok:

```bash
ngrok http 8000
```

You'll see output like:

```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000
```

**Copy the HTTPS URL** (e.g., `abc123.ngrok-free.app` - without `https://`)

## Step 5: Update Environment Variables

Edit your `.env` file and update `VOICE_HOST`:

```bash
VOICE_HOST=abc123.ngrok-free.app
```

**Restart the container** for changes to take effect:

```bash
podman restart boba-voice
# or
docker restart boba-voice
```

## Step 6: Configure Twilio

### Purchase a Phone Number

1. Go to [Twilio Console](https://console.twilio.com)
2. Navigate to **Phone Numbers** → **Buy a Number**
3. Select a number with **Voice** capability
4. Click **Buy**

### Configure Voice Webhook

1. Go to **Phone Numbers** → **Manage** → **Active Numbers**
2. Click on your purchased number
3. Scroll to **Voice Configuration**
4. Set **A Call Comes In**:
   - **Webhook**: `https://abc123.ngrok-free.app/voice`
   - **HTTP Method**: `POST`
5. Click **Save**

**Important**: Replace `abc123.ngrok-free.app` with your actual ngrok URL!

## Step 7: Test Your Setup

### Make a Test Call

1. **Call your Twilio number**
2. You should hear: "Connecting you to the Deepgram Boba Rista"
3. Then the AI greeting: "Hey! I am your Deepgram BobaRista. What would you like to order?"

### Place a Test Order

Try this conversation:

```
You: "I want a taro milk tea with boba"
AI: "One taro milk tea with boba. Is that correct?"
You: "Yes"
AI: "Great! Would you like anything else?"
You: "No, that's all"
AI: "Can I please get your phone number for this order?"
You: "555-123-4567"
AI: "Thank you! Your order number is 5566. We'll text you when it's ready for pickup!"
```

### Check the Dashboards

Open in your browser:

- **Landing Page**: http://localhost:8000
- **Orders TV**: http://localhost:8000/orders
- **Barista Console**: http://localhost:8000/barista

You should see your order appear in real-time!

## Common Local Dev Commands

```bash
# View live logs
podman logs -f boba-voice

# Stop the container
./podman-stop.sh
# or manually:
podman stop boba-voice

# Start after stopping
podman start boba-voice

# Restart after .env changes
podman restart boba-voice

# Rebuild after code changes
./podman-stop.sh && ./podman-start.sh

# Execute commands inside container
podman exec -it boba-voice bash

# List all containers
podman ps -a

# Remove container completely
podman rm -f boba-voice

# Remove image
podman rmi boba-voice:local
```

## Troubleshooting Local Setup

### Issue: "Podman machine not running"

```bash
# Start the Podman VM (macOS)
podman machine start

# Check status
podman machine list
```

### Issue: "Port 8000 already in use"

```bash
# Find what's using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>

# Or use a different port
podman run -p 8001:8000 ...
```

### Issue: "Container exits immediately"

```bash
# Check logs for errors
podman logs boba-voice
```

**Common issues:**
- Missing `DEEPGRAM_API_KEY` in `.env`
- Invalid `.env` format
- Python dependencies failed to install

### Issue: "ngrok URL keeps changing"

Free ngrok URLs change every time you restart. Solutions:

1. **Update `.env` with new URL each time**
2. **Upgrade to ngrok paid plan** for static domains
3. **Use localhost tunneling alternative** (e.g., localtunnel, Cloudflare Tunnel)

### Issue: "Twilio webhook not working"

```bash
# Check if ngrok is running
curl https://your-ngrok-url.ngrok-free.app/voice

# Check container logs
podman logs boba-voice
```

**Verify webhook URL in Twilio console:**
- Must be: `https://<ngrok-url>/voice` (with HTTPS)

### Issue: "No audio on call"

- Verify ngrok is using HTTPS (not HTTP)
- Check WebSocket connection in logs
- Ensure `VOICE_HOST` matches ngrok URL exactly

## Development Workflow

### Making Code Changes

1. **Edit your code** in the `app/` directory
2. **Rebuild and restart**:
   ```bash
   ./podman-stop.sh && ./podman-start.sh
   ```
3. **Test your changes** by calling the number

### Testing Without Phone Calls

You can test HTTP endpoints directly:

```bash
# Test TwiML endpoint
curl -X POST http://localhost:8000/voice

# Get orders JSON
curl http://localhost:8000/orders.json

# Create test orders
curl -X POST "http://localhost:8000/api/seed?n=3"
```

### Viewing Orders Data

```bash
# Read orders.json from container
podman exec boba-voice cat /app/app/orders.json | jq

# Or view in browser
open http://localhost:8000/orders.json
```

## Next Steps

- Read [Architecture Guide](doc-05-architecture.md) to understand how everything works
- Ready for production? See [Deployment Guide](doc-04-deployment.md)
- Need help? Check the application logs and verify your configuration

## Quick Reference

**Start Development Environment:**
```bash
./podman-start.sh
# Update .env with ngrok URL
ngrok http 8000
```

**Test:**
```bash
open http://localhost:8000/orders
# Call your Twilio number
```

**Stop:**
```bash
./podman-stop.sh
# Press Ctrl+C in ngrok terminal
```
