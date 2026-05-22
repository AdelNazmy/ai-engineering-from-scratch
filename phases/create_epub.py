#!/usr/bin/env python3
"""Generate an EPUB book from all en.md files found recursively under a directory.

Files are sorted by their full path so that content appears in sequential order
following the traversal (phase 00 -> 01 -> ... -> 19).

Mermaid code blocks are automatically rendered to PNG images using @mermaid-js/mermaid-cli
(mmdc) and embedded as <img> tags directly inside the EPUB archive.

The TOC uses proper nested structure: phase directories appear as clickable
parent entries, and each chapter is listed underneath its parent phase.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
from html import escape as html_escape


try:
    from ebooklib import epub
except ImportError:
    print("Installing ebooklib...")
    os.system(f"{sys.executable or 'python'} -m pip install ebooklib")
    from ebooklib import epub

import markdown


# Path to mmdc binary (mermaid CLI)
MMCDC_PATH = "/tmp/node_modules/.bin/mmdc"


def find_en_md_files(root_dir: str) -> list[str]:
    """Recursively find all en.md files under root_dir, sorted by path."""
    result = []
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for f in filenames:
            if f == "en.md":
                result.append(os.path.join(dirpath, f))
    result.sort()
    return result


def md_to_html(md_text: str) -> str:
    """Convert markdown text to HTML."""
    return markdown.markdown(
        md_text,
        extensions=[
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
            "attr_list",
            "md_in_html",
        ],
    )


def extract_title(md_text: str) -> str:
    """Extract the first # heading as the chapter title."""
    for line in md_text.splitlines():
        if line.startswith("# ") and not line.startswith("##"):
            return line[2:].strip()
        if line.startswith("#") and not line.startswith("##"):
            return line.lstrip("# ").strip()
    return "Untitled"


