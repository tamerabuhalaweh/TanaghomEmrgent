import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "./lib/auth";
import { I18nProvider } from "./lib/i18n";
import AppLayout from "./components/AppLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Events from "./pages/Events";
import EventDetail from "./pages/EventDetail";
import AIBuilder from "./pages/AIBuilder";
import Users from "./pages/Users";
import Settings from "./pages/Settings";
import Integrations from "./pages/Integrations";

function Protected({ children, adminOnly }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center text-slate-500 text-sm">
        Loading...
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (adminOnly && user.role !== "admin") return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <Protected>
              <AppLayout />
            </Protected>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="/events" element={<Events />} />
          <Route path="/events/:id" element={<EventDetail />} />
          <Route path="/ai" element={<AIBuilder />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route
            path="/users"
            element={
              <Protected adminOnly>
                <Users />
              </Protected>
            }
          />
          <Route
            path="/settings"
            element={
              <Protected adminOnly>
                <Settings />
              </Protected>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <AuthProvider>
        <Toaster
          position="top-center"
          toastOptions={{
            className: "!font-medium",
          }}
        />
        <AppRoutes />
      </AuthProvider>
    </I18nProvider>
  );
}
