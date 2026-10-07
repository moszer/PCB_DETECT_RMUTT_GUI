"""Create, verify or safely restore a station-data archive.

Run as: python -m app.backup_cli backup|verify|restore ...
"""
import argparse
from pathlib import Path

from .services.backup_service import create_backup, restore_backup, verify_backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup")
    verify = commands.add_parser("verify")
    verify.add_argument("archive", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("target", type=Path, help="New, nonexistent data directory")
    args = parser.parse_args()
    if args.command == "backup":
        print(create_backup())
    elif args.command == "verify":
        print(f"Verified {len(verify_backup(args.archive))} files")
    else:
        print(restore_backup(args.archive, args.target))


if __name__ == "__main__":
    main()
