def format_bytes(num_bytes: int) -> str:
    num = float(max(0, int(num_bytes)))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for i, unit in enumerate(units):
        if num < 1024 or i == len(units) - 1:
            if unit == "B":
                return f"{int(num)} {unit}"
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{int(num_bytes)} B"
