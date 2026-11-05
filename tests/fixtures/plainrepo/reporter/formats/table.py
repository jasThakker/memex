"""Plain text table output. Its folder has no __init__.py (a namespace package)."""


def render_table(rows: list[str]) -> str:
    return "\n".join(f"| {row} |" for row in rows)
