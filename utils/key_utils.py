def mask_key(key: str) -> str:
    if not key or len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}{'•' * (len(key) - 8)}{key[-4:]}"
