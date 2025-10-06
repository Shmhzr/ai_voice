# Deepgram BobaRista - Voice Ordering System

A production-ready voice ordering system for boba shops built with **FastAPI**, **Twilio**, and **Deepgram Agent API**. Features real-time voice conversations, SMS notifications, and live order dashboards.

## What is Deepgram BobaRista?

Deepgram BobaRista is an AI-powered voice ordering system that allows customers to call a phone number and place boba tea orders through natural conversation. The system uses advanced speech recognition, natural language processing, and text-to-speech to create a seamless ordering experience.

### Key Features

- 🎤 **Natural Voice Ordering**: Customers call and speak naturally to place orders
- 🤖 **AI-Powered Assistant**: Uses Deepgram's Agent API for intelligent conversation
- 📱 **SMS Notifications**: Automatic order confirmations and ready notifications
- 📊 **Real-time Dashboards**: Live order tracking for staff and customers
- 🏪 **Production Ready**: Containerized, scalable, and secure
- 🔧 **Easy Setup**: Complete documentation and deployment guides

## Demo

### How It Works

1. **Customer calls** your Twilio phone number
2. **AI greets** them: "Hey! I am your Deepgram BobaRista. What would you like to order?"
3. **Natural conversation** - Customer says: "I want a taro milk tea with boba"
4. **AI confirms** order details and asks for phone number
5. **Order placed** - Customer receives SMS confirmation with order number
6. **Staff sees** order on dashboard and prepares it
7. **Ready notification** - Customer gets SMS when order is ready

### Sample Conversation

```
Customer: "Hi, I'd like to order a taro milk tea with boba"
AI: "One taro milk tea with boba. Is that correct?"
Customer: "Yes, that's right"
AI: "Great! Would you like anything else?"
Customer: "No, that's all"
AI: "Can I please get your phone number for this order?"
Customer: "555-123-4567"
AI: "Thank you! Your order number is 4782. We'll text you when it's ready for pickup!"
```

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Customer      │    │   Twilio Voice   │    │   Your Server   │
│   (Phone Call)  │◄──►│   (Webhook)      │◄──►│   (FastAPI)     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │  Deepgram Agent │
                                               │  (STT + LLM + TTS)│
                                               └─────────────────┘
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │  Twilio SMS     │
                                               │  (Notifications)│
                                               └─────────────────┘
```

### Core Components

- **FastAPI Backend**: REST API + WebSocket bridge for audio streaming
- **Deepgram Agent**: Real-time speech-to-text, LLM reasoning, text-to-speech
- **Twilio Integration**: Voice calls + SMS notifications
- **Real-time Dashboard**: Server-Sent Events for live order updates
- **Containerized**: Podman/Docker with production-ready configuration

## Quick Start

### Prerequisites

- Python 3.11+
- Podman or Docker
- ngrok (for local testing)
- Twilio account with A2P 10DLC approval
- Deepgram API key

### 5-Minute Setup

```bash
# 1. Clone and setup
git clone https://github.com/your-username/DG-Boba-Assitant.git
cd DG-Boba-Assitant
cp sample.env.txt .env

# 2. Edit .env with your API keys
# - Get Deepgram API key: https://console.deepgram.com/
# - Get Twilio credentials: https://console.twilio.com/

# 3. Start the application
./podman-start.sh

# 4. Expose to internet (separate terminal)
ngrok http 8000

# 5. Configure Twilio webhook
# Use ngrok URL: https://your-ngrok-url.ngrok-free.app/voice
```

### Test Your Setup

1. **Call your Twilio number** - You should hear the AI greeting
2. **Place a test order** - Try: "I want a taro milk tea with boba"
3. **Check dashboards** - Visit `http://localhost:8000/orders` and `http://localhost:8000/barista`

### Production Deployment

For production deployment, see our comprehensive guides:

