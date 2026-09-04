-- received_condition was never shown in the app or the PDF; drop it.
IF COL_LENGTH('Forge.RepairEval.revision', 'received_condition') IS NOT NULL
    ALTER TABLE Forge.RepairEval.revision DROP COLUMN received_condition;
GO
