import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { PageSkeleton } from "./components/States";
import Home from "./pages/Home";

// The match page carries the charting code; everything else loads it on demand.
const Match = lazy(() => import("./pages/Match"));
const News = lazy(() => import("./pages/News"));
const Competitions = lazy(() => import("./pages/Competitions"));
const CompetitionPage = lazy(() => import("./pages/Competition"));
const TeamPage = lazy(() => import("./pages/Team"));
const PlayerPage = lazy(() => import("./pages/Player"));
const Stats = lazy(() => import("./pages/Stats"));
const Replays = lazy(() => import("./pages/Replays"));
const Matches = lazy(() => import("./pages/Matches"));
const Buzz = lazy(() => import("./pages/Buzz"));
const About = lazy(() => import("./pages/About"));
const NotFound = lazy(() => import("./pages/NotFound"));

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

export default function App() {
  return (
    <Layout>
      <ScrollToTop />
      <Suspense fallback={<PageSkeleton />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/news" element={<News />} />
          <Route path="/competitions" element={<Competitions />} />
          <Route path="/competitions/:cid" element={<CompetitionPage />} />
          <Route path="/competitions/:cid/:sid" element={<CompetitionPage />} />
          <Route path="/match/:mid" element={<Match />} />
          <Route path="/team/:tid" element={<TeamPage />} />
          <Route path="/player/:pid" element={<PlayerPage />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/replays" element={<Replays />} />
          <Route path="/matches" element={<Matches />} />
          <Route path="/buzz" element={<Buzz />} />
          <Route path="/today" element={<Navigate to="/matches" replace />} />
          <Route path="/live" element={<Navigate to="/replays" replace />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
