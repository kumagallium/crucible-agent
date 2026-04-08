# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| latest  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in Crucible Agent, please report it responsibly.

### How to Report

1. **Do NOT open a public issue** for security vulnerabilities
2. Email: **kumagallium@gmail.com**
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

This is a volunteer-maintained project, so we cannot guarantee specific response times. That said, we will do our best to:

- **Acknowledge** your report promptly
- **Assess** the issue and communicate next steps
- **Prioritize** fixes based on severity

### Scope

The following are in scope:

- API authentication bypasses
- Prompt injection leading to unauthorized tool execution
- SQL injection in provenance storage
- Unauthorized access to MCP server credentials
- WebSocket session hijacking
- Command injection via CLI tool execution

The following are out of scope:

- Issues in third-party dependencies (report upstream)
- Denial of service via legitimate API usage
- Attacks requiring access to the host server

## Security Architecture

Crucible Agent includes several security measures:

- **API key authentication**: Optional but recommended for production
- **CORS restrictions**: Configurable allowed origins
- **CLI allowlist**: Only explicitly permitted CLI tools can be executed
- **SSH tunnel access**: Production deployments are not exposed to the public internet
- **Token masking**: Sensitive values are masked in logs

## Disclosure Policy

We follow a coordinated disclosure process. Please allow us reasonable time to address the issue before public disclosure.
