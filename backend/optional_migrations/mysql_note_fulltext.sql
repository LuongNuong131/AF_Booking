-- Optional, MySQL-only operation. NOT part of Alembic head; never run on TiDB.
-- Verify SELECT VERSION(), ngram parser support and your provider's DDL policy first.
-- Schedule index build separately from normal app deployment on a large note table.
CREATE FULLTEXT INDEX ft_booking_notes_note ON booking_notes (note) WITH PARSER ngram;
-- Rollback: DROP INDEX ft_booking_notes_note ON booking_notes;
