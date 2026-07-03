import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ConsolePage } from "./pages/ConsolePage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ConsolePage />} />
        <Route path="history" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
