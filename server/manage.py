"""本地账号管理 CLI。

用法（在 OBot-EP 根目录）：

    uv run python -m server.manage list                 # 列出账号
    uv run python -m server.manage passwd               # 重置某个账号的密码（交互输入）
    uv run python -m server.manage passwd --user admin --password 新的密码
    uv run python -m server.manage create --user alice --password secret123 --role admin
    uv run python -m server.manage role --user alice --role admin
    uv run python -m server.manage disable --user alice

输出一律用英文 ASCII，避免在没装 CJK 字体的终端里乱码。
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import config
from .repository import ROLE_ADMIN, ROLE_USER, Repository
from .security import generate_password


def _repo() -> Repository:
    config.ensure_dirs()
    return Repository()


def cmd_list(_args: argparse.Namespace) -> int:
    repo = _repo()
    try:
        users = repo.list_users()
        if not users:
            print("No accounts yet. Run the server once to create the first admin,")
            print("or: python -m server.manage create --user admin --password ... --role admin")
            return 1

        print(f"{'ID':>4}  {'USERNAME':<20} {'ROLE':<6} {'ACTIVE':<7} {'LAST LOGIN'}")
        for user in users:
            last = "never" if not user.last_login_at else f"{user.last_login_at:.0f}"
            print(
                f"{user.id:>4}  {user.username:<20} {user.role:<6} "
                f"{'yes' if user.is_active else 'no':<7} {last}"
            )
        print(f"\ndatabase: {config.DB_PATH}")
    finally:
        repo.close()
    return 0


def cmd_passwd(args: argparse.Namespace) -> int:
    repo = _repo()
    try:
        username = args.user
        user = repo.find_user(username)
        if user is None:
            print(f"[x] No such account: {username}")
            return 1

        password = args.password
        if not password:
            password = getpass.getpass("New password (min 8 chars): ")
            confirm = getpass.getpass("Repeat: ")
            if password != confirm:
                print("[x] Passwords do not match")
                return 1

        try:
            repo.change_password(user.id, password)
        except ValueError as error:
            print(f"[x] {error}")
            return 1

        print(f"[ok] Password updated for '{username}'.")
        repo.add_log(
            actor_id=None,
            username=username,
            action="cli_password_reset",
            detail="password reset from the command line",
            is_admin=True,
        )
    finally:
        repo.close()
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    repo = _repo()
    try:
        password = args.password or generate_password()
        role = ROLE_ADMIN if args.role == "admin" else ROLE_USER
        try:
            user = repo.create_user(
                args.user, password, display_name=args.display_name or "", role=role
            )
        except ValueError as error:
            print(f"[x] {error}")
            return 1

        print(f"[ok] Created '{user.username}' with role '{user.role}'.")
        if not args.password:
            print(f"     generated password: {password}")
    finally:
        repo.close()
    return 0


def cmd_role(args: argparse.Namespace) -> int:
    repo = _repo()
    try:
        user = repo.find_user(args.user)
        if user is None:
            print(f"[x] No such account: {args.user}")
            return 1
        repo.set_user_role(user.id, ROLE_ADMIN if args.role == "admin" else ROLE_USER)
        print(f"[ok] '{user.username}' is now '{args.role}'.")
    finally:
        repo.close()
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    repo = _repo()
    try:
        user = repo.find_user(args.user)
        if user is None:
            print(f"[x] No such account: {args.user}")
            return 1
        repo.set_user_active(user.id, args.enable)
        print(f"[ok] '{user.username}' is now {'enabled' if args.enable else 'disabled'}.")
    finally:
        repo.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="server.manage", description="OBot-EP account CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list accounts").set_defaults(func=cmd_list)

    p = sub.add_parser("passwd", help="reset an account password")
    p.add_argument("--user", default=config.DEFAULT_ADMIN_USERNAME)
    p.add_argument("--password", default="", help="omit to be prompted")
    p.set_defaults(func=cmd_passwd)

    p = sub.add_parser("create", help="create an account")
    p.add_argument("--user", required=True)
    p.add_argument("--password", default="", help="omit to auto-generate")
    p.add_argument("--display-name", default="")
    p.add_argument("--role", choices=("user", "admin"), default="user")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("role", help="change an account role")
    p.add_argument("--user", required=True)
    p.add_argument("--role", choices=("user", "admin"), required=True)
    p.set_defaults(func=cmd_role)

    p = sub.add_parser("enable", help="enable an account")
    p.add_argument("--user", required=True)
    p.set_defaults(func=cmd_enable, enable=True)

    p = sub.add_parser("disable", help="disable an account")
    p.add_argument("--user", required=True)
    p.set_defaults(func=cmd_enable, enable=False)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
