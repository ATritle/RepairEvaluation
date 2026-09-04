-- Photo library per repair number.
-- Photos arrive from the /mobile page (or the desktop uploader) tagged with a
-- repair number, before or after an evaluation exists. The library is
-- independent of revisions: attaching a library photo to an evaluation copies
-- its reference into revision_photo; removing it from the library does not
-- touch any revision.

IF OBJECT_ID('Forge.RepairEval.repair_photo', 'U') IS NULL
CREATE TABLE Forge.RepairEval.repair_photo (
    repair_photo_id INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_repaireval_repair_photo PRIMARY KEY,
    repair_no       VARCHAR(50)   NOT NULL,
    file_name       VARCHAR(64)   NOT NULL CONSTRAINT fk_repaireval_repair_photo_file
                                  REFERENCES Forge.RepairEval.photo_file (file_name),
    original_name   NVARCHAR(260) NULL,
    caption         NVARCHAR(500) NULL,
    source          VARCHAR(20)   NOT NULL CONSTRAINT df_repaireval_repair_photo_source DEFAULT ('web'),  -- 'mobile' | 'web'
    uploaded_at     DATETIME2(0)  NOT NULL CONSTRAINT df_repaireval_repair_photo_uploaded DEFAULT (SYSDATETIME()),
    uploaded_by     VARCHAR(100)  NULL,
    removed_at      DATETIME2(0)  NULL,       -- soft delete from the library
    CONSTRAINT uq_repaireval_repair_photo UNIQUE (repair_no, file_name)
);
GO

IF NOT EXISTS (SELECT 1 FROM Forge.sys.indexes WHERE name = 'ix_repaireval_repair_photo_repair')
    CREATE INDEX ix_repaireval_repair_photo_repair
        ON Forge.RepairEval.repair_photo (repair_no, uploaded_at DESC) INCLUDE (removed_at);
GO
