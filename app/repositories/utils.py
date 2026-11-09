def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so user input is matched literally (escape char: ``\\``)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
