import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import AnalyticsPage from "./pages/AnalyticsPage";
import ChatPage from "./pages/ChatPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="chat" element={<ChatPage />} />
      </Route>
    </Routes>
  );
}

export default App;