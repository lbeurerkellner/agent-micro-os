_USAGE = """\
crontab - Manage scheduled jobs

Usage: crontab [-l | -e | -r]

Options:
  -l    List the current crontab
  -e    Edit the crontab (opens interactive editor)
  -r    Remove the crontab

Crontab format (one job per line):
  # m h dom mon dow command
  */5 * * * *  ls /tmp
  0 2 * * 1-5  cat /var/log/syslog
"""

CRONTAB_PATH = "etc/crontab"

DEFAULT_CRONTAB = """\
# AgentVault crontab
# Format: minute hour day-of-month month day-of-week command
# Examples:
#   */5 * * * *  ls /tmp        # every 5 minutes
#   0 2 * * 1-5  echo hello     # 2am weekdays
#   0 0 1 * *    du /           # midnight on 1st of month
"""


async def run(*args):
    """Manage scheduled cron jobs."""
    from system.context import SystemContext, cprint
    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found.")
        return

    if len(args) != 1 or args[0] not in ('-l', '-e', '-r'):
        cprint(_USAGE)
        return

    flag = args[0]
    vault = ctx.fs()

    if flag == '-l':
        from system.crond import collect_jobs
        jobs = collect_jobs(vault)
        if not jobs:
            cprint("no crontab for current user")
            return
        for job in jobs:
            cprint(f"{job.minute} {job.hour} {job.dom} {job.month} {job.dow} {job.command}")

    elif flag == '-e':
        from bin.edit import edit_with_prompt_toolkit
        initial = ""
        if vault.exists(CRONTAB_PATH):
            initial = vault.read(CRONTAB_PATH).decode('utf-8')
        else:
            initial = DEFAULT_CRONTAB

        edited = await edit_with_prompt_toolkit(initial)
        vault.write(CRONTAB_PATH, edited.encode('utf-8'))
        cprint("crontab: installing new crontab")

    elif flag == '-r':
        if not vault.exists(CRONTAB_PATH):
            cprint("no crontab for current user")
            return
        vault.delete(CRONTAB_PATH)
        cprint("crontab: removed")
