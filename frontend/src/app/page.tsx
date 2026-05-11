export default function HomePage() {
  return (
    <main className="landingPhone" role="main">
      <div className="landingCard">
        <div className="landingTitle">
          <span className="landingTitleBrand">ForeAI</span>
          {": An AI Golf Caddie"}
        </div>

        <div className="landingBtns" role="navigation" aria-label="Primary">
          <a className="landingBtn landingBtnPrimary" href="/caddie">
            Play
          </a>
          <a className="landingBtn" href="/settings">
            Settings
          </a>
          <a className="landingBtn" href="/rounds">
            Past Rounds
          </a>
        </div>
      </div>
    </main>
  );
}

