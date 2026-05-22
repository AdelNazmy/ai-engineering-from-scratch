---
name: epub-generator
description: Generate EPUB books from markdown files with mermaid diagrams, nested TOC, and table styling. Use when building an EPUB from en.md files across phase directories. Triggers: "generate epub", "build ebook", "create epub book".
---

# EPUB Generator Skill

Generate EPUB books from recursively-sorted `en.md` markdown files with:
- Nested TOC (phase directories as clickable parents, chapters nested underneath)
- Mermaid diagrams rendered to PNG images embedded in the archive
- Table border CSS injected into all chapters containing tables

## Prerequisites

### Python packages
```bash
pip install ebooklib markdown
# Requires ebooklib 0.20 — older versions lack EpubNav/EpubNcx support
```

### Node.js: mermaid CLI (mmdc)
Install once in a temp directory to avoid polluting the workspace:
```bash
mkdir -p /tmp/mermaid-cli && cd /tmp/mermaid-cli
npm init -y --yes
npm install @mermaid-js/mermaid-cli
# Binary at: /tmp/mermaid-cli/node_modules/.bin/mmdc
```

Set `MMCDC_PATH` in the script to point here. If your environment differs, update this path.

## Workflow

1. **Find all en.md files** under the root directory, sorted by full path (phase 00 → phase 19).
2. **For each file**, extract the title (first `#` heading), then process markdown:
   - Convert ```mermaid ...``` blocks to `<img>` tags pointing to embedded PNGs
   - Render each diagram via `mmdc -i /tmp/_mmd_input.mmd -o /tmp/_mmd_output.png`
3. **Inject table CSS** into every chapter containing a `<table>`:
   ```css
   table { border-collapse: collapse; }
   th, td { border: 1px solid #bbb; padding: 6px 10px; text-align: left; }
   thead th { background: #f4f4f4; font-weight: 600; }
   ```
4. **Build nested TOC** using tuple-based structure: `(link, [children])`.

## Critical Pitfalls & How to Avoid Them

### 1. Phase directories don't appear in the TOC (silent failure)
**Pitfall:** Setting `book.toc = [epub.Link(...), ...]` as a flat list does NOT create nested TOC entries. Many e-readers show only chapter titles, no phase headers.

**Fix:** Use **tuple-based nesting**: `(epub.Link(href=..., title="phase-name"), [list of child epub.Link objects])`. The `_get_nav` method in ebooklib interprets tuples as parent→children for both nav.xhtml and toc.ncx generation.

### 2. No nav.xhtml or toc.ncx generated (broken EPUB)
**Pitfall:** `ebooklib.EpubBook` does NOT auto-generate `nav.xhtml` or `.ncx`. The `write_epub()` method only writes these files if an `EpubNav` and/or `EpubNcx` item exists in the book. Without them, e-readers cannot read the TOC at all — `epub.read_epub()` crashes with `AttributeError: 'NoneType' object has no attribute 'get_name'`.

**Fix:** Always add both before calling `write_epub()`:
```python
book.add_item(epub.EpubNav())   # Generates nav.xhtml
book.add_item(epub.EpubNcx())   # Generates toc.ncx
```

### 3. Mermaid code blocks show as raw text (not rendered)
**Pitfall:** The `markdown` library does not natively render mermaid diagrams. They appear as `<pre><code>mermaid ...</code></pre>` which e-readers can't display visually.

**Fix:** Process mermaid blocks **before** calling `markdown.markdown()`:
- Use regex to find ```mermaid ...``` blocks in raw markdown
- Render each via subprocess call to `mmdc` → PNG bytes
- Replace the block with `<img src="images/mermaid_*.png">`
- Add each PNG as an `epub.EpubItem` (uid, file_name, media_type="image/png", content=raw_bytes) so it gets included in the EPUB archive

### 4. Mermaid images not visible in e-reader (missing from archive)
**Pitfall:** Writing PNGs to a directory on disk and referencing them via relative paths in HTML does NOT work — those files are never added to the EPUB zip. The `img src` path becomes a dead reference.

**Fix:** Add each rendered PNG as an `epub.EpubItem` with `media_type="image/png"` and raw bytes content. This registers it in the manifest and writes it into the archive at `images/mermaid_*.png`.

### 5. Table borders invisible (subtle rendering issue)
**Pitfall:** The markdown library's `tables` extension outputs bare `<table><thead><tbody>` with no CSS. Most e-readers render tables without any visible borders, making data unreadable.

**Fix:** Inject a `<style>` block into the `<head>` of every chapter that contains a `<table>`. Check with `if "<table>" in html_body:` before injecting. The CSS must use `border-collapse: collapse` and explicit `1px solid #bbb` on both `th` and `td`.

### 6. ebooklib version mismatch
**Pitfall:** Older versions of ebooklib (pre-0.20) may lack proper EpubNav/EpubNcx support or have bugs in nested TOC handling.

**Fix:** Pin to version 0.20+. Check with `pip show ebooklib | grep Version`.

### 7. mmdc rendering silently fails
**Pitfall:** Puppeteer (used by mmdc) can fail due to missing system dependencies (libX11, libnss3, etc.) or network issues during font/icon downloads. The subprocess returns a non-zero exit code but the output file may not exist.

**Fix:** Always check `result.returncode`, verify the output file exists AND has size > 50 bytes. On failure, fall back to rendering as SVG (smaller file) or keep the raw mermaid code in a styled `<pre>` block. Add timeout protection (`timeout=90`).

### 8. Large EPUB file size from many diagrams
**Pitfall:** 266+ PNGs can push an EPUB over 50-100 MB, which may not open on all e-readers (Kindle limits ~100MB).

**Fix:** Consider: reducing mmdc `--width`/`--height`, using lower `--scale` factor, or selectively rendering only the most important diagrams. SVG embeds are much smaller but have limited e-reader support.

## Reference Files
- **Main script**: `create_epub.py` — full implementation
- **Standalone renderer**: `render_mermaid.py` — can be run separately to pre-render all diagrams
