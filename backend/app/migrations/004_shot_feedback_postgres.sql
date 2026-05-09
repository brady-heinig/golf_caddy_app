-- Optional metadata for logged post-advice feedback (ties back to recommended club / advised distance).
ALTER TABLE shots ADD COLUMN IF NOT EXISTS recommended_club TEXT;
ALTER TABLE shots ADD COLUMN IF NOT EXISTS advised_plays_like_yd DOUBLE PRECISION;
ALTER TABLE shots ADD COLUMN IF NOT EXISTS feedback_transcript TEXT;