def render_mermaid_to_png(mermaid_code: str) -> bytes | None:
    """Render a single mermaid diagram to PNG.

    Returns raw PNG bytes, or None if rendering fails.
    """
    try:
        with open("/tmp/_mmd_input.mmd", "w") as f:
            f.write(mermaid_code)

        result = subprocess.run(
            [
                MMCDC_PATH,
                "-i", "/tmp/_mmd_input.mmd",
                "-o", "/tmp/_mmd_output.png",
                "-b", "transparent",
                "--height", "600",
                "--width", "1200",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )

        if result.returncode != 0 or not os.path.exists("/tmp/_mmd_output.png"):
            return None

        with open("/tmp/_mmd_output.png", "rb") as f:
            data = f.read()

        if len(data) < 50:
            return None

        return data

    except Exception as e:
        print(f"  Mermaid render error: {e}")
        return None


def process_markdown_with_mermaid(md_text: str, book: epub.EpubBook) -> tuple[str, list[epub.EpubItem]]:
    """Process markdown text, converting mermaid code blocks to <img> tags.

    Returns (processed_html_string, list_of_image_items_to_add).
    """
    image_items = []

    def replace_mermaid_block(match):
        mermaid_code = match.group(1)
        png_data = render_mermaid_to_png(mermaid_code.strip())

        if png_data:
            # Create a unique ID for this image in the EPUB
            hash_key = hashlib.sha256(png_data).hexdigest()[:8]
            img_id = f"mermaid_{hash_key}"
            epub_img_name = f"{img_id}.png"

            # Add image as an EpubItem (static item, not a chapter)
            epub_img = epub.EpubItem(
                uid=img_id,
                file_name=f"images/{epub_img_name}",
                media_type="image/png",
                content=png_data,
            )
            book.add_item(epub_img)
            image_items.append(epub_img)

            return f'<div class="mermaid-figure"><img src="images/{epub_img_name}" alt="Diagram" style="max-width: 95%; height: auto; display: block; margin: 1em auto;"/></div>'
        else:
            # Fallback: keep the mermaid code as a styled pre block
            return f'<pre style="background:#f6f8fa;padding:12px;border-radius:6px;font-family:monospace;"><code>{html_escape(mermaid_code.strip())}</code></pre>'

    result = re.sub(r'```mermaid\s*\n(.*?)```', replace_mermaid_block, md_text, flags=re.DOTALL)
    return result, image_items


def build_epub(
    md_files: list[str],
    output_path: str,
    book_title: str = "AI Engineering From Scratch",
) -> None:
    """Build an EPUB from a sorted list of markdown files."""

    book = epub.EpubBook()

    # Metadata
    book.add_metadata("", "title", book_title)
    book.add_metadata("", "creator", "AI Engineering From Scratch")
    book.add_metadata("", "language", "en")
    book.add_metadata(
        "",
        "description",
        "Complete AI Engineering curriculum from scratch.",
    )

    # Collect phase directory -> list of (index, title) for the nested TOC.
    phase_dirs: dict[str, list[tuple[int, str]]] = {}
    total_images = 0

    for i, md_path in enumerate(md_files):
        with open(md_path, encoding="utf-8") as fh:
            raw = fh.read()

        title = extract_title(raw)

        # Process mermaid blocks -> convert to <img> tags and embed PNGs into EPUB
        processed_md, image_items = process_markdown_with_mermaid(raw, book)
        total_images += len(image_items)

        html_body = md_to_html(processed_md)

        # Inject table border CSS if this chapter contains a <table>.
        if "<table>" in html_body:
            css_block = """<style>
  table {
    border-collapse: collapse;
    margin: 1em 0;
    font-size: 0.95em;
  }
  th, td {
    border: 1px solid #bbb;
    padding: 6px 10px;
    text-align: left;
  }
  thead th {
    background: #f4f4f4;
    font-weight: 600;
  }
</style>"""
            html_body = css_block + "\n" + html_body

        # Build a minimal HTML document wrapping the converted markdown.
        html_content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{html_escape(title)}</title></head>
<body>
{html_body}
</body>
</html>"""

        chapter = epub.EpubHtml(
            title=title,
            file_name=f"chapter_{i:04d}.xhtml",
            content=html_content.encode("utf-8"),
            uid=f"chapter_{i}",
        )

        book.add_item(chapter)
        book.spine.append(chapter)

        # Collect phase directory info for the nested nav TOC.
        rel = os.path.relpath(md_path)
        parts = rel.split(os.sep)
        phase_dir = parts[0] if len(parts) > 1 else "__root__"
        phase_dirs.setdefault(phase_dir, []).append((i, title))

    # Build individual HTML pages for each phase header.
    phase_pages: dict[str, str] = {}
    for phase_dir in sorted(phase_dirs.keys()):
        chapters = phase_dirs[phase_dir]
        first_chapter_idx = chapters[0][0]

        page_html = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{html_escape(phase_dir)}</title></head>
<body>
<h1>{html_escape(phase_dir)}</h1>
<p>Chapters {first_chapter_idx + 1} to {first_chapter_idx + len(chapters)}: {len(chapters)} lessons</p>
<nav>
<a href="chapter_{first_chapter_idx:04d}.xhtml">Start reading &rarr;</a>
</nav>
</body>
</html>"""

        phase_page = epub.EpubHtml(
            title=phase_dir,
            file_name=f"phase_{phase_dir.replace('/', '_')}.xhtml",
            content=page_html.encode("utf-8"),
            uid=f"phase_{phase_dir}",
        )
        book.add_item(phase_page)
        phase_pages[phase_dir] = f"phase_{phase_dir.replace('/', '_')}.xhtml"

        # Add phase pages to the spine so readers can navigate to them.
        book.spine.append(phase_page)

    # Build the nested TOC using tuple-based structure.
    toc: list = []
    for phase_dir in sorted(phase_dirs.keys()):
        chapters = phase_dirs[phase_dir]

        toc.append(
            (
                epub.Link(
                    href=phase_pages[phase_dir],
                    title=phase_dir,
                    uid=f"toc_phase_{phase_dir}",
                ),
                [
                    epub.Link(
                        href=f"chapter_{idx:04d}.xhtml",
                        title=title,
                        uid=f"toc_chap_{idx}",
                    )
                    for idx, title in chapters
                ],
            )
        )

    book.toc = toc  # Tuple-based nested structure drives both nav.xhtml and .ncx.

    # Add EpubNav and EpubNcx so ebooklib writes nav.xhtml and toc.ncx to the archive.
    nav_item = epub.EpubNav()
    book.add_item(nav_item)

    ncx_item = epub.EpubNcx()
    book.add_item(ncx_item)

    # Write the EPUB file — this auto-generates nav.xhtml and .ncx from book.toc.
    epub.write_epub(output_path, book)
    print(f"\nEPUB written to: {os.path.abspath(output_path)}")
    print(f"  Chapters : {len(md_files)}")
    print(f"  Mermaid images embedded: {total_images}")


def main():
    parser = argparse.ArgumentParser(
        description="Build an EPUB from all en.md files found recursively."
    )
    parser.add_argument(
        "directory", nargs="?", default=None, help="Root directory to search.",
    )
    parser.add_argument("--output", "-o", default="ai-engineering-from-scratch.epub")
    args = parser.parse_args()

    root = os.path.abspath(args.directory) if args.directory else os.getcwd()
    if not os.path.isdir(root):
        print(f"Error: {root} is not a valid directory.")
        sys.exit(1)

    md_files = find_en_md_files(root)
    if not md_files:
        print("No en.md files found.")
        sys.exit(0)

    build_epub(md_files, args.output)


if __name__ == "__main__":
    main()
