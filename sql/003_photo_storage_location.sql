-- Photo bytes may live outside the database (local disk now, file share later).
-- photo_file keeps the metadata for every photo; `storage` says where the bytes
-- are and `path` is relative to the configured root so the root can move.

IF COL_LENGTH('Forge.RepairEval.photo_file', 'storage') IS NULL
    ALTER TABLE Forge.RepairEval.photo_file
        ADD storage VARCHAR(10) NOT NULL CONSTRAINT df_repaireval_photo_file_storage DEFAULT ('db'),  -- 'db' | 'fs'
            path    NVARCHAR(400) NULL;                                                              -- relative path when storage = 'fs'
GO

IF EXISTS (SELECT 1 FROM Forge.sys.columns c
           JOIN Forge.sys.objects o ON o.object_id = c.object_id
           JOIN Forge.sys.schemas s ON s.schema_id = o.schema_id
           WHERE s.name = 'RepairEval' AND o.name = 'photo_file' AND c.name = 'content' AND c.is_nullable = 0)
    ALTER TABLE Forge.RepairEval.photo_file ALTER COLUMN content VARBINARY(MAX) NULL;
GO
