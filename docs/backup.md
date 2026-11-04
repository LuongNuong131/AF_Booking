# Database backups and recovery

The backup tools read every application table and `alembic_version` in one
REPEATABLE READ transaction. They write a ZIP containing typed CSV files and a
manifest with column definitions, row counts, schema revision and SHA-256 checksums.
JSON-encoded cells distinguish NULL, strings, JSON, dates, decimals and bytes.
Generated columns are archived for comparison and recomputed by the destination.
This is a data snapshot; keep the matching Git revision and migration files too.

## Export

Use Python 3.12 and the hash-locked backend runtime requirements. From the checkout
root, provide `DATABASE_URL` through a protected process environment or secret
manager, using `mysql+aiomysql://...`. TLS certificate and hostname verification
remain enabled. `DATABASE_SSL_CA` optionally selects a public CA bundle.

```sh
backend/.venv/bin/python scripts/export_backup.py --encrypt --output /tmp/booking-backup/snapshot.enc
```

Encrypted backups require `BACKUP_ENCRYPTION_KEY`: base64 encoding of exactly 32
random bytes. Generate it in a secure password manager or protected terminal;
keep it separately from the artifact and never commit or print it in CI logs.
AES-256-GCM authenticates the archive. Keep historical keys if rotating this key.
Without `--encrypt`, the output is an unencrypted typed ZIP suitable for isolated
local recovery tests. Temporary and final files have mode 0600; incomplete files
are removed, and an existing destination is never overwritten. Default timeout:
600 seconds (`--timeout` can change it). Commands print only aggregate counts.

## Scheduled GitHub Actions

`.github/workflows/backup.yml` runs daily at 19:30 UTC (02:30 ICT), or manually.
It remains disabled until repository variable `BACKUP_ENABLED=true` is configured.
Add repository secrets `DATABASE_URL` and `BACKUP_ENCRYPTION_KEY` securely in GitHub.
The runner must be permitted to connect to TiDB Cloud and verify its certificate.
The workflow uploads only the encrypted file, retaining artifacts for 14 days.
Download copies to durable offsite storage according to your recovery policy;
GitHub artifacts and a free database plan are not long-term backup retention.
No production secrets or live cron job were configured by this implementation.

## Restore into an empty database

1. Retrieve the artifact and its encryption key. Check out the source application's
   Git revision, install its locked runtime requirements, and stop application
   writers. Create an empty destination database with the required UTF-8 settings.
2. Set `DATABASE_URL` to that destination through the protected environment. Do not
   reuse the source URL. Set the matching `BACKUP_ENCRYPTION_KEY` for an encrypted file.
3. Run the following from the checkout root:

```sh
backend/.venv/bin/python scripts/restore_backup.py --input /tmp/snapshot.enc --prepare-schema
```

`--prepare-schema` runs the checked-out Alembic migrations only when the database
has no tables. Alternatively migrate the empty target beforehand and omit the flag.
The tool rejects populated targets, unknown/missing tables, revision or column
mismatches, invalid archive members, counts/checksums and authentication failures.
Archive authentication, checksums and schema checks precede insertion. CSV row
validation and inserts use one transaction, rolling back together on failure. There is no
truncate/force option. MySQL/TiDB metadata-table collation differences are tolerated
only for `alembic_version`; application column definitions are checked.

Restored account sessions are revoked by default. Restart the API, verify `/health`
and `/health/db`, sign in again, inspect representative folders/history/invoices,
and compare backup counts. Keep the source intact until recovery is accepted.

## Recovery verification

`--suite backup` runs against disposable verified-TLS MySQL and TiDB. Tests compare
all application tables after encrypted round-trip, including generated guards and
JSON/Unicode/CSV special characters; prove concurrent writes do not tear the
snapshot; reject a wrong encryption key before creating tables; reject populated
targets/output collisions; and invoke both actual CLIs against an empty database.
The exact-data test explicitly preserves sessions internally for comparison; the
normal restore CLI always revokes them. See [testing.md](testing.md) for results.
