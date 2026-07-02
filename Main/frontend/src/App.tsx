import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ConsolePage } from "./pages/ConsolePage";

function QueryRedirect({ to }: { to: string }) {
  return <Navigate to={to} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ConsolePage />} />
        <Route path="history" element={<QueryRedirect to="/?#history" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
