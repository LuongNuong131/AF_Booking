"""Consistent, typed CSV snapshots; restore only into an empty, matching application schema."""

import base64
import csv
import hashlib
import io
import json
import os
import tempfile
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import MetaData, inspect, select
from sqlalchemy.sql import sqltypes

from app.models import Base

MAGIC = b"AFBK1\x00"
ALEMBIC_CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"
MAX_ARCHIVE_BYTES = 8 * 1024**3


class BackupError(ValueError):
    """Messages are fixed operational instructions, never database errors or values."""


def encryption_key(value):
    try:
        key = base64.b64decode(value, validate=True)
        if len(key) == 32:
            return key
    except (ValueError, TypeError):
        pass
    raise BackupError("BACKUP_ENCRYPTION_KEY must be a base64 encoded 32-byte key.")


def private_file(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


def encrypt_file(source, target, key):
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(MAGIC)
    with source.open("rb") as src, private_file(target) as dst:
        dst.write(MAGIC + nonce)
        while chunk := src.read(1024 * 1024):
            dst.write(cipher.update(chunk))
        dst.write(cipher.finalize())
        dst.write(cipher.tag)


def decrypt_file(source, target, key):
    size = source.stat().st_size
    if not len(MAGIC) + 12 + 16 <= size <= MAX_ARCHIVE_BYTES:
        raise BackupError("Invalid encrypted backup size.")
    with source.open("rb") as src:
        if src.read(len(MAGIC)) != MAGIC:
            raise BackupError("Unknown encrypted backup format.")
        nonce = src.read(12)
        src.seek(-16, 2)
        tag = src.read(16)
        src.seek(len(MAGIC) + 12)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        cipher.authenticate_additional_data(MAGIC)
        remaining = size - len(MAGIC) - 12 - 16
        with private_file(target) as dst:
            while remaining:
                chunk = src.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise BackupError("Encrypted backup was truncated.")
                remaining -= len(chunk)
                dst.write(cipher.update(chunk))
            dst.write(cipher.finalize())  # Authentication must finish before any DB write.


async def reflect(connection):
    names = set(await connection.run_sync(lambda c: inspect(c).get_table_names()))
    expected = set(Base.metadata.tables) | {"alembic_version"}
    if names != expected:
        raise BackupError("Migrate the application schema; unexpected or missing tables exist.")
    metadata = MetaData()
    await connection.run_sync(lambda c: metadata.reflect(c, only=sorted(expected)))
    return metadata


def describe(table, dialect):
    return [
        {
            "name": c.name,
            "type": f"VARCHAR({c.type.length})"
            if table.name == "alembic_version"
            else str(c.type.compile(dialect=dialect)),
            "generated": bool(c.computed),
        }
        for c in table.columns
    ]


def encode(value):
    if isinstance(value, (date, datetime, time)):
        value = value.isoformat()
    elif isinstance(value, Decimal):
        value = str(value)
    elif isinstance(value, bytes):
        value = base64.b64encode(value).decode("ascii")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode(raw, column):
    value = json.loads(raw)
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, sqltypes.DateTime):
        return datetime.fromisoformat(value)
    if isinstance(kind, sqltypes.Date):
        return date.fromisoformat(value)
    if isinstance(kind, sqltypes.Time):
        return time.fromisoformat(value)
    if isinstance(kind, sqltypes.Numeric) and not isinstance(kind, sqltypes.Float):
        return Decimal(value)
    if isinstance(kind, sqltypes.LargeBinary):
        return base64.b64decode(value, validate=True)
    return value


