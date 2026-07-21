# Self-hosted remote MCP gateway

The gateway lets ChatGPT Chat/Work and Claude Chat/Cowork access the same private GitHub event vaults
as local agents. It never reaches a user's local SQLite database.

## Security model

- The endpoint must be served over HTTPS and reachable from the vendor's cloud infrastructure.
- MCP authorization uses OAuth authorization code + PKCE, protected-resource metadata, audience
  binding, short-lived access tokens, rotating refresh tokens, and revocation.
- GitHub OAuth is a separate downstream grant. Its token is encrypted at rest; it is never passed
  through as an MCP token or returned by a tool.
- Every tool is scoped by authenticated GitHub subject and an explicit private-repository allowlist.
- Public repositories and repositories without push access are rejected.
- No raw transcript, local path, credential, or tool payload is written to Git.

## Create the GitHub OAuth app

Create one OAuth app for the deployment. Set its callback URL to:

```text
https://memory.example.com/oauth/github/callback
```

Record the client ID and secret in the deployment secret manager. Generate the encryption key once:

```text
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Losing this key makes stored GitHub grants unreadable. Do not commit it or place it in Compose YAML.

## Required environment

```text
EMU_MEM_GATEWAY_BASE_URL=https://memory.example.com
EMU_MEM_GATEWAY_GITHUB_CLIENT_ID=...
EMU_MEM_GATEWAY_GITHUB_CLIENT_SECRET=...
EMU_MEM_GATEWAY_ENCRYPTION_KEY=...
EMU_MEM_GATEWAY_GITHUB_ALLOWLIST=alice,bob
EMU_MEM_GATEWAY_GITHUB_WEBHOOK_SECRET=...
```

Install `emu-ai-mem[gateway]` and run `emu-mem gateway --host 0.0.0.0 --port 8000`, or use the
Compose deployment. Configure TLS at the reverse proxy. `/health` is public; `/mcp` is protected.

## Connect clients

Register `https://memory.example.com/mcp` as a custom MCP app/connector. The user signs in with
GitHub and then calls `configure_github_vault` for each selected private repository. Team/workspace
owners may need to approve the connector and write actions. Test a read before enabling writes.

## Webhook and polling

Configure a GitHub push webhook for `/webhooks/github` with the matching secret. The gateway also
refreshes GitHub state before explicit reads/sync, so missed webhooks recover without data loss.

## Backup, upgrade, and key rotation

Back up the persistent `/data` volume and deployment secrets separately. Stop the service or take a
consistent SQLite backup before copying files. Git events remain the content recovery source, but
OAuth grants and vault mappings live only in gateway storage.

Before rotating the encryption key, decrypt and re-encrypt every stored GitHub token in one
maintenance transaction. v2 deliberately refuses to start with an invalid key rather than silently
discarding grants. Upgrade a staging deployment first, run OAuth/search/write/revoke smoke tests,
then replace production containers while preserving `/data`.

## Reverse proxy and firewall

Terminate TLS with Caddy, nginx, or the organization's ingress. Forward the original host/proto,
limit request size, rate-limit authorization endpoints, and expose only HTTPS. If vendor cloud IP
ranges are allowlisted, update them according to the vendor's current documentation.
