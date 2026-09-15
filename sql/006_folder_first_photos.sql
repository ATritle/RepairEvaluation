-- Folder-first photos + soft delete + stale-save support.
--
-- The live photo library is the repair's Photos folder on the N drive; the
-- database no longer tracks library membership or photo bytes. A saved
-- revision references an immutable, content-hashed snapshot copied into
--   <Dwgs>\R36000\R36169\Photos\.archive\<sha256>.jpg
-- at save time. Old columns are kept nullable until the migration script has
-- moved every row, then 007 drops the legacy tables.

-- revision_photo: archive reference instead of photo_file FK
IF EXISTS (SELECT 1 FROM Forge.sys.foreign_keys WHERE name = 'fk_repaireval_revision_photo_file')
    ALTER TABLE Forge.RepairEval.revision_photo DROP CONSTRAINT fk_repaireval_revision_photo_file;
GO
IF COL_LENGTH('Forge.RepairEval.revision_photo', 'sha256') IS NULL
    ALTER TABLE Forge.RepairEval.revision_photo
        ADD sha256        CHAR(64)      NULL,   -- content hash of the normalised snapshot
            source_name   NVARCHAR(260) NULL,   -- file name in the live Photos folder at save time
            archive_path  NVARCHAR(400) NULL;   -- relative to the Dwgs root, e.g. R36000/R36169/Photos/.archive/<sha>.jpg
GO
IF EXISTS (SELECT 1 FROM Forge.sys.columns c JOIN Forge.sys.objects o ON o.object_id = c.object_id JOIN Forge.sys.schemas s ON s.schema_id = o.schema_id
           WHERE s.name = 'RepairEval' AND o.name = 'revision_photo' AND c.name = 'file_name' AND c.is_nullable = 0)
    ALTER TABLE Forge.RepairEval.revision_photo ALTER COLUMN file_name VARCHAR(64) NULL;
GO

-- evaluation: soft delete
IF COL_LENGTH('Forge.RepairEval.evaluation', 'deleted_at') IS NULL
    ALTER TABLE Forge.RepairEval.evaluation
        ADD deleted_at DATETIME2(0) NULL,
            deleted_by VARCHAR(100) NULL;
GO
