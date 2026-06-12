---
name: llm-wiki-weread-book-maintenance
description: Maintain and validate llm-wiki book pages compiled from WeRead or 微信读书 note exports. Use when compiling WeRead notes into wiki entity pages, backfilling complete archival 书摘 sections, auditing missing excerpts, preserving highlights and comments, deepening book pages, repairing source mappings, or verifying index and link integrity.
license: MIT
metadata:
  version: 1.1.0
  author: Hermes Agent
  tags:
    - llm-wiki
    - weread
    - knowledge-management
    - obsidian
    - book-notes
    - excerpt-audit
  hermes:
    category: knowledge-management
    tags:
      - llm-wiki
      - weread
      - book-notes
      - obsidian
---

# LLM Wiki WeRead Book Maintenance

Use this skill as the WeRead-specific compiler and validation layer for an existing Karpathy-style `llm-wiki`. It complements the base `llm-wiki` workflow and any local vault overlay. For WeRead sources, source mapping alone is not completion: a valid book page needs both a concise synthesis layer and a complete archival evidence layer.

## 1. Orient first

Before editing, read:

1. `SCHEMA.md`
2. `index.md`
3. recent `log.md`

Then inspect the live WeRead source folders. Do not assume a single historical path. Check these candidates when they exist:

- `微信读书/`
- `raw/transcripts/微信读书/`
- `raw/transcripts/书评 1/`

Treat a Markdown source as a standard WeRead export when it contains `noteCount:` and normal book metadata such as `bookId:`, `title:`, `author:`, `reviewCount:`, or `doc_type: weread-highlights-reviews`.

## 2. Completion rule

For a standard WeRead source with `noteCount > 0`, the mapped book entity page is incomplete if either condition holds:

- the page lacks `## 书摘`
- the `## 书摘` section contains fewer highlight/comment records than the raw source

This is true even when the page already contains good sections such as `## 核心框架`, `## 深化洞察`, or `## 对我的启发`.

Classify each standard source as one of:

- `complete`
- `no_notes`
- `needs_excerpt_backfill`
- `source_unmapped`
- `nonstandard_source`
- `needs_investigation`

## 3. Compilation contract

Separate deterministic extraction from LLM synthesis.

Archival evidence layer:

- Copy all original highlights / 划线 and user comments / 想法 into `## 书摘`.
- Preserve raw reading order as much as possible.
- Group excerpts under chapter/section headings when the raw source has them.
- Keep each comment attached to its original highlight.
- Keep highlights without comments.
- Do not compress, paraphrase, deduplicate, rewrite, or select only important excerpts.
- Do not ask the LLM to generate or summarize `## 书摘`.

Synthesis layer:

- Use the LLM for `一句话总结`, `核心框架`, `深化洞察`, `对我的启发`, wikilinks, tags, and concise interpretation.
- Keep synthesis compact because the full evidence is preserved in `## 书摘`.
- Link to at least two existing relevant `entities/` or `concepts/` pages when possible.

## 4. Managed excerpt block

When backfilling or recompiling an existing page, preserve frontmatter and human-written material. Prefer replacing only a managed excerpt block:

```markdown
<!-- BEGIN WEREAD_EXCERPTS -->
## 书摘
...
<!-- END WEREAD_EXCERPTS -->
```

If an old page has `## 书摘` without markers, preserve the rest of the page and replace only that section after confirming it is generated or stale. Do not overwrite handcrafted synthesis sections unless the user explicitly asks for regeneration.

## 5. Recommended page shape

For standard WeRead-derived book pages, use this body order unless the vault schema says otherwise:

1. `## 一句话总结`
2. `## 核心框架`
3. `## 深化洞察`
4. `## 对我的启发`
5. `## 书摘`
6. `## 章节索引`
7. `## 相关`
8. `## 来源`

Recommended WeRead status fields:

```yaml
weread_book_id: BOOK_ID_IF_PRESENT
weread_note_count: RAW_NOTE_COUNT
source_path: 微信读书/BOOK_TITLE.md
source_hash: OPTIONAL_HASH_OF_RAW_BODY
compiled_at: YYYY-MM-DD
compile_status: complete
```

Use `compile_status: no_notes`, `needs_excerpt_backfill`, `source_unmapped`, `nonstandard_source`, or `needs_investigation` when completion is blocked, unnecessary, or uncertain.

## 6. Batch workflow

1. Run an audit before editing. Prefer `scripts/weread_excerpt_audit.py` when available:

```bash
python3 scripts/weread_excerpt_audit.py /path/to/llm-wiki
```

2. Select a conservative batch:
   - start with 10-20 books
   - prioritize mapped standard WeRead sources with high `noteCount`
   - use `noteCount >= 20` as a good first high-value cutoff
3. For each selected source:
   - map it to an existing `entities/*.md` page via `sources:` or body source links
   - avoid creating duplicates when punctuation variants already exist
   - preserve existing page frontmatter and synthesis
   - insert or refresh the managed `## 书摘` block
   - bump `updated` and set or refresh WeRead status fields when the schema allows them
4. Verify:
   - raw highlight/comment counts match the generated `## 书摘` records
   - comments remain attached to their highlights
   - new wikilinks resolve
   - `index.md` still points at existing files
5. Log once for the whole batch:
   - append a concise `log.md` entry
   - for large batches, create `_meta/weread-excerpt-backfill-YYYY-MM-DD.md` with counts, changed pages, skipped sources, and remaining backlog

## 7. Mapping repair

When a WeRead source appears unmapped:

- Search by exact source relative path first.
- Search by `bookId`, title, and normalized title variants.
- Check for punctuation variants, subtitles, or duplicate book pages.
- Prefer updating the existing best book page over creating a new page.
- If two legitimate pages exist, merge only after confirming `entity_type`, author, sources, note count, and current links.
- Keep raw sources immutable; repair entity pages and navigation.

## 8. Index and link repair

If many index links are broken because filenames drifted, rebuild navigation from the live filesystem and frontmatter instead of hand-patching dozens of links.

When fixing bare wikilinks inside notes:

- Rewrite a bare link only when it matches exactly one existing page stem in `entities/` or `concepts/`.
- Do not auto-fix ambiguous links.
- Do not create low-confidence concept pages just to satisfy links.
- Classify missing links into high-value concept gaps, low-value text mentions, and true broken references.

## 9. Verification checklist

Before finishing:

- `SCHEMA.md`, `index.md`, and recent `log.md` were consulted.
- Standard WeRead sources were separated from nonstandard files, essays, templates, trackers, and external analyses.
- Every touched standard WeRead page with `noteCount > 0` has `## 书摘`.
- `## 书摘` was copied deterministically from the raw source, not summarized by the LLM.
- Raw highlight/comment counts were compared against generated excerpt records.
- High-note-count pages were spot-checked manually.
- Existing human synthesis was preserved unless regeneration was requested.
- New links resolve, and index entries point to current filenames.
- One concise batch log entry was appended.

## 10. Page-size tradeoff

Default to keeping complete `## 书摘` in the book entity page because the user expects extracted notes to be available inside the wiki. If pages become too large for reading, embeddings, or sync, propose a two-layer structure only after user approval:

- `entities/BOOK.md` for synthesis and navigation
- `entities/_excerpts/BOOK-书摘.md` for complete archival excerpts

Do not silently move full excerpts out of the entity page; that changes the retrieval and reading contract.
