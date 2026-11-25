# Running and sharing the app

## 1. Give someone their own copy (recommended)
They need [Docker Desktop](https://docs.docker.com/get-docker/) and, for real AI replies, a free GroqCloud API key ([console.groq.com/keys](https://console.groq.com/keys)).

```sh
git clone <this repository> && cd <folder>
./scripts/setup.sh          # macOS / Linux / Git Bash
.\scripts\setup.ps1         # Windows PowerShell
```
The script:
1. Checks Docker.
2. Creates `.env` with a random database password.
3. Asks for the API key. Pressing Enter starts the app with simulated replies instead.
4. Builds and starts the containers.
5. Waits until they are healthy.
6. Runs the self-check.

It ends with the URL to open (default http://localhost:8080).

Each copy has its own database, accounts and API key. Nothing is shared between installs.

## 2. Let people on your network use your running app
The web container listens on all network interfaces on `WEB_PORT` (default 8080).

1. Find your computer's address. On Windows run `ipconfig` and look for the IPv4 address, e.g. `192.168.1.23`.
2. Others open `http://192.168.1.23:8080`.
3. If they can't connect, allow the port through the firewall. On Windows, run this in an **admin** PowerShell:
   ```powershell
   New-NetFirewallRule -DisplayName "AI Assistant 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
   ```
4. Each person registers their own account and only sees their own conversations.

Things to know:
- **Shared quota:** everyone uses *your* Groq key and its free-tier limit (about 8000 tokens/min in total). With several active users, expect "busy, try again" messages.
- **Open registration:** anyone who can reach the URL can create an account. Only share on networks you trust.
- **No encryption:** traffic is plain HTTP on the local network.

## 3. Putting it on the internet
Don't expose port 8080 directly. Put it behind HTTPS, then set `COOKIE_SECURE=true` in `.env` and run `docker compose up -d`. Options:
- **A tunnel** (no open ports, quickest for a demo): Cloudflare Tunnel or ngrok pointed at `http://localhost:8080`.
- **A reverse proxy** with automatic certificates, such as Caddy, on a server you control.

Before doing this, consider V6 items: account controls, abuse and rate limits per IP, backups and monitoring.

## Everyday operations
| Task | Command |
|---|---|
| Status | `docker compose ps` |
| Health and self-check | `./scripts/setup.sh --check` (or `.\scripts\setup.ps1 -Check`) |
| Self-check including a real AI call | `docker compose exec api python -m app.doctor --live` |
| Logs | `docker compose logs -f api` |
| Update after pulling new code | `./scripts/setup.sh` (rebuilds, migrates, re-checks) |
| Stop / start | `docker compose stop` / `docker compose start` |
| Back up the database | `docker compose exec -T db pg_dump -U assistant assistant > backup.sql` |
| Restore a backup | `docker compose exec -T db psql -U assistant assistant < backup.sql` |
| Remove everything **including data** | `docker compose down -v` |

**Starting automatically:** every container uses `restart: unless-stopped`, so the app comes back whenever Docker starts. To have Docker start when you log in, enable *Docker Desktop → Settings → General → "Start Docker Desktop when you sign in"*.

**If your `.env` password and the database disagree:** the database password is fixed when the volume is first created. If you delete `.env` and run setup again, the new random password will not match the existing data. Either restore the old `POSTGRES_PASSWORD`, or reset with `docker compose down -v`, which **deletes all data**.
