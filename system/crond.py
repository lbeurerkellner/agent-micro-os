"""Cron daemon — runs scheduled jobs from /etc/crontab and /etc/cron.d/ for each user."""

import asyncio
import io
import re
from dataclasses import dataclass
from fs.providers import ModelProvider
from system.context import SystemContext
from datetime import datetime

import structlog

log = structlog.get_logger("crond")

# Matches ANSI escape sequences (colors, cursor movement, spinners, etc.)
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\r')


@dataclass
class CronJob:
    minute: str
    hour: str
    dom: str  # day of month
    month: str
    dow: str  # day of week
    command: str


def parse_crontab(content: str) -> list[CronJob]:
    """Parse crontab file content into a list of CronJob entries.

    Format: m h dom mon dow command...
    Lines starting with # are comments. Blank lines are skipped.
    """
    jobs = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue  # malformed line
        jobs.append(CronJob(
            minute=parts[0],
            hour=parts[1],
            dom=parts[2],
            month=parts[3],
            dow=parts[4],
            command=parts[5],
        ))
    return jobs


def matches_field(spec: str, value: int) -> bool:
    """Check if a cron field specification matches a given value.

    Supports: * (any), */N (step), N (exact), N,M (list), N-M (range).
    """
    for part in spec.split(','):
        part = part.strip()
        if part == '*':
            return True
        if part.startswith('*/'):
            step = int(part[2:])
            if step > 0 and value % step == 0:
                return True
        elif '-' in part:
            lo, hi = part.split('-', 1)
            if int(lo) <= value <= int(hi):
                return True
        else:
            if int(part) == value:
                return True
    return False


def job_matches(job: CronJob, dt: datetime) -> bool:
    """Check if a cron job should run at the given datetime."""
    return (
        matches_field(job.minute, dt.minute)
        and matches_field(job.hour, dt.hour)
        and matches_field(job.dom, dt.day)
        and matches_field(job.month, dt.month)
        and matches_field(job.dow, dt.isoweekday() % 7)  # 0=Sun, 1=Mon, ..., 6=Sat
    )


CRONTAB_PATH = "etc/crontab"
CRON_D_PATH = "etc/cron.d"
CRON_LOG_PATH = "var/log/cron.log"


def collect_jobs(vault) -> list[CronJob]:
    """Collect all cron jobs from /etc/crontab and /etc/cron.d/*.

    Returns the combined list of jobs from all sources.
    """
    jobs = []

    # Read /etc/crontab
    if vault.exists(CRONTAB_PATH):
        try:
            content = vault.read(CRONTAB_PATH).decode('utf-8')
            jobs.extend(parse_crontab(content))
        except Exception:
            pass

    # Read each file in /etc/cron.d/
    if vault.exists(CRON_D_PATH) and vault.is_dir(CRON_D_PATH):
        for entry in vault.list(prefix=CRON_D_PATH):
            entry = entry.strip('/')
            if entry == CRON_D_PATH or vault.is_dir(entry):
                continue
            try:
                content = vault.read(entry).decode('utf-8')
                jobs.extend(parse_crontab(content))
            except Exception:
                pass

    return jobs


async def crond_loop(users: list[str] | None, fsimage: str):
    """Background cron daemon loop.

    Every 60 seconds, reads /etc/crontab and /etc/cron.d/* for each user
    and executes matching jobs. Output is appended to /var/log/cron.log.

    If users is None, all users are re-discovered from the vault each tick.
    """
    from bin.ash import run_command

    log.info("loop_started", fsimage=fsimage, fixed_users=users)

    while True:
        # Sleep until the next minute boundary
        now = datetime.now()
        seconds_until_next_minute = 60 - now.second
        await asyncio.sleep(seconds_until_next_minute)

        now = datetime.now()
        active_users = users if users is not None else discover_users(fsimage)
        log.debug("tick", time=now.strftime("%H:%M"), users=active_users)

        for user in active_users:
            with SystemContext(user=user, fsimage=fsimage, interactive=False) as ctx:
                from fs.providers import BinProvider, DocsProvider

                SystemContext.current().mount("sbin", BinProvider())
                SystemContext.current().mount("models", ModelProvider())
                SystemContext.current().mount("docs", DocsProvider())

                vault = ctx.fs()
                jobs = collect_jobs(vault)

                matched = [j for j in jobs if job_matches(j, now)]
                if jobs:
                    log.debug("user_jobs", user=user, total=len(jobs), matched=len(matched))

                for job in matched:
                    log.info("job_start", user=user, command=job.command)
                    vault.write(CRON_LOG_PATH, f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Running job: {job.command}\n".encode('utf-8'), mode="a")
                    stdout_buf = io.StringIO()
                    stderr_buf = io.StringIO()
                    try:
                        with ctx.child(stdout=stdout_buf, stderr=stderr_buf):
                            await run_command(job.command)
                        log.info("job_ok", user=user, command=job.command)
                    except Exception as e:
                        stderr_buf.write(f"crond: error running '{job.command}': {e}\n")
                        log.error("job_error", user=user, command=job.command, error=str(e))

                    output = stdout_buf.getvalue() + stderr_buf.getvalue()
                    if output:
                        # Strip ANSI escapes and carriage returns for clean logs
                        output = _ANSI_RE.sub('', output)
                        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                        log_entry = f"[{timestamp}] {job.command}\n{output}\n"
                        vault.write(CRON_LOG_PATH, log_entry.encode('utf-8'), mode="a")


def start_crond(users: list[str], fsimage: str) -> asyncio.Task:
    """Start crond as a background asyncio task on the current event loop.

    Returns the task so the caller can cancel it if needed.
    """
    return asyncio.create_task(crond_loop(users, fsimage))


def discover_users(fsimage: str) -> list[str]:
    """Return all distinct users present in the vault database."""
    import sqlite3
    conn = sqlite3.connect(fsimage)
    users = [row[0] for row in conn.execute("SELECT DISTINCT user FROM versions")]
    conn.close()
    return users


if __name__ == "__main__":
    import logging
    import argparse

    parser = argparse.ArgumentParser(description="Cron daemon for AgentVault")
    parser.add_argument("--fsimage", required=True, help="Path to the vault .db file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if args.verbose else logging.INFO
        ),
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )

    users = discover_users(args.fsimage)
    if not users:
        log.error("no_users_found", fsimage=args.fsimage)
        raise SystemExit(1)

    log.info("starting", users=users, mode="auto-discover")
    asyncio.run(crond_loop(None, args.fsimage))
