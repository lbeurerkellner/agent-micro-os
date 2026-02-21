"""Vault SQLite database utilities (vacuum, analyze)."""

import argparse
import sqlite3


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def cmd_vacuum(args):
    """Vacuum the database to reclaim unused space."""
    from pathlib import Path
    from fs.vault import Vault

    vault = Vault(args.fsimage, "system")
    reclaimed = vault.vacuum()

    if reclaimed > 0:
        print(f"Vacuumed {args.fsimage}: reclaimed {_format_size(reclaimed)}")  # no-ctx-print
    else:
        print(f"Vacuumed {args.fsimage}: no space reclaimed")  # no-ctx-print

    db_path = Path(args.fsimage)
    print(f"Database size: {_format_size(db_path.stat().st_size)}")  # no-ctx-print


def cmd_analyze(args):
    """Show space usage breakdown per user and top-level directory."""
    conn = sqlite3.connect(args.fsimage)
    cursor = conn.cursor()

    # Per-user summary
    cursor.execute("""
        SELECT user, COUNT(*), SUM(LENGTH(content))
        FROM versions
        GROUP BY user
        ORDER BY SUM(LENGTH(content)) DESC
    """)
    users = cursor.fetchall()

    print(f"=== Space usage: {args.fsimage} ===\n")  # no-ctx-print
    print(f"{'User':<20} {'Versions':>10} {'Total Size':>12}")  # no-ctx-print
    print("-" * 44)  # no-ctx-print
    grand_total = 0
    for user, count, total in users:
        total = total or 0
        grand_total += total
        print(f"{user:<20} {count:>10,} {_format_size(total):>12}")  # no-ctx-print
    print("-" * 44)  # no-ctx-print
    print(f"{'TOTAL':<20} {'':>10} {_format_size(grand_total):>12}")  # no-ctx-print

    # Per-user top-level directory breakdown
    for user, _, _ in users:
        print(f"\n--- {user} ---\n")  # no-ctx-print

        # Get top-level directory sizes (all versions)
        cursor.execute("""
            SELECT
                CASE
                    WHEN INSTR(filepath, '/') > 0
                        THEN SUBSTR(filepath, 1, INSTR(filepath, '/') - 1)
                    ELSE filepath
                END AS top_dir,
                COUNT(*) AS versions,
                SUM(LENGTH(content)) AS total_size,
                COUNT(DISTINCT filepath) AS files
            FROM versions
            WHERE user = ?
            GROUP BY top_dir
            ORDER BY total_size DESC
        """, (user,))
        dirs = cursor.fetchall()

        print(f"  {'Directory':<24} {'Files':>6} {'Versions':>10} {'Total Size':>12}")  # no-ctx-print
        print(f"  {'-' * 54}")  # no-ctx-print
        for top_dir, versions, total_size, files in dirs:
            total_size = total_size or 0
            print(f"  {top_dir:<24} {files:>6,} {versions:>10,} {_format_size(total_size):>12}")  # no-ctx-print

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Vault database utilities")
    parser.add_argument("--fsimage", required=True, help="Path to the vault .db file")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("vacuum", help="Reclaim unused space")
    sub.add_parser("analyze", help="Show space usage breakdown")

    args = parser.parse_args()

    if args.command == "vacuum":
        cmd_vacuum(args)
    elif args.command == "analyze":
        cmd_analyze(args)


if __name__ == "__main__":
    main()
