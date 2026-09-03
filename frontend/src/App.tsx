import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Benchmark } from "./pages/Benchmark";
import { Chat } from "./pages/Chat";
import { ControlTower } from "./pages/ControlTower";
import { Exceptions } from "./pages/Exceptions";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ControlTower />} />
        <Route path="exceptions" element={<Exceptions />} />
        <Route path="chat" element={<Chat />} />
        <Route path="benchmark" element={<Benchmark />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
