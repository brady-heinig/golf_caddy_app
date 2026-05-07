export default function HomePage() {
  return (
    <main className="container">
      <div className="card">
        <div className="cardBody grid">
          <h1 className="title">AI Golf Caddie</h1>
          <p className="muted" style={{ margin: 0 }}>
            Start a round and get quick, structured club + aim suggestions using your handicap, bag, wind,
            and hazards.
          </p>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
            <a className="card" href="/settings">
              <div className="cardBody">
                <div style={{ fontWeight: 650, marginBottom: 6 }}>Settings</div>
                <div className="muted" style={{ fontSize: 13 }}>
                  Handicap + club carry distances
                </div>
              </div>
            </a>
            <a className="card" href="/rounds">
              <div className="cardBody">
                <div style={{ fontWeight: 650, marginBottom: 6 }}>Rounds</div>
                <div className="muted" style={{ fontSize: 13 }}>
                  Start/resume, hole map, and chat
                </div>
              </div>
            </a>
          </div>
        </div>
      </div>
    </main>
  );
}

