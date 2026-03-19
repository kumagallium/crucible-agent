FROM python:3.12-slim

# Node.js for MCP stdio servers (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY src/ src/
COPY scripts/ scripts/
COPY mcp_agent.config.yaml .
COPY chat-ui/ chat-ui/

# Expose port
EXPOSE 8090

# Run
CMD ["uv", "run", "uvicorn", "crucible_agent.main:app", "--host", "0.0.0.0", "--port", "8090"]
