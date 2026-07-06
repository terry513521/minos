import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ConsolePage } from "./pages/ConsolePage";
import { RoundsHistoryPage } from "./pages/RoundsHistoryPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ConsolePage />} />
        <Route path="history/rounds" element={<RoundsHistoryPage />} />
        <Route path="history" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
