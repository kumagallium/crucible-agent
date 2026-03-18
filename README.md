# Crucible Agent

AI agent runtime that connects any frontend to MCP servers via LLM — domain behavior is driven by swappable prompt profiles.

## Architecture

```
Frontend (ELN, Chat UI, CLI, etc.)
    ↓ REST / WebSocket
┌─ Crucible Agent ──────────────────┐
│  FastAPI → Agent Runner → Adapter │
│                ↓             ↓    │
│           LiteLLM      MCP Servers│
│              ↓          (via SSE) │
│           LLM API                 │
│                                   │
│  PostgreSQL (provenance records)  │
└───────────────────────────────────┘
```

## Quick Start (Local Development)

```bash
git clone https://github.com/kumagallium/crucible-agent.git
cd crucible-agent
./setup.sh             # Generates .env from template
# Edit .env with your API keys
docker compose up -d
```

- API: http://localhost:8090
- Swagger UI: http://localhost:8090/docs
- LiteLLM Proxy: http://localhost:4000

## Server Deployment

Tested on **Ubuntu 22.04 LTS**. The setup script installs Docker, configures security hardening, and starts the application.

```bash
git clone https://github.com/kumagallium/crucible-agent.git
cd crucible-agent
sudo bash setup-server.sh
```

### What `setup-server.sh` does

| Step | Description |
|------|-------------|
| Docker | Installs Docker CE + Compose plugin |
| SSH | Key-only auth, root login disabled |
| Firewall (UFW) | Inbound deny (SSH only), outbound deny (allowlist) |
| fail2ban | Auto-ban after 5 failed SSH attempts (24h) |
| Docker iptables | Blocks external access to app ports, UDP flood protection |
| Auto-update | Unattended security patches |

### Options

```bash
# Change SSH port (recommended for production)
SSH_PORT=<your-port> sudo bash setup-server.sh
```

### Access after deployment

The application ports (8090, 4000) are **not exposed externally**. Use SSH tunnel to access:

```bash
ssh -L 8090:localhost:8090 -p <ssh-port> <user>@<server-ip>
# Then open http://localhost:8090/docs in your browser
```

## Configuration

Edit `.env` to configure:

```bash
# LLM (via LiteLLM Proxy)
LITELLM_API_BASE=http://litellm:4000
LLM_MODEL=your-model-name
SAKURA_AI_API_KEY=your-key
SAKURA_AI_API_BASE=https://your-endpoint

# Crucible (MCP server registry, optional)
CRUCIBLE_API_URL=http://crucible-api:8080
```

See [.env.example](.env.example) for all options.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/agent/run` | Run agent (synchronous) |

See [docs/api-spec.md](docs/api-spec.md) for full specification.

## Tech Stack

- **Runtime**: Python 3.12+ / FastAPI / uvicorn
- **Agent**: [mcp-agent](https://github.com/lastmile-ai/mcp-agent) (lastmile-ai)
- **LLM Gateway**: [LiteLLM](https://github.com/BerriAI/litellm) Proxy
- **Database**: PostgreSQL (provenance records)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for the phased implementation plan.

## License

[Apache-2.0](LICENSE)
