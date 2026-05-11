-- Last play mode live or sim for resuming without the mode picker
ALTER TABLE rounds ADD COLUMN IF NOT EXISTS round_mode TEXT;
