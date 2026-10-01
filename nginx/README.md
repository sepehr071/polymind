# Nginx (prod origin)

Live prod vhost is **server-managed** at `/etc/nginx/sites-available/unichat`.
Repo copies:

| File | Role |
|------|------|
| `conf.d/unichat-limits.conf` | `limit_req` / `limit_conn` zones (http context) |
| `sites-available/unichat.conf` | unichat.example.com vhost + limits on `/api/` |
| `server.conf` / `nginx.conf` | Docker/Swarm reference only |

## Deploy on prod

```bash
# 1) zones
sudo cp nginx/conf.d/unichat-limits.conf /etc/nginx/conf.d/unichat-limits.conf

# 2) prod real client IP (regenerate periodically)
curl -fsSL https://cdn.example.com/ips.txt | \
  awk '{print "set_real_ip_from "$1";"}' | \
  sudo tee /etc/nginx/conf.d/cdn-set-real-ip.conf >/dev/null
printf '%s\n' 'real_ip_header X-Forwarded-For;' 'real_ip_recursive on;' | \
  sudo tee -a /etc/nginx/conf.d/cdn-set-real-ip.conf >/dev/null

# 3) site
sudo cp nginx/sites-available/unichat.conf /etc/nginx/sites-available/unichat
sudo nginx -t && sudo systemctl reload nginx
```

## Limits (defaults)

- Per client: **20** concurrent connections to `/api/`
- Global vhost API: **180** concurrent connections
- Rate: **40 req/s** per client, burst 80 (health burst 120)
- Over limit → **HTTP 429**

SSE is not gzipped (`text/event-stream` omitted from gzip_types).