- **[Deployment Guide](documentations/doc-04-deployment.md)** - Complete production setup
- **[AWS EC2 Setup](documentations/doc-02-ec2-setup.md)** - Server configuration
- **[Twilio Setup](documentations/doc-03-twilio-setup.md)** - Phone number configuration
- **[Architecture Guide](documentations/doc-05-architecture.md)** - System design details

**Quick Production Commands:**
```bash
# On your server
git clone https://github.com/your-username/DG-Boba-Assitant.git /opt/bobarista
cd /opt/bobarista
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Configure .env and systemd service
sudo systemctl enable bobarista
sudo systemctl start bobarista
```

## Project Structure

```
DG-Boba-Assitant/
├── app/                          # Main application code
│   ├── main.py                   # FastAPI application entrypoint
│   ├── app_factory.py            # Application factory with lifecycle hooks
│   ├── settings.py               # Configuration and environment variables
│   ├── http_routes.py            # REST endpoints (Twilio webhooks, dashboards)
│   ├── ws_bridge.py              # WebSocket bridge for Twilio ↔ Deepgram audio
│   ├── agent_client.py           # Deepgram Agent API client
│   ├── agent_functions.py        # AI tool definitions and state management
│   ├── business_logic.py         # Core business logic (menu, cart, orders)
│   ├── orders_store.py           # Thread-safe JSON persistence layer
│   ├── events.py                 # Pub/sub system for real-time updates
│   ├── audio.py                  # Audio format conversion (µ-law ↔ Linear16)
│   ├── send_sms.py               # Twilio SMS integration
│   ├── session.py                # User session management
│   ├── call_logger.py            # Call logging and debugging
│   ├── order_ids.py              # Order ID generation utilities
│   └── orders.json               # Order storage (auto-reset on startup)
│
├── documentations/               # Comprehensive documentation
│   ├── doc-01-getting-started.md    # Local development setup
│   ├── doc-02-ec2-setup.md          # AWS EC2 configuration
│   ├── doc-03-twilio-setup.md       # Twilio phone & webhook setup
│   ├── doc-04-deployment.md         # Production deployment guide
│   ├── doc-05-architecture.md       # System design deep dive
│   └── doc-06-api-reference.md      # API endpoints documentation
│
├── Containerfile                 # Podman/Docker build configuration
├── podman-start.sh               # Local development script
├── podman-stop.sh                # Cleanup script
├── requirements.txt              # Python dependencies
├── sample.env.txt                # Environment variables template
└── README.md                     # This file
```

### Key Components

- **`app/`** - Core application logic and API endpoints
- **`documentations/`** - Complete setup and deployment guides
- **`Containerfile`** - Container configuration for easy deployment
- **`sample.env.txt`** - Template for environment configuration

## Technical Details

### Audio Processing Pipeline

1. **Twilio Input**: µ-law 8kHz audio from phone calls
2. **Resampling**: Convert to Linear16 48kHz for Deepgram
3. **Deepgram Processing**: STT → LLM reasoning → TTS
4. **Output**: Convert back to µ-law 8kHz for Twilio

### AI Agent Configuration

- **STT Model**: `nova-3` (real-time speech recognition)
- **LLM Model**: `gemini-2.5-flash` (reasoning and responses)
- **TTS Model**: `aura-2-odysseus-en` (natural voice synthesis)
- **Language**: English (`en`)

### State Management

- **Session-based**: Each call maintains isolated state
- **Thread-safe**: Concurrent call handling with proper locking
- **Persistent**: Orders stored in JSON with automatic cleanup
- **Real-time**: Live updates via Server-Sent Events

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Landing page |
| `/voice` | POST | Twilio webhook (call initiation) |
| `/twilio` | WS | WebSocket for audio streaming |
| `/orders` | GET | TV dashboard (large display) |
| `/barista` | GET | Staff console interface |
| `/orders.json` | GET | Orders data (JSON API) |

## Development Workflow

### Code Organization

