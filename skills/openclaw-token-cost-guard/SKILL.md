---
name: openclaw-token-cost-guard
description: Monitor OpenClaw token usage and model cost from session logs, compare the current run with the previous snapshot, and send an alert report when cost growth exceeds a threshold. Use when users ask to track OpenClaw token spend, calculate realtime token cost, detect spending spikes, monitor DeepSeek/Kimi/GPT model usage, or set up cost alerts for OpenClaw agents.
---

# OpenClaw Token Cost Guard

Use this skill to compute OpenClaw token costs from local session logs and warn when spend has increased too much since the previous run.

## Quick Start

Run a one-shot check for today:

```bash
python3 skills/openclaw-token-cost-guard/scripts/token_cost_guard.py --threshold-cny 20
```

When installed by Hermes and running from the skill directory:

```bash
python3 scripts/token_cost_guard.py --threshold-cny 20
```

Initialize a baseline without alerting:

```bash
python3 skills/openclaw-token-cost-guard/scripts/token_cost_guard.py --init-only
```

Run every 60 seconds:

```bash
python3 skills/openclaw-token-cost-guard/scripts/token_cost_guard.py --watch-interval 60 --threshold-cny 20
```

Send an alert through OpenClaw when the threshold is exceeded:

```bash
python3 skills/openclaw-token-cost-guard/scripts/token_cost_guard.py \
  --threshold-cny 20 \
  --send-openclaw \
  --channel feishu \
  --target <recipient-or-chat-id>
```

## Behavior

- Reads `~/.openclaw/agents/*/sessions/*.jsonl`.
- Defaults to today's Asia/Shanghai date.
- Computes cost by agent and model.
- Compares current total cost with the previous snapshot in `~/.openclaw/token-cost-guard/state.json`.
- Alerts when either condition is true:
  - absolute cost delta is greater than `--threshold-cny`
  - percentage delta is greater than `--threshold-percent`
- Writes Markdown reports to `~/.openclaw/token-cost-guard/reports/`.

## Hermes Compatibility

The bundled script is stdlib-only and can run under Codex, OpenClaw, Hermes, cron, or a plain shell.

Environment variables:

- `OPENCLAW_STATE_DIR` or `OPENCLAW_HOME`: override the OpenClaw state directory.
- `OPENCLAW_TOKEN_COST_GUARD_STATE_DIR`: override state/report storage.
- `HERMES_STATE_DIR` or `HERMES_DATA_DIR`: when present, default state/report storage goes under `<that-dir>/openclaw-token-cost-guard`.
- `OPENCLAW_TOKEN_COST_THRESHOLD_CNY`: default absolute alert threshold.
- `OPENCLAW_TOKEN_COST_THRESHOLD_PERCENT`: default percent alert threshold.

Hermes tap metadata lives in `skill.json`; ClawHub/OpenClaw marketplace metadata lives in `clawhub.json`.

## Pricing

The script embeds current DeepSeek official CNY prices per 1M tokens:

- `deepseek-v4-pro`: cache hit 0.025, cache miss 3, output 6
- `deepseek-v4-flash`: cache hit 0.02, cache miss 1, output 2
- `deepseek-chat` and `deepseek-reasoner` are treated as v4-flash compatibility aliases.

Known local CNY estimates are included for Kimi models. Unknown models are listed as unpriced unless OpenClaw recorded a usable `usage.cost.total`.

Use `--pricing-file <json>` to override or add prices. JSON shape:

```json
{
  "provider/model-or-model-id": {
    "cache_hit_cny_per_million": 0.02,
    "cache_miss_cny_per_million": 1.0,
    "output_cny_per_million": 2.0
  }
}
```

## Output Contract

When reporting results, include:

- current total known cost
- previous total and delta when available
- alert status and threshold
- top models by cost
- top agents by cost
- unpriced models, if any
