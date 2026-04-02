#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
OPENCLAW_BIN="${OPENCLAW_BIN:-$OPENCLAW_HOME/bin/openclaw}"

PLUGIN_SRC="$REPO_ROOT/openclaw/extensions/reel-agent-bridge"
PLUGIN_DST="$OPENCLAW_HOME/extensions/reel-agent-bridge"
CONFIG_PATH="$OPENCLAW_HOME/openclaw.json"
WORKSPACE_STATE_PATH="${OPENCLAW_WORKSPACE_STATE_PATH:-$OPENCLAW_HOME/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json}"
REPO_ENV_PATH="${REEL_AGENT_ENV_PATH:-$REPO_ROOT/.env}"
TELEGRAM_ACCOUNT_ID="${OPENCLAW_TELEGRAM_ACCOUNT_ID:-realtor-social}"

if [[ ! -d "$PLUGIN_SRC" ]]; then
  echo "Missing plugin source: $PLUGIN_SRC" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Missing OpenClaw config: $CONFIG_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$PLUGIN_DST")"

if [[ -e "$PLUGIN_DST" && ! -L "$PLUGIN_DST" ]]; then
  BACKUP_ROOT="$OPENCLAW_HOME/extensions/.backups"
  mkdir -p "$BACKUP_ROOT"
  BACKUP_PATH="$BACKUP_ROOT/reel-agent-bridge-$(date +%Y%m%d-%H%M%S)"
  mv "$PLUGIN_DST" "$BACKUP_PATH"
  echo "Backed up existing local plugin to $BACKUP_PATH"
elif [[ -L "$PLUGIN_DST" ]]; then
  CURRENT_TARGET="$(readlink "$PLUGIN_DST" || true)"
  if [[ "$CURRENT_TARGET" != "$PLUGIN_SRC" ]]; then
    rm "$PLUGIN_DST"
  fi
fi

ln -sfn "$PLUGIN_SRC" "$PLUGIN_DST"

python3 - "$CONFIG_PATH" "$PLUGIN_DST" "$REPO_ROOT" "$REPO_ENV_PATH" "$WORKSPACE_STATE_PATH" "$TELEGRAM_ACCOUNT_ID" <<'PY'
import json
import os
import pathlib
import sys

config_path = pathlib.Path(sys.argv[1])
plugin_dst = sys.argv[2]
repo_root = sys.argv[3]
repo_env_path = sys.argv[4]
workspace_state_path = sys.argv[5]
telegram_account_id = sys.argv[6]


def load_dotenv(path_str: str) -> dict[str, str]:
    env: dict[str, str] = {}
    path = pathlib.Path(path_str)
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key.strip()] = value
    return env


def unique_paths(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = os.path.abspath(os.path.expanduser(value))
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


obj = json.loads(config_path.read_text(encoding="utf-8"))
plugin_env = load_dotenv(repo_env_path)

plugins = obj.setdefault("plugins", {})
load = plugins.setdefault("load", {})
paths = load.setdefault("paths", [])
if plugin_dst not in paths:
    paths.append(plugin_dst)

entries = plugins.setdefault("entries", {})
entry = entries.setdefault("reel-agent-bridge", {})
entry["enabled"] = True
cfg = entry.setdefault("config", {})

callback_secret = (
    cfg.get("callbackSecret")
    or plugin_env.get("OPENCLAW_CALLBACK_SECRET")
    or os.environ.get("OPENCLAW_CALLBACK_SECRET")
)
if not callback_secret:
    raise SystemExit(
        "Missing OPENCLAW_CALLBACK_SECRET. Add it to repo .env or export it before running install-local-wiring.sh."
    )

cfg["callbackSecret"] = callback_secret
cfg["telegramAccountId"] = cfg.get("telegramAccountId") or telegram_account_id
cfg["repoRoot"] = repo_root
cfg["repoEnvPath"] = repo_env_path
cfg["workspaceStatePath"] = workspace_state_path
cfg["mediaLocalRoots"] = unique_paths(
    list(cfg.get("mediaLocalRoots") or [])
    + [repo_root, os.path.join(repo_root, "skills", "listing-video", "output"), "/tmp"]
)

config_path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

if [[ -x "$OPENCLAW_BIN" ]]; then
  "$OPENCLAW_BIN" config validate
fi

cat <<EOF
OpenClaw wiring installed.
- repo source: $PLUGIN_SRC
- local mount: $PLUGIN_DST
- config updated: $CONFIG_PATH

Next:
1. Restart gateway: $OPENCLAW_BIN gateway restart
2. Verify plugin: $OPENCLAW_BIN plugins inspect reel-agent-bridge --json
EOF
