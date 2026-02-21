"""Tests for crontab command and cron daemon."""

import io
from datetime import datetime
from unittest.mock import patch

from system.context import SystemContext
from system.crond import CronJob, parse_crontab, matches_field, job_matches, collect_jobs
from bin import crontab


# --- parse_crontab tests ---

def test_parse_crontab_basic():
    content = "*/5 * * * * ls /tmp\n0 2 * * 1-5 echo hello\n"
    jobs = parse_crontab(content)
    assert len(jobs) == 2
    assert jobs[0] == CronJob("*/5", "*", "*", "*", "*", "ls /tmp")
    assert jobs[1] == CronJob("0", "2", "*", "*", "1-5", "echo hello")


def test_parse_crontab_skips_comments_and_blanks():
    content = "# this is a comment\n\n  \n*/10 * * * * ls\n# another comment\n"
    jobs = parse_crontab(content)
    assert len(jobs) == 1
    assert jobs[0].command == "ls"


def test_parse_crontab_malformed_lines():
    content = "only three fields here\n* * * * * valid command\n"
    jobs = parse_crontab(content)
    assert len(jobs) == 1
    assert jobs[0].command == "valid command"


def test_parse_crontab_empty():
    assert parse_crontab("") == []
    assert parse_crontab("# only comments\n") == []


# --- matches_field tests ---

def test_matches_field_star():
    assert matches_field("*", 0)
    assert matches_field("*", 59)


def test_matches_field_exact():
    assert matches_field("5", 5)
    assert not matches_field("5", 6)


def test_matches_field_step():
    assert matches_field("*/5", 0)
    assert matches_field("*/5", 15)
    assert not matches_field("*/5", 3)


def test_matches_field_range():
    assert matches_field("1-5", 1)
    assert matches_field("1-5", 3)
    assert matches_field("1-5", 5)
    assert not matches_field("1-5", 0)
    assert not matches_field("1-5", 6)


def test_matches_field_list():
    assert matches_field("1,15,30", 1)
    assert matches_field("1,15,30", 15)
    assert matches_field("1,15,30", 30)
    assert not matches_field("1,15,30", 2)


def test_matches_field_combined_list_and_range():
    assert matches_field("1-3,7,10-12", 2)
    assert matches_field("1-3,7,10-12", 7)
    assert matches_field("1-3,7,10-12", 11)
    assert not matches_field("1-3,7,10-12", 5)


# --- job_matches tests ---

def test_job_matches_every_minute():
    job = CronJob("*", "*", "*", "*", "*", "echo hi")
    dt = datetime(2025, 6, 15, 10, 30)
    assert job_matches(job, dt)


def test_job_matches_specific_time():
    job = CronJob("30", "10", "*", "*", "*", "echo hi")
    assert job_matches(job, datetime(2025, 6, 15, 10, 30))
    assert not job_matches(job, datetime(2025, 6, 15, 10, 31))
    assert not job_matches(job, datetime(2025, 6, 15, 11, 30))


def test_job_matches_weekday():
    # 2025-06-16 is a Monday (isoweekday=1, %7=1)
    job = CronJob("0", "0", "*", "*", "1", "echo monday")
    assert job_matches(job, datetime(2025, 6, 16, 0, 0))
    # 2025-06-17 is Tuesday
    assert not job_matches(job, datetime(2025, 6, 17, 0, 0))


def test_job_matches_sunday():
    # Sunday: isoweekday=7, %7=0
    job = CronJob("0", "0", "*", "*", "0", "echo sunday")
    assert job_matches(job, datetime(2025, 6, 15, 0, 0))  # Sunday


def test_job_matches_day_of_month():
    job = CronJob("0", "0", "1", "*", "*", "echo first")
    assert job_matches(job, datetime(2025, 6, 1, 0, 0))
    assert not job_matches(job, datetime(2025, 6, 2, 0, 0))


# --- crontab command tests ---

async def test_crontab_list(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("etc/crontab", b"*/5 * * * * ls /tmp\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await crontab.run("-l")
        assert "*/5 * * * * ls /tmp" in output.getvalue()


async def test_crontab_list_no_crontab(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await crontab.run("-l")
        assert "no crontab" in output.getvalue()


async def test_crontab_remove(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("etc/crontab", b"0 * * * * echo hi\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await crontab.run("-r")
        assert "removed" in output.getvalue()
        assert not vault.exists("etc/crontab")


async def test_crontab_remove_no_crontab(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await crontab.run("-r")
        assert "no crontab" in output.getvalue()


async def test_crontab_no_args(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await crontab.run()
        assert "Usage" in output.getvalue()


# --- collect_jobs tests ---

def test_collect_jobs_crontab_only(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("etc/crontab", b"0 * * * * echo main\n")
        jobs = collect_jobs(vault)
        assert len(jobs) == 1
        assert jobs[0].command == "echo main"


def test_collect_jobs_cron_d_only(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("etc/cron.d/cleanup", b"0 3 * * * rm /tmp/old\n")
        vault.write("etc/cron.d/backup", b"0 4 * * * echo backup\n")
        jobs = collect_jobs(vault)
        assert len(jobs) == 2
        commands = {j.command for j in jobs}
        assert "rm /tmp/old" in commands
        assert "echo backup" in commands


def test_collect_jobs_combined(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("etc/crontab", b"*/5 * * * * echo main\n")
        vault.write("etc/cron.d/extra", b"0 0 * * * echo extra\n")
        jobs = collect_jobs(vault)
        assert len(jobs) == 2
        commands = {j.command for j in jobs}
        assert "echo main" in commands
        assert "echo extra" in commands


def test_collect_jobs_empty(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        jobs = collect_jobs(vault)
        assert jobs == []


def test_collect_jobs_cron_d_with_comments(temp_db):
    with SystemContext(user="cron_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("etc/cron.d/mixed", b"# a comment\n\n*/10 * * * * echo ten\n")
        jobs = collect_jobs(vault)
        assert len(jobs) == 1
        assert jobs[0].command == "echo ten"


# --- crond execution test ---

async def test_crond_executes_matching_job(temp_db):
    """Test that crond runs a matching job and logs output."""
    from system.crond import crond_loop
    from fs.providers import BinProvider
    import asyncio

    with SystemContext(user="cron_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()

        # Set up a crontab with a job that matches every minute
        vault.write("etc/crontab", b"* * * * * echo cron-test-output\n")

        # Patch asyncio.sleep to avoid waiting, and datetime.now to return a known time
        call_count = 0

        async def fake_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError()

        fake_now = datetime(2025, 6, 15, 10, 30, 0)

        with patch("system.crond.asyncio.sleep", side_effect=fake_sleep):
            with patch("system.crond.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                try:
                    await crond_loop(["cron_user"], temp_db)
                except asyncio.CancelledError:
                    pass

        # Check that cron log was written
        vault = ctx.fs()
        assert vault.exists("var/log/cron.log")
        log_content = vault.read("var/log/cron.log").decode('utf-8')
        assert "cron-test-output" in log_content
        assert "echo cron-test-output" in log_content
