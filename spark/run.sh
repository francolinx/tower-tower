#!/usr/bin/env bash
# Start the Spark half in tmux session "tower".
#   ./run.sh          ASR container + tower-core
#   ./run.sh --llm    also start vLLM (Qwen3-4B, ~3 min to ready)
# Secrets are read from ~/cnh-prep/.env (never from the repo).
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE="${TOWER_ENV:-$HOME/cnh-prep/.env}"
VENV="${TOWER_VENV:-$HOME/cnh-venv}"

if [[ "${1:-}" == "--llm" ]]; then
  docker compose --profile llm up -d asr llm
else
  docker compose up -d asr
fi

echo "waiting for ASR on 127.0.0.1:8090 ..."
for _ in $(seq 1 60); do
  curl -sf 127.0.0.1:8090/healthz >/dev/null && break
  sleep 2
done

# --no-access-log: request URLs can carry room keys; we log our own content-free lines.
CORE_CMD="set -a; source '$ENV_FILE'; set +a; source '$VENV/bin/activate'; \
uvicorn tower.app:app --host 127.0.0.1 --port 8088 --no-access-log"

tmux has-session -t tower 2>/dev/null || tmux new-session -d -s tower -n shell
tmux kill-window -t tower:core 2>/dev/null || true
tmux new-window -t tower -n core -c "$PWD" "bash -lc \"$CORE_CMD\""

for _ in $(seq 1 30); do
  curl -sf 127.0.0.1:8088/healthz && echo && break
  sleep 1
done
echo "tower-core on 127.0.0.1:8088 (tmux attach -t tower). Public: tailscale funnel --bg 8088"
