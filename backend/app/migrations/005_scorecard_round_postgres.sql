-- Persist scorecard per round (resume / pause). JSON array of player rows: id, name, scores (18 holes each).
ALTER TABLE rounds ADD COLUMN IF NOT EXISTS scorecard_json TEXT;
