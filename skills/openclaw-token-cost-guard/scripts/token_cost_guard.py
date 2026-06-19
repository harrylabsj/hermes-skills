#!/usr/bin/env python3
"""OpenClaw token cost monitor with threshold alerts.

The script is intentionally stdlib-only so it can run from cron, OpenClaw
jobs, or a regular shell without installing dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai") if ZoneInfo else timezone(timedelta(hours=8))


DEFAULT_PRICES_CNY = {
    "deepseek-v4-pro": {
        "cache_hit_cny_per_million": 0.025,
        "cache_miss_cny_per_million": 3.0,
        "output_cny_per_million": 6.0,
    },
    "deepseek-v4-flash": {
        "cache_hit_cny_per_million": 0.02,
        "cache_miss_cny_per_million": 1.0,
        "output_cny_per_million": 2.0,
    },
    "deepseek-chat": {
        "cache_hit_cny_per_million": 0.02,
        "cache_miss_cny_per_million": 1.0,
        "output_cny_per_million": 2.0,
    },
    "deepseek-reasoner": {
        "cache_hit_cny_per_million": 0.02,
        "cache_miss_cny_per_million": 1.0,
        "output_cny_per_million": 2.0,
    },
    "kimi-k2.6": {
        "cache_hit_cny_per_million": 1.16,
        "cache_miss_cny_per_million": 6.89,
        "output_cny_per_million": 29.0,
    },
    "kimi-k2.7-code": {
        "cache_hit_cny_per_million": 1.16,
        "cache_miss_cny_per_million": 6.89,
        "output_cny_per_million": 29.0,
    },
    "gateway-injected": {
        "cache_hit_cny_per_million": 0.0,
        "cache_miss_cny_per_million": 0.0,
        "output_cny_per_million": 0.0,
    },
}


@dataclass
class Bucket:
    calls: int = 0
    cache_miss_input: int = 0
    cache_hit_input: int = 0
    output: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0

    def add(self, miss: int, hit: int, output: int, total: int, cost_cny: float) -> None:
        self.calls += 1
        self.cache_miss_input += miss
        self.cache_hit_input += hit
        self.output += output
        self.total_tokens += total
        self.cost_cny += cost_cny

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "cache_miss_input": self.cache_miss_input,
            "cache_hit_input": self.cache_hit_input,
            "output": self.output,
            "total_tokens": self.total_tokens,
            "cost_cny": round(self.cost_cny, 6),
        }


@dataclass
class Snapshot:
    generated_at: str
    date: str
    total: Bucket
    by_model: dict[str, Bucket]
    by_agent: dict[str, Bucket]
    unpriced: dict[str, Bucket]
    usage_records: int
    priced_records: int

    def as_state(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "date": self.date,
            "total": self.total.as_dict(),
            "by_model": buckets_to_dict(self.by_model),
            "by_agent": buckets_to_dict(self.by_agent),
            "unpriced": buckets_to_dict(self.unpriced),
            "usage_records": self.usage_records,
            "priced_records": self.priced_records,
        }


@dataclass
class AlertResult:
    status: str
    should_alert: bool
    delta_cny: float = 0.0
    delta_percent: float | None = None
    previous_total_cny: float | None = None
    reason: str = ""


def buckets_to_dict(buckets: dict[str, Bucket]) -> dict[str, dict[str, Any]]:
    return {
        key: bucket.as_dict()
        for key, bucket in sorted(buckets.items(), key=lambda item: item[1].cost_cny, reverse=True)
    }


def default_openclaw_dir() -> Path:
    for env_name in ("OPENCLAW_STATE_DIR", "OPENCLAW_HOME"):
        value = os.environ.get(env_name)
        if value:
            return Path(value).expanduser()
    return Path.home() / ".openclaw"


def default_state_dir(openclaw_dir: Path) -> Path:
    value = os.environ.get("OPENCLAW_TOKEN_COST_GUARD_STATE_DIR")
    if value:
        return Path(value).expanduser()
    for env_name in ("HERMES_STATE_DIR", "HERMES_DATA_DIR"):
        value = os.environ.get(env_name)
        if value:
            return Path(value).expanduser() / "openclaw-token-cost-guard"
    return openclaw_dir / "token-cost-guard"


def parse_args() -> argparse.Namespace:
    default_threshold = float(os.environ.get("OPENCLAW_TOKEN_COST_THRESHOLD_CNY", "20"))
    default_percent = float(os.environ.get("OPENCLAW_TOKEN_COST_THRESHOLD_PERCENT", "0"))
    openclaw_dir = default_openclaw_dir()
    state_dir = default_state_dir(openclaw_dir)

    parser = argparse.ArgumentParser(description="Monitor OpenClaw token cost and alert on spikes.")
    parser.add_argument("--openclaw-dir", default=str(openclaw_dir))
    parser.add_argument("--date", help="Date to inspect in YYYY-MM-DD, default today in Asia/Shanghai.")
    parser.add_argument("--agent", action="append", help="Agent id to include. Repeatable. Defaults to all agents with sessions.")
    parser.add_argument("--pricing-file", help="JSON price override file.")
    parser.add_argument("--threshold-cny", type=float, default=default_threshold)
    parser.add_argument("--threshold-percent", type=float, default=default_percent)
    parser.add_argument("--state-file", default=str(state_dir / "state.json"))
    parser.add_argument("--reports-dir", default=str(state_dir / "reports"))
    parser.add_argument("--init-only", action="store_true", help="Write baseline without alerting.")
    parser.add_argument("--no-state-write", action="store_true", help="Do not update state file.")
    parser.add_argument("--always-report", action="store_true", help="Print report even when no alert fires.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--watch-interval", type=float, help="Run continuously every N seconds.")
    parser.add_argument("--send-openclaw", action="store_true", help="Send alert via `openclaw message send`.")
    parser.add_argument("--send-always", action="store_true", help="Send report even when no alert fires.")
    parser.add_argument("--channel", help="OpenClaw message channel, e.g. feishu.")
    parser.add_argument("--target", help="OpenClaw message target/chat id.")
    parser.add_argument("--account", help="Optional OpenClaw message account id.")
    parser.add_argument("--send-dry-run", action="store_true", help="Pass --dry-run to openclaw message send.")
    return parser.parse_args()


def target_date(args: argparse.Namespace) -> str:
    if args.date:
        return args.date
    return datetime.now(TZ_SHANGHAI).date().isoformat()


def load_prices(pricing_file: str | None) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = json.loads(json.dumps(DEFAULT_PRICES_CNY))
    if not pricing_file:
        return prices

    with open(pricing_file, "r", encoding="utf-8") as handle:
        overrides = json.load(handle)
    for model, value in overrides.items():
        prices[model] = {
            "cache_hit_cny_per_million": float(value.get("cache_hit_cny_per_million", value.get("cache_hit", 0))),
            "cache_miss_cny_per_million": float(value.get("cache_miss_cny_per_million", value.get("cache_miss", 0))),
            "output_cny_per_million": float(value.get("output_cny_per_million", value.get("output", 0))),
        }
    return prices


def discover_agents(openclaw_dir: Path, requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    agents_dir = openclaw_dir / "agents"
    if not agents_dir.exists():
        return []
    agents = []
    for child in sorted(agents_dir.iterdir()):
        if child.is_dir() and (child / "sessions").exists():
            agents.append(child.name)
    return agents


def parse_event_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            if number > 10_000_000_000:
                number = number / 1000.0
            return datetime.fromtimestamp(number, timezone.utc).astimezone(TZ_SHANGHAI).date().isoformat()
        text = str(value)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(TZ_SHANGHAI).date().isoformat()
    except Exception:
        return None


def normalize_model(provider: str | None, model: str | None) -> str | None:
    if not model:
        return None
    normalized = str(model)
    if provider == "deepseek" and not normalized.startswith("deepseek-"):
        normalized = f"deepseek-{normalized}"
    if "/" in normalized:
        normalized = normalized.split("/", 1)[1]
    return normalized


def usage_int(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            try:
                return int(value or 0)
            except Exception:
                return 0
    return 0


def compute_cost_cny(model: str, miss: int, hit: int, output: int, prices: dict[str, dict[str, float]]) -> float | None:
    price = prices.get(model)
    if price is None:
        return None
    return (
        miss * price["cache_miss_cny_per_million"]
        + hit * price["cache_hit_cny_per_million"]
        + output * price["output_cny_per_million"]
    ) / 1_000_000


def collect_snapshot(args: argparse.Namespace, prices: dict[str, dict[str, float]]) -> Snapshot:
    openclaw_dir = Path(args.openclaw_dir).expanduser()
    date = target_date(args)
    agents = discover_agents(openclaw_dir, args.agent)
    total = Bucket()
    by_model: dict[str, Bucket] = {}
    by_agent: dict[str, Bucket] = {}
    unpriced: dict[str, Bucket] = {}
    usage_records = 0
    priced_records = 0

    for agent in agents:
        sessions_dir = openclaw_dir / "agents" / agent / "sessions"
        if not sessions_dir.exists():
            continue
        by_agent.setdefault(agent, Bucket())
        for session_file in sorted(sessions_dir.glob("*.jsonl")):
            with open(session_file, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "message":
                        continue
                    message = event.get("message") or {}
                    if message.get("role") != "assistant":
                        continue
                    event_date = parse_event_date(event.get("timestamp") or message.get("timestamp"))
                    if event_date != date:
                        continue

                    usage = message.get("usage") or {}
                    model = normalize_model(message.get("provider"), message.get("model"))
                    if not model:
                        continue

                    miss = usage_int(usage, "input", "inputTokens") + usage_int(usage, "cacheWrite", "cacheWriteInputTokens")
                    hit = usage_int(usage, "cacheRead", "cacheReadInputTokens")
                    output = usage_int(usage, "output", "outputTokens")
                    total_tokens = usage_int(usage, "totalTokens", "total_tokens") or (miss + hit + output)
                    if not (miss or hit or output or total_tokens):
                        continue

                    usage_records += 1
                    cost_cny = compute_cost_cny(model, miss, hit, output, prices)
                    if cost_cny is None:
                        unpriced.setdefault(model, Bucket()).add(miss, hit, output, total_tokens, 0.0)
                        continue

                    priced_records += 1
                    total.add(miss, hit, output, total_tokens, cost_cny)
                    by_agent.setdefault(agent, Bucket()).add(miss, hit, output, total_tokens, cost_cny)
                    by_model.setdefault(model, Bucket()).add(miss, hit, output, total_tokens, cost_cny)

    return Snapshot(
        generated_at=datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds"),
        date=date,
        total=total,
        by_model=by_model,
        by_agent=by_agent,
        unpriced=unpriced,
        usage_records=usage_records,
        priced_records=priced_records,
    )


def load_previous_state(state_file: Path) -> dict[str, Any] | None:
    if not state_file.exists():
        return None
    try:
        with open(state_file, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def compare(snapshot: Snapshot, previous: dict[str, Any] | None, args: argparse.Namespace) -> AlertResult:
    if args.init_only:
        return AlertResult(status="initialized", should_alert=False, reason="baseline initialized")
    if not previous:
        return AlertResult(status="initialized", should_alert=False, reason="no previous snapshot")
    if previous.get("date") != snapshot.date:
        return AlertResult(status="initialized", should_alert=False, reason="new date baseline")

    previous_total = float((previous.get("total") or {}).get("cost_cny") or 0.0)
    current_total = snapshot.total.cost_cny
    delta = current_total - previous_total
    percent = (delta / previous_total * 100.0) if previous_total > 0 else None

    absolute_alert = delta > args.threshold_cny
    percent_alert = percent is not None and args.threshold_percent > 0 and percent > args.threshold_percent
    should_alert = absolute_alert or percent_alert
    reason_parts = []
    if absolute_alert:
        reason_parts.append(f"delta {delta:.2f} CNY > threshold {args.threshold_cny:.2f} CNY")
    if percent_alert:
        reason_parts.append(f"delta {percent:.1f}% > threshold {args.threshold_percent:.1f}%")

    return AlertResult(
        status="alert" if should_alert else "ok",
        should_alert=should_alert,
        delta_cny=delta,
        delta_percent=percent,
        previous_total_cny=previous_total,
        reason="; ".join(reason_parts) if reason_parts else "within threshold",
    )


def format_number(value: int) -> str:
    return f"{value:,}"


def top_rows(title: str, buckets: dict[str, Bucket], limit: int = 8) -> list[str]:
    rows = [f"## {title}", "", "| Name | Calls | Total tokens | Cost CNY |", "|---|---:|---:|---:|"]
    visible = [
        (name, bucket)
        for name, bucket in buckets.items()
        if bucket.calls > 0 or bucket.total_tokens > 0 or bucket.cost_cny > 0
    ]
    for name, bucket in sorted(visible, key=lambda item: item[1].cost_cny, reverse=True)[:limit]:
        rows.append(f"| {name} | {bucket.calls} | {format_number(bucket.total_tokens)} | {bucket.cost_cny:.2f} |")
    if len(rows) == 4:
        rows.append("| none | 0 | 0 | 0.00 |")
    rows.append("")
    return rows


def render_report(snapshot: Snapshot, result: AlertResult, args: argparse.Namespace) -> str:
    lines = [
        "# OpenClaw Token Cost Guard",
        "",
        f"- Status: {result.status.upper()}",
        f"- Date: {snapshot.date}",
        f"- Generated at: {snapshot.generated_at}",
        f"- Current known cost: {snapshot.total.cost_cny:.2f} CNY",
        f"- Current known tokens: {format_number(snapshot.total.total_tokens)}",
        f"- Usage records: {snapshot.usage_records} total, {snapshot.priced_records} priced",
        f"- Threshold: {args.threshold_cny:.2f} CNY"
        + (f" or {args.threshold_percent:.1f}%" if args.threshold_percent > 0 else ""),
    ]
    if result.previous_total_cny is not None:
        lines.extend(
            [
                f"- Previous known cost: {result.previous_total_cny:.2f} CNY",
                f"- Delta: {result.delta_cny:.2f} CNY"
                + (f" ({result.delta_percent:.1f}%)" if result.delta_percent is not None else ""),
            ]
        )
    lines.append(f"- Reason: {result.reason}")
    lines.append("")
    lines.extend(top_rows("Top Models", snapshot.by_model))
    lines.extend(top_rows("Top Agents", snapshot.by_agent))

    if snapshot.unpriced:
        lines.extend(["## Unpriced Models", "", "| Model | Calls | Total tokens |", "|---|---:|---:|"])
        for name, bucket in sorted(snapshot.unpriced.items(), key=lambda item: item[1].total_tokens, reverse=True):
            lines.append(f"| {name} | {bucket.calls} | {format_number(bucket.total_tokens)} |")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def write_report(report: str, snapshot: Snapshot, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.generated_at.replace(":", "").replace("+", "_").replace("-", "")
    path = reports_dir / f"token-cost-{snapshot.date}-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    return path


def write_state(snapshot: Snapshot, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(snapshot.as_state(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def send_openclaw(report: str, args: argparse.Namespace) -> None:
    if not args.channel or not args.target:
        raise SystemExit("--send-openclaw requires --channel and --target")
    command = ["openclaw", "message", "send", "--channel", args.channel, "--target", args.target, "--message", report]
    if args.account:
        command.extend(["--account", args.account])
    if args.send_dry_run:
        command.append("--dry-run")
    subprocess.run(command, check=True, timeout=60)


def run_once(args: argparse.Namespace, prices: dict[str, dict[str, float]]) -> int:
    state_file = Path(args.state_file).expanduser()
    reports_dir = Path(args.reports_dir).expanduser()
    previous = load_previous_state(state_file)
    snapshot = collect_snapshot(args, prices)
    result = compare(snapshot, previous, args)
    report = render_report(snapshot, result, args)
    report_path = write_report(report, snapshot, reports_dir)

    if not args.no_state_write:
        write_state(snapshot, state_file)

    if args.json:
        print(json.dumps({"result": result.__dict__, "snapshot": snapshot.as_state(), "report_path": str(report_path)}, ensure_ascii=False, indent=2))
    elif result.should_alert or args.always_report or args.init_only:
        print(report)
        print(f"Report: {report_path}")
    else:
        print(
            f"OK: current={snapshot.total.cost_cny:.2f} CNY, "
            f"delta={result.delta_cny:.2f} CNY, report={report_path}"
        )

    if args.send_openclaw and (result.should_alert or args.send_always):
        send_openclaw(report, args)

    return 2 if result.should_alert else 0


def main() -> int:
    args = parse_args()
    prices = load_prices(args.pricing_file)

    if args.watch_interval:
        exit_code = 0
        try:
            while True:
                exit_code = max(exit_code, run_once(args, prices))
                time.sleep(args.watch_interval)
        except KeyboardInterrupt:
            return exit_code
    return run_once(args, prices)


if __name__ == "__main__":
    raise SystemExit(main())