- **Separation of Concerns**: Clear separation between HTTP routes, WebSocket handling, business logic, and AI integration
- **Dependency Injection**: Settings and services injected through FastAPI's dependency system
- **Error Handling**: Comprehensive error handling with proper HTTP status codes
- **Logging**: Structured logging for debugging and monitoring

### Testing

```bash
# Run tests (when implemented)
pytest

# Test specific components
pytest tests/test_business_logic.py
pytest tests/test_agent_functions.py
```

### Code Quality

- **Type Hints**: Full type annotation support
- **Linting**: Configure with your preferred linter (flake8, black, etc.)
- **Formatting**: Consistent code formatting

## Environment Configuration

Create `.env` file with required variables:

```bash
# Server Configuration
VOICE_HOST=your-domain.com
NGROK_HOST=your-ngrok-url.ngrok-free.app

# Deepgram API
DEEPGRAM_API_KEY=your_deepgram_key

# Twilio Voice (calls)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_E164=+1234567890
TWILIO_TO_E164=+1234567890

# Twilio SMS (notifications)
MSG_TWILIO_ACCOUNT_SID=your_msg_account_sid
MSG_TWILIO_AUTH_TOKEN=your_msg_auth_token
MSG_TWILIO_FROM_E164=+1234567890

# Agent Configuration
AGENT_LANGUAGE=en
AGENT_TTS_MODEL=aura-2-odysseus-en
AGENT_STT_MODEL=nova-3
```

## Monitoring & Debugging

### Logs

```bash
# View application logs
podman logs -f boba-voice

# View specific log levels
podman logs boba-voice | grep ERROR
```

### Debugging Tools

- **Call Logger**: Automatic logging of all call interactions
- **Order Tracking**: Complete order lifecycle logging
- **WebSocket Monitoring**: Real-time connection status
- **Error Reporting**: Detailed error messages with stack traces

## Production Considerations

### Performance

- **Concurrent Calls**: Supports multiple simultaneous calls
- **Memory Management**: Efficient audio processing with minimal memory footprint
- **Connection Pooling**: Optimized database and API connections

### Security

- **API Key Management**: Secure environment variable handling
- **Input Validation**: Comprehensive request validation
- **Rate Limiting**: Built-in protection against abuse
- **HTTPS**: SSL/TLS encryption for all communications

### Scalability

- **Horizontal Scaling**: Stateless design allows multiple instances
- **Load Balancing**: Compatible with standard load balancers
- **Database**: Easy migration to persistent database (PostgreSQL, etc.)

## Documentation

Comprehensive documentation available in the `documentations/` directory:

- **[Getting Started](documentations/doc-01-getting-started.md)**: Local development setup
- **[Architecture](documentations/doc-05-architecture.md)**: System design and component details
- **[API Reference](documentations/doc-06-api-reference.md)**: Complete API documentation
- **[Deployment](documentations/doc-04-deployment.md)**: Production deployment guide
- **[Troubleshooting](documentations/doc-07-troubleshooting.md)**: Common issues and solutions

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

See [Development Guide](documentations/doc-08-development.md) for detailed contribution guidelines.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Troubleshooting

### Common Issues

**Call not connecting?**
- Check if ngrok is running: `curl https://your-ngrok-url.ngrok-free.app/voice`
- Verify Twilio webhook URL is correct and uses HTTPS
- Check application logs: `podman logs -f boba-voice`

**No audio on call?**
- Ensure WebSocket URL uses `wss://` (not `ws://`)
- Check Deepgram API key is valid
- Verify `VOICE_HOST` matches your ngrok URL exactly

**SMS not sending?**
- Verify Twilio SMS credentials in `.env`
- Check phone number has SMS capability
- Review Twilio logs in console

### Quick Fixes

```bash
# Restart application
./podman-stop.sh && ./podman-start.sh

# Check logs
podman logs -f boba-voice

# Test endpoints
curl http://localhost:8000/orders.json
```

For detailed troubleshooting, check the application logs and verify your configuration.
