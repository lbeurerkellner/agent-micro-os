# ---
# description: Prints current date and time. Supports optional --timezone TZ (IANA timezone, e.g., Europe/Berlin). Usage: date [--timezone TZ]
# network: 'disable'
# ---
import sys
from datetime import datetime

# Use zoneinfo if available (Python 3.9+), fallback to pytz if present
try:
    from zoneinfo import ZoneInfo
    zoneinfo_available = True
except Exception:
    zoneinfo_available = False


def print_usage():
    print('Usage: date [--timezone TZ]\n\nPrints current date and time.\n\nOptions:\n  --timezone TZ   IANA timezone name (e.g., Europe/Berlin). If omitted, uses local system time.\n  --help          Show this help message')

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        # No timezone, print local time
        now = datetime.now()
        print(now.strftime('%Y-%m-%d %H:%M:%S'))
        sys.exit(0)

    if '--help' in args or '-h' in args:
        print_usage()
        sys.exit(0)

    # parse --timezone
    tz = None
    if '--timezone' in args:
        i = args.index('--timezone')
        try:
            tz = args[i+1]
        except IndexError:
            print('Error: --timezone requires a value', file=sys.stderr)
            sys.exit(2)
    else:
        # If any single arg provided treat it as timezone for convenience
        if len(args) == 1:
            tz = args[0]

    if not tz:
        now = datetime.now()
        print(now.strftime('%Y-%m-%d %H:%M:%S'))
        sys.exit(0)

    if zoneinfo_available:
        try:
            tzobj = ZoneInfo(tz)
        except Exception as e:
            print(f'Error: unknown timezone "{tz}"', file=sys.stderr)
            sys.exit(3)
        now = datetime.now(tzobj)
        print(now.strftime('%Y-%m-%d %H:%M:%S %Z%z'))
        sys.exit(0)
    else:
        # Try pytz if available
        try:
            import pytz
            tzobj = pytz.timezone(tz)
            now = datetime.now(tzobj)
            print(now.strftime('%Y-%m-%d %H:%M:%S %Z%z'))
            sys.exit(0)
        except Exception:
            print('Error: zoneinfo not available and pytz not present, or unknown timezone', file=sys.stderr)
            sys.exit(4)

