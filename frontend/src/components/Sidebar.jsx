import { useLocation, useNavigate } from "react-router-dom";

// The mockup's rail: seven unlabelled markers with the third one active on both
// screens. Kept as a shared component so it persists across the two routes,
// which the brief asks for explicitly.
const MARKERS = [0, 1, 2, 3, 4, 5, 6];
const ACTIVE = 2;

export default function Sidebar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <nav className="sidebar" aria-label="Sections">
      {MARKERS.map((marker) => (
        <button
          key={marker}
          type="button"
          className={"marker" + (marker === ACTIVE ? " marker-active" : "")}
          aria-current={marker === ACTIVE ? "page" : undefined}
          aria-label={marker === ACTIVE ? "Handoff queue" : `Section ${marker + 1}`}
          onClick={() => marker === ACTIVE && pathname !== "/" && navigate("/")}
        />
      ))}
    </nav>
  );
}
