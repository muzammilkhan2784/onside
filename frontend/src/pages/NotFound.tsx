import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="font-display text-8xl text-signal">Offside</p>
      <p className="mt-4 text-[15px] text-mute">
        This page was a step beyond the last defender - there's nothing at this address. The match, team or player may not be in the archive.
      </p>
      <div className="mt-6 flex justify-center gap-2">
        <Link to="/" className="btn btn-primary">Back to the front page</Link>
        <Link to="/news" className="btn">Browse stories</Link>
      </div>
    </div>
  );
}
