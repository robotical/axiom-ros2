def find_json_fragments(txt: str):
    """Return list of (start, end) indices for complete {...} JSON segments.
    Properly ignores braces inside JSON strings with escapes."""
    frags = []
    depth = 0
    start = -1
    in_str = False
    esc = False

    for i, ch in enumerate(txt):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
        elif ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    frags.append((start, i + 1))
                    start = -1
    return frags
