/** Onside design tokens. One committed visual world: a floodlit pitch at
 *  night. Two colours carry meaning and are never decorative: amber means
 *  "this was changed after the fact" and violet means "this is a replay of a
 *  match that has already been played". */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Night match under floodlights: near-black turf, chalk lines.
        night: "#06100B",
        deck: "#0C1A12",
        deck2: "#132519",
        rule: "#1F3A2A",
        chalk: "#F2F6F0",
        mute: "#9DB2A4",
        dim: "#647A6C",
        grass: "#2FCB74",      // the brand accent: the pitch itself
        home: "#5CC8FF",
        away: "#FF5A6E",
        draw: "#3C5A48",
        signal: "#FFC53D",     // corrections, and nothing else
        replay: "#B79CFF",     // replays of archived matches, and nothing else
        live: "#3DFF9E",       // a real feed that is live right now
        pitch: "#0E2618",
        line: "#2C5A40",
      },
      fontFamily: {
        display: ["Anton", "Impact", "Arial Narrow Bold", "sans-serif"],
        sans: ["Manrope", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      keyframes: {
        blip: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".25" } },
        slam: { from: { opacity: "0", transform: "translateY(-8px) scale(.985)" }, to: { opacity: "1", transform: "none" } },
        sweep: {
          "0%": { opacity: "0", backgroundPosition: "120% 0" },
          "25%": { opacity: "1" },
          "100%": { opacity: "0", backgroundPosition: "-120% 0" },
        },
      },
      animation: { blip: "blip 1.4s ease-in-out infinite", slam: "slam .45s cubic-bezier(.16,1.2,.3,1)", sweep: "sweep .8s ease-out" },
    },
  },
  plugins: [],
};
