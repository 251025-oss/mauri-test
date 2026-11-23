import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Languages, { Welcome } from "./pages/Languages";
import Learn from "./pages/Learn";
import Lesson from "./pages/Lesson";
import Profile from "./pages/Profile";
import { useProgress } from "./state/progress";

export default function App() {
  const { state } = useProgress();
  return (
    <Routes>
      <Route path="/" element={state.language ? <Navigate to="/apprendre" replace /> : <Welcome />} />
      <Route element={<Layout />}>
        <Route path="/apprendre" element={<Learn />} />
        <Route path="/langues" element={<Languages />} />
        <Route path="/profil" element={<Profile />} />
      </Route>
      {/* La leçon s'affiche en plein écran, sans barre de navigation */}
      <Route path="/lecon/:index" element={<Lesson />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
