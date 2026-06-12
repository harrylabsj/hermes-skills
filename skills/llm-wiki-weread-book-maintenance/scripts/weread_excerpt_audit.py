#!/usr/bin/env python3
"""Audit WeRead-derived llm-wiki book pages for missing or shallow excerpt sections."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SOURCE_DIRS = (
    "微信读书",
    "raw/transcripts/微信读书",
    "raw/transcripts/书评 1",
)


@dataclass(frozen=True)
class SourceRecord:
    path: Path
    rel_path: str
    title: str
    note_count: int
    raw_highlights: int
    raw_comments: int
    is_standard: bool


@dataclass(frozen=True)
class AuditRow:
    rel_path: str
    title: str
    note_count: int
    raw_highlights: int
    raw_comments: int
    entity_paths: tuple[str, ...]
    has_excerpt: bool
    excerpt_items: int
    status: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def to_int(value: str | None) -> int:
    if not value:
        return 0
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else 0


def excerpt_section(text: str) -> str:
    match = re.search(r"(?ms)^## 书摘\s*$([\s\S]*?)(?=^## |\Z)", text)
    return match.group(1) if match else ""


def count_excerpt_items(text: str) -> int:
    section = excerpt_section(text)
    if not section:
        return 0
    quote_items = len(re.findall(r"(?m)^>\s*\S+", section))
    comment_items = len(re.findall(r"(?m)^(?:评论|想法|我的想法)[:：]", section))
    return max(quote_items, quote_items + comment_items)


def collect_sources(wiki_root: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for rel_dir in SOURCE_DIRS:
        source_dir = wiki_root / rel_dir
        if not source_dir.exists():
            continue
        for path in sorted(source_dir.rglob("*.md")):
            text = read_text(path)
            frontmatter = parse_frontmatter(text)
            note_count = to_int(frontmatter.get("noteCount"))
            raw_highlights = len(re.findall(r"(?m)^>\s*📌", text))
            raw_comments = len(re.findall(r"(?m)^###\s*划线评论", text))
            title = frontmatter.get("title") or path.stem
            is_standard = bool(
                note_count
                or frontmatter.get("doc_type") == "weread-highlights-reviews"
                or "bookId" in frontmatter
            )
            records.append(
                SourceRecord(
                    path=path,
                    rel_path=path.relative_to(wiki_root).as_posix(),
                    title=title,
                    note_count=note_count,
                    raw_highlights=raw_highlights,
                    raw_comments=raw_comments,
                    is_standard=is_standard,
                )
            )
    return records


def collect_entities(wiki_root: Path) -> list[tuple[Path, str]]:
    entity_dir = wiki_root / "entities"
    if not entity_dir.exists():
        return []
    return [(path, read_text(path)) for path in sorted(entity_dir.rglob("*.md"))]


def map_entities(source: SourceRecord, entities: list[tuple[Path, str]], wiki_root: Path) -> list[tuple[Path, str]]:
    mapped = [(path, text) for path, text in entities if source.rel_path in text]
    if mapped:
        return mapped

    stem = source.path.stem
    title = source.title
    candidates: list[tuple[Path, str]] = []
    for path, text in entities:
        if path.stem == stem or path.stem == title:
            candidates.append((path, text))
            continue
        frontmatter = parse_frontmatter(text)
        if frontmatter.get("title") in {stem, title}:
            candidates.append((path, text))
    return candidates


def audit(wiki_root: Path) -> list[AuditRow]:
    sources = collect_sources(wiki_root)
    entities = collect_entities(wiki_root)
    rows: list[AuditRow] = []

    for source in sources:
        if not source.is_standard:
            continue
        mapped = map_entities(source, entities, wiki_root)
        entity_paths = tuple(path.relative_to(wiki_root).as_posix() for path, _ in mapped)
        has_excerpt = any(re.search(r"(?m)^## 书摘\s*$", text) for _, text in mapped)
        excerpt_items = max((count_excerpt_items(text) for _, text in mapped), default=0)

        if source.note_count <= 0:
            status = "no_notes"
        elif not mapped:
            status = "source_unmapped"
        elif not has_excerpt:
            status = "needs_excerpt_backfill"
        elif source.raw_highlights and excerpt_items < source.raw_highlights:
            status = "needs_investigation"
        else:
            status = "complete"

        rows.append(
            AuditRow(
                rel_path=source.rel_path,
                title=source.title,
                note_count=source.note_count,
                raw_highlights=source.raw_highlights,
                raw_comments=source.raw_comments,
                entity_paths=entity_paths,
                has_excerpt=has_excerpt,
                excerpt_items=excerpt_items,
                status=status,
            )
        )
    return rows


def print_markdown(rows: list[AuditRow], limit: int) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1

    print("# WeRead Excerpt Audit")
    print()
    print("## Summary")
    print()
    print(f"- standard_sources: {len(rows)}")
    for status in sorted(counts):
        print(f"- {status}: {counts[status]}")

    backlog = [
        row
        for row in rows
        if row.status in {"needs_excerpt_backfill", "source_unmapped", "needs_investigation"}
    ]
    backlog.sort(key=lambda row: row.note_count, reverse=True)

    print()
    print("## Backlog")
    print()
    print("| status | noteCount | rawHighlights | excerptItems | source | entity |")
    print("| --- | ---: | ---: | ---: | --- | --- |")
    for row in backlog[:limit]:
        entity = ", ".join(row.entity_paths) if row.entity_paths else "-"
        print(
            f"| {row.status} | {row.note_count} | {row.raw_highlights} | "
            f"{row.excerpt_items} | {row.rel_path} | {entity} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", type=Path, help="Path to an llm-wiki root")
    parser.add_argument("--limit", type=int, default=80, help="Maximum backlog rows to print")
    args = parser.parse_args()

    wiki_root = args.wiki_root.expanduser().resolve()
    if not (wiki_root / "SCHEMA.md").exists():
        print(f"Not an llm-wiki root, missing SCHEMA.md: {wiki_root}", file=sys.stderr)
        return 2

    print_markdown(audit(wiki_root), args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
