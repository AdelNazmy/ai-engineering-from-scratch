#!/usr/bin/env python3
"""Generate an EPUB book from all en.md files found recursively under a directory.

Files are sorted by their full path so that content appears in sequential order
following the traversal (phase 00 -> 01 -> ... -> 19).

The TOC uses proper nested structure: phase directories appear as clickable
parent entries, and each chapter is listed underneath its parent phase.
"""

import argparse
import os
import sys
from html import escape as html_escape


try:
    from ebooklib import epub
except ImportError:
    print("Installing ebooklib...")
    os.system(f"{sys.executable or 'python'} -m pip install ebooklib")
    from ebooklib import epub

import markdown


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

    for i, md_path in enumerate(md_files):
        with open(md_path, encoding="utf-8") as fh:
            raw = fh.read()

        title = extract_title(raw)
        html_body = md_to_html(raw)

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

    # Build the nested TOC using tuple-based structure.
    # ebooklib's _get_nav interprets tuples as (parent, [children]) for nesting.
    toc: list = []
    for phase_dir in sorted(phase_dirs.keys()):
        chapters = phase_dirs[phase_dir]

        # Phase header link -> children are the chapters under this phase.
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
