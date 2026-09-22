import { Link } from "react-router-dom";

const SECTIONS: { title: string; body: string }[] = [
  {
    title: "The score is a fold over a log",
    body: "Every match is an append-only log of events. The score, the cards, the stats - all of it is recomputed from the log, never edited in place. A VAR overturn is a new record that supersedes an old one, so the goal stays visible, struck through, with the reason and the minute the decision came. That is why Onside can answer 'what was the score at 63 minutes?' after the fact.",
  },
  {
    title: "Win probability you can check",
    body: "A LightGBM model trained on 288,288 match-minutes from 3,168 matches, then tested on the 793 matches that came after them. Its multiclass Brier score is 0.404, against 0.469 for 'whoever is ahead wins'. Predicted and observed frequencies match across the range - when it says 25%, it happens about 24% of the time. The build fails if that ever gets worse.",
  },
  {
    title: "Reports written by rules",
    body: "Each report ranks the match's moments by how far they moved the win probability, then turns them into sentences from a phrase bank. No language model: every sentence is reproducible, it costs nothing, it cannot invent a goal, and it rewrites itself the moment a correction lands.",
  },
  {
    title: "Replays, not live matches",
    body: "Every match in the archive has already been played, and its page says so: full time, the date it was played, the real result. A replay re-runs one of those matches minute by minute - only when someone starts it - through the exact pipeline a live feed would use, so the correction handling can be watched working. A replay is always marked in violet, its page shows the real result alongside, and it never changes the archived match. Live fixtures from today need a licensed feed; the football-data.org and API-Football adapters are built and tested, and switch on with an API key.",
  },
  {
    title: "Honest about the data",
    body: "Everything here is StatsBomb's open data: 3,961 matches across 24 competitions, not every game in the world - global live coverage needs a paid feed, and Onside's adapter layer is built for one. StatsBomb records no VAR decisions, so the corrections in replays are synthesised and labelled that way. Where the archive holds only part of a league season, no table is shown rather than a wrong one.",
  },
];

export default function About() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <h1 className="font-display text-5xl uppercase">How Onside works</h1>
        <p className="mt-2 text-mute">Onside: level with the last defender - and the call that stands after the review.</p>
      </div>
      {SECTIONS.map((s) => (
        <section key={s.title} className="space-y-2">
          <h2 className="text-xl font-extrabold">{s.title}</h2>
          <p className="leading-relaxed text-[#CFE0D4]">{s.body}</p>
        </section>
      ))}
      <p className="text-mute">
        The API behind this site is public and documented at <a className="link" href="/docs">/docs</a>.
        Every match also has a no-JavaScript page for slow connections, e.g. <a className="link" href="/m/3869685">/m/3869685</a>.
        {" "}<Link className="link" to="/replays">Start a replay</Link> to watch the correction pipeline work.
      </p>
    </div>
  );
}
