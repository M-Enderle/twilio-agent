# Twilio Agent - Intelligent Voice & SMS Assistant

A production-ready Twilio-powered agent that handles voice calls and SMS messages for emergency services (locksmith and towing services). Built with FastAPI, Redis, and containerized for easy deployment.

## ✨ Features

- **Intelligent Call Routing**: AI-powered intent classification to route calls to appropriate services
- **Voice Interaction**: Natural language processing for German voice interactions  
- **SMS Support**: Text message handling and responses
- **Location Services**: GPS location sharing and address validation
- **Emergency Services**: Specialized workflows for locksmith and towing services
- **Real-time Processing**: WebSocket support for live interactions
- **Production Ready**: Docker containerization with nginx, SSL, monitoring

## 🚀 Quick Start

### Development Setup

1. **Clone and setup:**
   ```bash
   git clone <repository>
   cd twilio-agent
   cp .env.production.template .env
   # Update .env with your credentials
   ```

2. **Start development server:**
   ```bash
   ./scripts/dev-start.sh
   ```

3. **Access the application:**
   - API: http://localhost:8000
   - Health check: http://localhost:8000/health
   - Docs: http://localhost:8000/docs

### Production Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for comprehensive deployment instructions.

**Quick deployment:**
```bash
# On your server
./scripts/server-setup.sh
./scripts/deploy.sh your-domain.com your-email@example.com
```

## 📋 Requirements

### Development
- Python 3.10+
- Poetry or pip
- Redis (via Docker)

### Production  
- Ubuntu 20.04+ server
- Docker & Docker Compose
- Domain name with SSL
- 2GB+ RAM, 20GB+ storage

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TWILIO_ACCOUNT_SID` | Your Twilio Account SID | ✅ |
| `TWILIO_AUTH_TOKEN` | Your Twilio Auth Token | ✅ |
| `TWILIO_PHONE_NUMBER` | Your Twilio phone number | ✅ |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for notifications | ✅ |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for alerts | ✅ |
| `MAPS_API_KEY` | Google Maps API key | ✅ |
| `REDIS_URL` | Redis connection URL | ✅ |
| `DOMAIN` | Your domain name | ✅ (production) |

### Twilio Webhooks

Configure these URLs in your Twilio Console:

- **Voice URL**: `https://your-domain.com/incoming-call`
- **SMS URL**: `https://your-domain.com/webhook/sms` 
- **Status Callback**: `https://your-domain.com/webhook/status`

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Twilio API    │───▶│   Nginx Proxy   │───▶│  FastAPI App    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                         │
                        ┌─────────────────┐              │
                        │   Redis Cache   │◀────────────┘
                        └─────────────────┘
```

## 📁 Project Structure

```
twilio-agent/
├── twilio_agent/              # Main application package
│   ├── main.py   # FastAPI app and call routing
│   ├── actions/              # Twilio and Redis integrations
│   └── utils/                # AI, location, pricing utilities
├── data/                     # ZIP code databases
├── templates/                # HTML templates for location sharing
├── nginx/                    # Nginx configuration
├── scripts/                  # Deployment and maintenance scripts
├── docker-compose.prod.yml   # Production Docker setup
├── Dockerfile               # Application container
└── DEPLOYMENT.md           # Comprehensive deployment guide
```

## 🔄 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check for monitoring |
| `/incoming-call` | POST | Twilio voice webhook |
| `/webhook/sms` | POST | Twilio SMS webhook |
| `/webhook/status` | POST | Twilio status callback |
| `/location/{session_id}` | GET | Location sharing page |
| `/api/location` | POST | Submit GPS coordinates |

## 🛠️ Development

### Local Development

1. **Install dependencies:**
   ```bash
   poetry install
   # or
   pip install -r requirements.txt
   ```

2. **Start Redis:**
   ```bash
   docker-compose up -d redis
   ```

3. **Run the application:**
   ```bash
   uvicorn twilio_agent.main:app --reload
   ```

### Testing

Tests live in the `tests/` directory and mirror the source tree structure:

```
tests/
├── twilio_agent/
│   ├── utils/
│   │   ├── test_contacts.py
│   │   ├── test_ai.py
│   │   └── ...
│   ├── test_main.py
│   └── ...
└── ...
```

**Install test dependencies (one-time):**
```bash
poetry add --group dev pytest pytest-asyncio
```

**Run all tests:**
```bash
poetry run pytest
```

**Run tests with verbose output:**
```bash
poetry run pytest -v
```

**Run a specific test file:**
```bash
poetry run pytest tests/twilio_agent/utils/test_contacts.py
```

**Run a specific test function:**
```bash
poetry run pytest tests/twilio_agent/utils/test_contacts.py::test_function_name
```

**Run tests matching a keyword:**
```bash
poetry run pytest -k "keyword"
```

**Check code formatting:**
```bash
poetry run black twilio_agent/
poetry run isort twilio_agent/
```

## 📊 Monitoring & Operations

### Health Monitoring
- Health endpoint: `/health`
- Container health checks
- Automated monitoring script: `./scripts/monitor.sh`

### Logging
- Structured logging with rotation
- Centralized logs in `/opt/twilio-agent/logs/`
- Error alerting via email/Telegram

### Backups
- Automated daily Redis backups
- Configuration backup
- 7-day retention policy

### Maintenance Commands

```bash
# View logs
docker-compose logs -f app

# Restart services  
docker-compose restart

# Update application
./scripts/update.sh

# Create backup
./backup.sh

# System monitoring
./scripts/monitor.sh
```

## 🔒 Security

- **SSL/TLS**: Automatic Let's Encrypt certificates
- **Firewall**: UFW with minimal open ports
- **Rate Limiting**: API endpoint protection
- **Container Security**: Non-root user, isolated networks
- **Input Validation**: Sanitized user inputs
- **Secret Management**: Environment variable isolation

## 📈 Scaling

### Horizontal Scaling
- Multiple app instances behind nginx
- Redis clustering for high availability
- Load balancer for multi-server setup

### Performance Optimization
- Redis caching and persistence
- Nginx compression and caching
- Container resource limits
- Database connection pooling

## 🆘 Troubleshooting

### Common Issues

**Application not starting:**
```bash
# Check logs
docker-compose logs app

# Verify environment variables
cat .env.production
```

**SSL certificate issues:**
```bash
# Regenerate certificate
docker-compose run --rm certbot
docker-compose restart nginx
```

**High resource usage:**
```bash
# Check resource usage
docker stats

# Restart services
docker-compose restart
```

See [DEPLOYMENT.md](./DEPLOYMENT.md) for comprehensive troubleshooting.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Support

For deployment issues, check:
1. [DEPLOYMENT.md](./DEPLOYMENT.md) - Comprehensive deployment guide
2. Application logs: `docker-compose logs app`
3. System logs: `/var/log/twilio-agent/`
4. Health check: `https://your-domain.com/health`

---

**Built with ❤️ for reliable emergency service coordination**