async def export_snapshot(engine, output, *, key=None, on_table=None):
    output = Path(output)
    if output.exists():
        raise BackupError("Output already exists; choose a new backup filename.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="booking-backup-", dir=output.parent) as directory:
        archive = Path(directory) / "snapshot.zip"
        manifest = {"format": 1, "tables": {}}
        with (
            private_file(archive) as target,
            zipfile.ZipFile(
                target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as zipped,
        ):
            async with engine.connect() as connection:
                await connection.execution_options(isolation_level="REPEATABLE READ")
                async with connection.begin():
                    metadata = await reflect(connection)
                    manifest["revision"] = (
                        await connection.execute(select(metadata.tables["alembic_version"]))
                    ).scalar_one()
                    for name, table in sorted(metadata.tables.items()):
                        digest, count = hashlib.sha256(), 0
                        with zipped.open(f"tables/{name}.csv", "w", force_zip64=True) as member:

                            def write(rows, digest=digest, member=member):
                                buffer = io.StringIO(newline="")
                                writer = csv.writer(buffer, lineterminator="\n")
                                writer.writerows(rows)
                                data = buffer.getvalue().encode("utf-8")
                                digest.update(data)
                                member.write(data)

                            write([[c.name for c in table.columns]])
                            result = await connection.stream(
                                select(table).order_by(*table.primary_key.columns)
                            )
                            try:
                                async for rows in result.partitions(500):
                                    write([[encode(v) for v in row] for row in rows])
                                    count += len(rows)
                            finally:
                                await result.close()
                        manifest["tables"][name] = {
                            "columns": describe(table, engine.dialect),
                            "rows": count,
                            "sha256": digest.hexdigest(),
                        }
                        if on_table is not None:
                            await on_table(name, count)
            zipped.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
        if key is not None:
            encrypted = Path(directory) / "snapshot.enc"
            encrypt_file(archive, encrypted, key)
            archive = encrypted
        # Hard-link publishes only a complete file, refuses overwrite, and preserves 0600.
        os.link(archive, output)
    return {
        "revision": manifest["revision"],
        "rows": {k: v["rows"] for k, v in manifest["tables"].items()},
    }


def validate_archive(archive):
    infos = archive.infolist()
    if (
        len(infos) != len({i.filename for i in infos})
        or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES
    ):
        raise BackupError("Duplicate entries or excessive uncompressed backup size.")
    info = archive.getinfo("manifest.json")
    if info.file_size > 1024 * 1024:
        raise BackupError("Invalid backup manifest size.")
    manifest = json.loads(archive.read(info))
    expected = set(Base.metadata.tables) | {"alembic_version"}
    if manifest.get("format") != 1 or set(manifest.get("tables", {})) != expected:
        raise BackupError("Unsupported or incomplete application backup.")
    if {i.filename for i in infos} != {"manifest.json"} | {f"tables/{n}.csv" for n in expected}:
        raise BackupError("Unexpected backup members.")
    for name, entry in manifest["tables"].items():
        digest = hashlib.sha256()
        with archive.open(f"tables/{name}.csv") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise BackupError("Backup checksum mismatch; no database data was restored.")
    return manifest


async def prepare_schema(engine):
    from alembic.config import Config

    from alembic import command

    config = Config(str(ALEMBIC_CONFIG))

    def migrate(connection):
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with engine.begin() as connection:
        names = await connection.run_sync(lambda c: inspect(c).get_table_names())
        if names:
            raise BackupError("Schema preparation requires a completely empty database.")
        await connection.run_sync(migrate)


async def restore_snapshot(engine, source, *, key=None, prepare=False, preserve_sessions=False):
    source = Path(source)
    with tempfile.TemporaryDirectory(prefix="booking-restore-") as directory:
        with source.open("rb") as stream:  # noqa: ASYNC230 - offline CLI, bounded local I/O
            encrypted = stream.read(len(MAGIC)) == MAGIC
        archive_path = source
        if encrypted:
            if key is None:
                raise BackupError("Provide BACKUP_ENCRYPTION_KEY to restore this backup.")
            archive_path = Path(directory) / "verified.zip"
            decrypt_file(source, archive_path, key)
        with zipfile.ZipFile(archive_path) as archive:
            manifest = validate_archive(archive)
            if prepare:
                await prepare_schema(engine)
            async with engine.begin() as connection:
                metadata = await reflect(connection)
                revision = (
                    await connection.execute(select(metadata.tables["alembic_version"]))
                ).scalar_one()
                if revision != manifest["revision"]:
                    raise BackupError("Source and target Alembic revisions must match.")
                for name, table in metadata.tables.items():
                    if describe(table, engine.dialect) != manifest["tables"][name]["columns"]:
                        raise BackupError("Source and target column definitions must match.")
                    if (
                        name != "alembic_version"
                        and (await connection.execute(select(table).limit(1))).first()
                    ):
                        raise BackupError("Restore target contains data; no rows were restored.")
                csv.field_size_limit(16 * 1024 * 1024)
                restored = {}
                for name, table in sorted(metadata.tables.items()):
                    if name == "alembic_version":
                        continue
                    with (
                        archive.open(f"tables/{name}.csv") as stream,
                        io.TextIOWrapper(stream, encoding="utf-8", newline="") as text,
                    ):
                        reader = csv.reader(text)
                        if next(reader) != [c.name for c in table.columns]:
                            raise BackupError("CSV columns do not match the manifest.")
                        batch, count = [], 0
                        for row in reader:
                            if len(row) != len(table.columns):
                                raise BackupError("Invalid CSV row width.")
                            batch.append(
                                {
                                    c.name: decode(raw, c)
                                    for c, raw in zip(table.columns, row, strict=True)
                                    if not c.computed
                                }
                            )
                            count += 1
                            if len(batch) == 500:
                                await connection.execute(table.insert(), batch)
                                batch.clear()
                        if batch:
                            await connection.execute(table.insert(), batch)
                        if count != manifest["tables"][name]["rows"]:
                            raise BackupError("Restored row count does not match the manifest.")
                        restored[name] = count
                if not preserve_sessions:
                    users = metadata.tables["users"]
                    await connection.execute(users.update().values(current_session_id=None))
    return {"revision": revision, "rows": restored, "sessions_revoked": not preserve_sessions}
