-- IFP Repair Evaluation - Forge storage
-- Run from master in SSMS (all objects fully qualified) or let the app's
-- setup step run it with a db_owner login.
--
-- Model: one evaluation per repair number; every Save writes a new revision.
-- Nothing is updated in place, so old versions stay visible.

IF NOT EXISTS (SELECT 1 FROM Forge.sys.schemas WHERE name = 'RepairEval')
    EXEC Forge.sys.sp_executesql N'CREATE SCHEMA RepairEval AUTHORIZATION dbo';
GO

IF OBJECT_ID('Forge.RepairEval.evaluation', 'U') IS NULL
CREATE TABLE Forge.RepairEval.evaluation (
    evaluation_id       INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_repaireval_evaluation PRIMARY KEY,
    repair_no           VARCHAR(50)  NOT NULL,
    current_revision_no INT          NOT NULL CONSTRAINT df_repaireval_evaluation_rev DEFAULT (0),
    created_at          DATETIME2(0) NOT NULL CONSTRAINT df_repaireval_evaluation_created DEFAULT (SYSDATETIME()),
    updated_at          DATETIME2(0) NOT NULL CONSTRAINT df_repaireval_evaluation_updated DEFAULT (SYSDATETIME()),
    CONSTRAINT uq_repaireval_evaluation_repair_no UNIQUE (repair_no)
);
GO

IF OBJECT_ID('Forge.RepairEval.revision', 'U') IS NULL
CREATE TABLE Forge.RepairEval.revision (
    revision_id         INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_repaireval_revision PRIMARY KEY,
    evaluation_id       INT           NOT NULL CONSTRAINT fk_repaireval_revision_evaluation
                                      REFERENCES Forge.RepairEval.evaluation (evaluation_id) ON DELETE CASCADE,
    revision_no         INT           NOT NULL,
    saved_at            DATETIME2(0)  NOT NULL CONSTRAINT df_repaireval_revision_saved DEFAULT (SYSDATETIME()),
    saved_by            VARCHAR(100)  NULL,      -- client host/IP today; login name once the app has auth
    eval_date           DATE          NULL,
    technician          VARCHAR(100)  NULL,
    customer            NVARCHAR(255) NULL,      -- as shown on the report ("# - name" when picked from P21)
    customer_id         VARCHAR(20)   NULL,      -- Prophet21.dbo.customer.customer_id
    customer_contact    NVARCHAR(255) NULL,
    contact_id          VARCHAR(20)   NULL,      -- Prophet21.dbo.contacts.id
    customer_email      NVARCHAR(255) NULL,
    email_override      BIT           NOT NULL CONSTRAINT df_repaireval_revision_override DEFAULT (0),
    model               NVARCHAR(255) NULL,
    serial              NVARCHAR(255) NULL,
    customer_po         NVARCHAR(100) NULL,
    material            NVARCHAR(255) NULL,      -- Customer Part Number
    customer_request    NVARCHAR(MAX) NULL,
    received_condition  NVARCHAR(MAX) NULL,
    findings            NVARCHAR(MAX) NULL,
    CONSTRAINT uq_repaireval_revision UNIQUE (evaluation_id, revision_no)
);
GO

IF OBJECT_ID('Forge.RepairEval.photo_file', 'U') IS NULL
CREATE TABLE Forge.RepairEval.photo_file (
    file_name       VARCHAR(64)    NOT NULL CONSTRAINT pk_repaireval_photo_file PRIMARY KEY,  -- <uuid>.jpg
    original_name   NVARCHAR(260)  NULL,
    content_type    VARCHAR(50)    NOT NULL CONSTRAINT df_repaireval_photo_file_ct DEFAULT ('image/jpeg'),
    width_px        INT            NULL,
    height_px       INT            NULL,
    byte_size       INT            NOT NULL,
    sha256          CHAR(64)       NULL,
    content         VARBINARY(MAX) NOT NULL,
    uploaded_at     DATETIME2(0)   NOT NULL CONSTRAINT df_repaireval_photo_file_uploaded DEFAULT (SYSDATETIME()),
    uploaded_by     VARCHAR(100)   NULL
);
GO

IF OBJECT_ID('Forge.RepairEval.revision_photo', 'U') IS NULL
CREATE TABLE Forge.RepairEval.revision_photo (
    revision_photo_id INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_repaireval_revision_photo PRIMARY KEY,
    revision_id       INT           NOT NULL CONSTRAINT fk_repaireval_revision_photo_revision
                                    REFERENCES Forge.RepairEval.revision (revision_id) ON DELETE CASCADE,
    seq               INT           NOT NULL,   -- 1 = "PHOTO 1" on the report
    file_name         VARCHAR(64)   NOT NULL CONSTRAINT fk_repaireval_revision_photo_file
                                    REFERENCES Forge.RepairEval.photo_file (file_name),
    display_name      NVARCHAR(260) NULL,       -- original upload name shown in the UI
    description       NVARCHAR(MAX) NULL,
    rotation          SMALLINT      NOT NULL CONSTRAINT df_repaireval_revision_photo_rot DEFAULT (0),  -- 0/90/180/270 clockwise
    CONSTRAINT uq_repaireval_revision_photo UNIQUE (revision_id, seq)
);
GO

IF OBJECT_ID('Forge.RepairEval.photo_annotation', 'U') IS NULL
CREATE TABLE Forge.RepairEval.photo_annotation (
    annotation_id     INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_repaireval_photo_annotation PRIMARY KEY,
    revision_photo_id INT          NOT NULL CONSTRAINT fk_repaireval_photo_annotation_photo
                                   REFERENCES Forge.RepairEval.revision_photo (revision_photo_id) ON DELETE CASCADE,
    seq               INT          NOT NULL,
    symbol            VARCHAR(20)  NOT NULL,   -- arrow_up/arrow_right/arrow_down/arrow_left/circle/square/rectangle/x/check
    x                 FLOAT        NOT NULL,   -- 0..1 fraction of displayed (rotated) image width
    y                 FLOAT        NOT NULL,   -- 0..1 fraction of displayed (rotated) image height
    size_pct          INT          NOT NULL CONSTRAINT df_repaireval_photo_annotation_size DEFAULT (100),  -- 25..300
    CONSTRAINT uq_repaireval_photo_annotation UNIQUE (revision_photo_id, seq)
);
GO

IF NOT EXISTS (SELECT 1 FROM Forge.sys.indexes WHERE name = 'ix_repaireval_revision_eval')
    CREATE INDEX ix_repaireval_revision_eval ON Forge.RepairEval.revision (evaluation_id, revision_no DESC);
IF NOT EXISTS (SELECT 1 FROM Forge.sys.indexes WHERE name = 'ix_repaireval_evaluation_updated')
    CREATE INDEX ix_repaireval_evaluation_updated ON Forge.RepairEval.evaluation (updated_at DESC);
GO
