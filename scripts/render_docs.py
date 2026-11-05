"""Render the repo's Markdown files into browser-viewable HTML under docs/html/.

Markdown stays the source of truth. Each output page embeds its Markdown text and
renders it in the browser with marked and mermaid (loaded from a CDN), so this
script needs only the standard library.

Usage:
    python3 scripts/render_docs.py              # render every Markdown file in the repo
    python3 scripts/render_docs.py DESIGN.md    # render specific files
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "html"
SKIP_DIRS = {".git", ".venv", "vendor", "node_modules", "docs/html"}

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --border: #d1d9e0;
          --code-bg: #f6f8fa; --link: #0969da; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --border: #3d444d;
            --code-bg: #151b23; --link: #4493f8; }}
  }}
  body {{ background: var(--bg); color: var(--fg); margin: 0;
         font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica,
               Arial, sans-serif; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 32px 16px 64px; }}
  .source {{ color: var(--muted); font-size: 13px; margin-bottom: 24px; }}
  a {{ color: var(--link); }}
  h1, h2 {{ border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }}
  code {{ background: var(--code-bg); padding: 0.15em 0.35em; border-radius: 4px;
         font: 85% ui-monospace, SFMono-Regular, Menlo, monospace; }}
  pre {{ background: var(--code-bg); padding: 16px; border-radius: 6px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; display: block; overflow-x: auto; margin: 16px 0; }}
  th, td {{ border: 1px solid var(--border); padding: 6px 12px;
           text-align: left; vertical-align: top; }}
  th {{ background: var(--code-bg); }}
  .mermaid {{ text-align: center; margin: 16px 0; }}
</style>
</head>
<body>
<main>
<div class="source">Generated from <code>{source}</code>. Edit the Markdown, not this file.</div>
<article id="content">Loading...</article>
</main>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>
  const markdownSource = {markdown_json};
  const article = document.getElementById("content");
  article.innerHTML = marked.parse(markdownSource);
  for (const link of article.querySelectorAll("a[href]")) {{
    const href = link.getAttribute("href");
    if (!/^[a-z]+:/i.test(href) && /\\.md(#.*)?$/.test(href)) {{
      link.setAttribute("href", href.replace(/\\.md(#.*)?$/, ".html$1"));
    }}
  }}
  for (const block of article.querySelectorAll("code.language-mermaid")) {{
    const diagram = document.createElement("div");
    diagram.className = "mermaid";
    diagram.textContent = block.textContent;
    block.parentElement.replaceWith(diagram);
  }}
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  mermaid.initialize({{ startOnLoad: false, theme: dark ? "dark" : "default" }});
  mermaid.run();
</script>
</body>
</html>
"""


def is_skipped(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT).as_posix()
    return any(relative == skip or relative.startswith(skip + "/") for skip in SKIP_DIRS)


def find_markdown_files() -> list[Path]:
    return sorted(path for path in REPO_ROOT.rglob("*.md") if not is_skipped(path))


def output_path_for(source: Path) -> Path:
    return (OUTPUT_DIR / source.relative_to(REPO_ROOT)).with_suffix(".html")


def render(source: Path) -> Path:
    text = source.read_text(encoding="utf-8")
    relative = source.relative_to(REPO_ROOT).as_posix()
    # Escape "</" so the embedded text can never close the <script> tag early.
    markdown_json = json.dumps(text).replace("</", "<\\/")
    page = PAGE_TEMPLATE.format(
        title=html.escape(f"{source.stem} (Memex)"),
        source=html.escape(relative),
        markdown_json=markdown_json,
    )
    target = output_path_for(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    return target


def main(args: list[str]) -> int:
    sources = [Path(arg).resolve() for arg in args] if args else find_markdown_files()
    for source in sources:
        if source.suffix != ".md" or not source.is_file():
            print(f"skipped (not a Markdown file): {source}", file=sys.stderr)
            continue
        if not source.is_relative_to(REPO_ROOT) or is_skipped(source):
            continue
        target = render(source)
        print(target.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
