"""Explicit local setup commands; never prints passwords or encryption keys."""

import argparse
import asyncio
import getpass
import os
import secrets
import sys
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import PROJECT_ROOT, Settings
from app.core.security import hash_password
from app.models.identity import AuditLog, Membership, Role, User, Workspace


def init_env() -> None:
    destination = PROJECT_ROOT / ".env"
    content = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    values = {
        "__POSTGRES_PASSWORD__": secrets.token_urlsafe(24),
        "__SESSION_SECRET__": secrets.token_urlsafe(48),
        "__ENCRYPTION_KEY__": Fernet.generate_key().decode("ascii"),
    }
    for marker, value in values.items():
        content = content.replace(marker, value)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print("Created private .env; no secret values were printed. Back it up separately.")


async def create_user(args: argparse.Namespace, password: str) -> None:
    settings = Settings()
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    encoded = hash_password(password)
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            if await db.scalar(select(User).where(User.email == email)):
                raise ValueError("User already exists")
            if args.command == "bootstrap-admin":
                existing = await db.scalar(select(Workspace.id).limit(1))
                if existing is not None:
                    raise ValueError(
                        "Workspace already exists; use create-user with an explicit workspace ID"
                    )
                workspace = Workspace(name=args.workspace_name)
                db.add(workspace)
                await db.flush()
                role = Role.ADMIN
            else:
                found_workspace = await db.get(Workspace, UUID(args.workspace_id))
                if found_workspace is None:
                    raise ValueError("Workspace does not exist")
                workspace = found_workspace
                role = Role(args.role)
            user = User(email=email, password_hash=encoded)
            db.add(user)
            await db.flush()
            db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role))
            db.add(
                AuditLog(
                    workspace_id=workspace.id,
                    actor_id=user.id,
                    action="identity.user_created",
                    target_id=str(user.id),
                    request_id=str(uuid4()),
                    details={"role": role},
                )
            )
            await db.commit()
            print(f"Created {role} user; workspace_id={workspace.id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="tradeorbit")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-env", help="Create a new private .env without overwriting")
    for name in ("bootstrap-admin", "create-user"):
        command = commands.add_parser(name)
        command.add_argument("--email", required=True)
        command.add_argument("--password-stdin", action="store_true")
        if name == "bootstrap-admin":
            command.add_argument("--workspace-name", default="TradeOrbit")
        else:
            command.add_argument("--workspace-id", required=True)
            command.add_argument("--role", choices=[role.value for role in Role], required=True)
    args = parser.parse_args()
    if args.command == "init-env":
        try:
            init_env()
        except FileExistsError:
            parser.exit(1, ".env already exists; it was not overwritten.\n")
        return
    password = (
        sys.stdin.readline().rstrip("\r\n")
        if args.password_stdin
        else getpass.getpass("Password (12-128 characters): ")
    )
    if not args.password_stdin and password != getpass.getpass("Confirm password: "):
        parser.exit(1, "Passwords do not match.\n")
    try:
        asyncio.run(create_user(args, password))
    except ValueError as exc:
        parser.exit(1, f"Setup rejected: {exc}\n")


if __name__ == "__main__":
    main()
