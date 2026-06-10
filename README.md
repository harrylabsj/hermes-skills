# Hermes Skills

Public Hermes-compatible skill tap.

## Install

Add this tap once:

```bash
hermes skills tap add <owner>/hermes-skills
```

Then search or install skills:

```bash
hermes skills search 京东
hermes skills install <owner>/hermes-skills/skills/jd-shopping
```

## Privacy Gate

Before publishing any skill to GitHub, ClawHub, Hermes, or another public registry, run:

```bash
python3 scripts/privacy_check.py skills/<skill-name>
```

The check fails on user-local absolute paths, private config files, non-placeholder email addresses, likely secrets, private keys, and optional custom denylist entries from `.privacy-denylist`.

## Skills

| Skill | What It Does | Install |
|-------|--------------|---------|
| `jd-shopping` | JD.com search, comparison, review analysis, SKU selection, and safe cart preparation before checkout/payment. | `hermes skills install <owner>/hermes-skills/skills/jd-shopping` |
| `find-her` | Respectful dating strategy, profile improvement, channel planning, and practical relationship coaching. | `hermes skills install <owner>/hermes-skills/skills/find-her` |
| `second-brain-aphorism` | Generate grounded Chinese reflections, aphorisms, quote-card lines, and daily thoughts from second-brain context. | `hermes skills install <owner>/hermes-skills/skills/second-brain-aphorism` |
