import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar.jsx";
import HandoffQueue from "./pages/HandoffQueue.jsx";
import ConversationDetail from "./pages/ConversationDetail.jsx";

export default function App() {
  return (
    <div className="shell">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<HandoffQueue />} />
          <Route path="/conversations/:id" element={<ConversationDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
