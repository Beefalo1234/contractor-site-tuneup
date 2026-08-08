#!/usr/bin/env bash
# Start the Contractor Site Tune-Up lead relay + Cloudflare quick tunnel.
# Run:  bash start-relay.sh   (or double-click in git-bash)
# Prints the public form URL when the tunnel is up.
# Requires: python3, tools/cloudflared.exe (in this repo), relay/secrets.env
cd "$(dirname "$0")"

if [ ! -f relay/secrets.env ]; then
  echo "ERROR: relay/secrets.env missing. Copy relay/secrets.env.example to"
  echo "       relay/secrets.env and fill in TELEGRAM_BOT_TOKEN and"
  echo "       TELEGRAM_HOME_CHANNEL."
  exit 1
fi

echo "[start-relay] launching relay.py on 127.0.0.1:8791 ..."
python3 relay/relay.py > relay/relay.log 2>&1 &
RELAY_PID=$!
sleep 2

echo "[start-relay] launching cloudflared quick tunnel ..."
./tools/cloudflared.exe tunnel --url http://127.0.0.1:8791 --no-autoupdate \
  > relay/tunnel.log 2>&1 &
TUNNEL_PID=$!

echo "[start-relay] waiting for tunnel URL ..."
for i in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' relay/tunnel.log \
        | head -1)
  [ -n "$URL" ] && break
  sleep 2
done

if [ -n "$URL" ]; then
  echo "[start-relay] OK"
  echo "  Relay PID:   $RELAY_PID  (relay/relay.log)"
  echo "  Tunnel PID:  $TUNNEL_PID  (relay/tunnel.log)"
  echo "  Form API:    $URL/api/lead"
  echo "  Health:      $URL/health"
  echo "NOTE: if this URL changed, update site/config.js and push to GitHub."
  echo "$URL" > relay/tunnel-url.txt
else
  echo "[start-relay] tunnel URL not found yet; check relay/tunnel.log"
  exit 1
fi
