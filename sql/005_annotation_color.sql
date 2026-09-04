-- Markup colour per annotation (hex, e.g. #ff0000). Existing rows stay red.
IF COL_LENGTH('Forge.RepairEval.photo_annotation', 'color') IS NULL
    ALTER TABLE Forge.RepairEval.photo_annotation
        ADD color CHAR(7) NOT NULL CONSTRAINT df_repaireval_photo_annotation_color DEFAULT ('#ff0000');
GO
