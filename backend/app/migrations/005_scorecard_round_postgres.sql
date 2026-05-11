-- Persist scorecard per round (resume / pause); optional JSON array of { id, name, scores }.
ALTER TABLE rounds ADD COLUMN IF NOT EXISTS scorecard_json TEXT;
