"""Human-readable formatting of times, sizes and distances."""
import datetime as dt
import os


def fmt_time(ns):
    return dt.datetime.fromtimestamp(ns / 1e9).strftime("%Y-%m-%d %H:%M:%S") if ns else "—"


def fmt_date(ns):
    return dt.datetime.fromtimestamp(ns / 1e9).strftime("%Y-%m-%d")


def fmt_clock(ns):
    return dt.datetime.fromtimestamp(ns / 1e9).strftime("%H:%M:%S")


def fmt_dur(ns):
    s = int(round(ns / 1e9))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def fmt_size(n):
    """Decimal units (1 GB = 1000³ bytes), as file managers show them."""
    if n < 1000:
        return f"{n:.0f} B"
    for unit in ("kB", "MB", "GB", "TB"):
        n /= 1000
        if round(n, 1) < 1000 or unit == "TB":  # 999.96 kB shows as 1.0 MB, not 1000.0 kB
            return f"{n:.1f} {unit}"


def fmt_dist(m):
    return f"{m / 1000:.2f} km" if m >= 1000 else f"{m:.0f} m"


def plural(n, word):
    """plural(1, 'gap') -> '1 gap', plural(3, 'gap') -> '3 gaps'."""
    return f"{n} {word}{'' if n == 1 else 's'}"


def home_short(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path
