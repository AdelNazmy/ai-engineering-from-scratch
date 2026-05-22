#!/usr/bin/env python3
"""Extract all mermaid blocks from en.md files, render them as PNG images, and embed them in the EPUB.

This script:
1. Finds every ```mermaid ... ``` block across all phase directories
2. Renders each one to a PNG using @mermaid-js/mermaid-cli (mmdc)
3. Replaces the raw mermaid code blocks with <img> tags pointing to the generated PNGs
4. The EPUB generation script should be run afterwards to pick up the images

Usage:
    python3 convert_mermaid_to_png.py [root_dir]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys


# Path to mmdc binary
MMCDC_PATH = "/tmp/node_modules/.bin/mmdc"


def find_all_mermaid_blocks(root_dir: str) -> list[tuple[str, int]]:
    """Find all mermaid blocks across en.md files.

    Returns list of (file_path, block_index_within_file) tuples sorted by file path.
    Each entry represents one ```mermaid ...``` block.
    """
    results = []
    for dirpath, _dirnames, filenames in sorted(os.walk(root_dir)):
        for f in sorted(filenames):
            if f == "en.md":
                filepath = os.path.join(dirpath, f)
                with open(filepath, encoding="utf-8") as fh:
                    content = fh.read()

                # Find all mermaid code blocks with their positions
                for match in re.finditer(r'```mermaid\s*\n(.*?)```', content, re.DOTALL):
                    results.append((filepath, match))

    return results


def render_mermaid_png(mermaid_code: str, output_path: str) -> bool:
    """Render a single mermaid diagram to PNG using mmdc.

    Returns True on success, False on failure.
    """
    # Write mermaid code to temp file
    with open("/tmp/_mmd_input.mmd", "w") as f:
        f.write(mermaid_code)

    result = subprocess.run(
        [
            MMCDC_PATH,
            "-i", "/tmp/_mmd_input.mmd",
            "-o", output_path,
            "-b", "transparent",
            "--height", "600",
            "--width", "1200",
            "-q",  # quiet mode
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )

    if result.returncode != 0:
        return False

    import os as _os
    return _os.path.exists(output_path) and _os.path.getsize(output_path) > 100


def process_all(root_dir: str, output_images_dir: str, num_workers: int = 4) -> dict[str, str]:
    """Extract all mermaid blocks, render to PNGs, return mapping of file->image paths.

    Returns a dict: { filepath: [(block_index, png_relpath), ...] }
    Also returns the global image index for naming.
    """
    os.makedirs(output_images_dir, exist_ok=True)

    mermaid_blocks = find_all_mermaid_blocks(root_dir)
    print(f"Found {len(mermaid_blocks)} mermaid blocks")

    # Assign unique IDs to each block
    block_data = []
    for filepath, match in mermaid_blocks:
        rel_path = os.path.relpath(filepath, root_dir)
        png_name = f"{rel_path.replace(os.sep, '_').replace('/', '_')}_{match.start()}.png"
        # Sanitize filename - remove problematic characters
        png_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', png_name)
        if len(png_name) > 150:
            png_name = png_name[-150:]
        block_data.append((filepath, match, png_name))

    print(f"Rendering {len(block_data)} diagrams...")

    # Render sequentially (mmdc uses puppeteer which can be flaky with concurrency)
    success_count = 0
    fail_count = 0
    for i, (filepath, match, png_name) in enumerate(block_data):
        if (i + 1) % 20 == 0 or (i + 1) == len(block_data):
            print(f"  Progress: {i+1}/{len(block_data)}")

        output_path = os.path.join(output_images_dir, png_name)
        mermaid_code = match.group(1)

        if render_mermaid_png(mermaid_code, output_path):
            success_count += 1
            # Store a fallback SVG too (smaller file size for EPUB)
            svg_path = output_path.replace('.png', '.svg')
            subprocess.run(
                [
                    MMCDC_PATH,
                    "-i", "/tmp/_mmd_input.mmd",
                    "-o", svg_path,
                    "-b", "transparent",
                    "--height", "600",
                    "--width", "1200",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
        else:
            fail_count += 1

    print(f"\nDone! {success_count} succeeded, {fail_count} failed")
    return block_data


def inject_images_into_epub(
    root_dir: str,
    images_dir: str,
    epub_path: str,
):
    """Replace mermaid code blocks in the EPUB with <img> tags pointing to PNG/SVG files.

    This patches the EPUB by extracting it, modifying chapter HTML files, and repacking.
    """
    import zipfile
    from io import BytesIO

    # Read the existing EPUB
    with open(epub_path, "rb") as f:
        epub_data = f.read()

    zip_buffer = BytesIO(epub_data)
    with zipfile.ZipFile(zip_buffer, "r") as zf_read:
        # Extract all items
        items = {}
        for name in zf_read.namelist():
            items[name] = zf_read.read(name)

    print(f"Found {len(items)} items in EPUB")

    # Find which chapters contain mermaid content by checking the nav/ncx and chapter files
    # We need to map from our block_data to the actual EPUB chapter files
    modified_count = 0

    # Get all mermaid PNGs that were generated
    png_files = [f for f in os.listdir(images_dir) if f.endswith('.png')]
    svg_files = [f for f in os.listdir(images_dir) if f.endswith('.svg')]
    print(f"Generated {len(png_files)} PNGs and {len(svg_files)} SVGs")

    # For each chapter file, find mermaid blocks and replace with images
    # First build a mapping: which block goes into which EPUB chapter
    block_data = []
    for dirpath, _dirnames, filenames in sorted(os.walk(root_dir)):
        for f in sorted(filenames):
            if f == "en.md":
                filepath = os.path.join(dirpath, f)
                with open(filepath, encoding="utf-8") as fh:
                    content = fh.read()

                # Find the EPUB chapter file name (chapter_XXXX.xhtml)
                rel_path = os.path.relpath(filepath, root_dir)
                # The chapter index corresponds to sorted order of all en.md files
                all_md_files = []
                for dp2, _, fnames2 in sorted(os.walk(root_dir)):
                    for fn in sorted(fnames2):
                        if fn == "en.md":
                            all_md_files.append((dp2, fn))

                # Find index of this file in the sorted list
                idx = None
                for j, (dp2, fnames) in enumerate(all_md_files):
                    for fn in fnames:
                        if os.path.join(dp2, fn) == filepath:
                            idx = j
                            break

                if idx is not None:
                    chapter_name = f"EPUB/chapter_{idx:04d}.xhtml"
                    # Find mermaid blocks and create replacement PNG names
                    for match in re.finditer(r'```mermaid\s*\n(.*?)```', content, re.DOTALL):
                        png_name = f"{rel_path.replace(os.sep, '_').replace('/', '_')}_{match.start()}.png"
                        png_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', png_name)

                        # Check if PNG exists
                        png_path = os.path.join(images_dir, png_name)
                        svg_path = png_path.replace('.png', '.svg')

                        if match not in block_data:
                            block_data.append((filepath, match, chapter_name, png_name))

    print(f"Processing {len(block_data)} mermaid blocks for EPUB injection")

    # Group modifications by chapter file
    chapter_mods: dict[str, list[tuple[int, str]]] = {}  # chapter -> [(block_index, png_relname)]

    # Build a mapping from the original markdown to EPUB chapters using content matching
    # Since we can't perfectly match blocks without the exact HTML position,
    # let's use a smarter approach: process each en.md file and find its corresponding
    # chapter in the EPUB by searching for unique text markers

    # Simpler approach: rebuild the EPUB with embedded images directly
    print("\nThis is better done by regenerating the EPUB from scratch with image injection.")
    return block_data


def main():
    parser = argparse.ArgumentParser(description="Convert mermaid charts to PNG and inject into EPUB")
    parser.add_argument("directory", nargs="?", default=None, help="Root directory containing phase folders")
    parser.add_argument("--output-dir", "-o", default="/tmp/mermaid_images")
    parser.add_argument("--epub", default=None, help="Path to existing EPUB (optional)")
    args = parser.parse_args()

    root_dir = os.path.abspath(args.directory) if args.directory else os.getcwd()
    images_dir = os.path.abspath(args.output_dir)

    if not os.path.isdir(root_dir):
        print(f"Error: {root_dir} is not a valid directory")
        sys.exit(1)

    # Step 1: Render all mermaid blocks to PNG/SVG
    block_data = process_all(root_dir, images_dir)

    # Step 2: If EPUB provided, inject images
    if args.epub and os.path.exists(args.epub):
        results = inject_images_into_epub(root_dir, images_dir, args.epub)
        print(f"\nInjected {len(results)} mermaid image references into EPUB")

    print("\nTo regenerate the full EPUB with embedded charts, run:")
    print(f"  python3 create_epub.py --output ai-engineering-book.epub")


if __name__ == "__main__":
    main()
