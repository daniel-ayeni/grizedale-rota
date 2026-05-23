import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "@/index.css";
import "@/App.css";

import { AuthProvider } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Staff from "@/pages/Staff";
import ServiceUsers from "@/pages/ServiceUsers";
import Rules from "@/pages/Rules";
import Settings from "@/pages/Settings";
import Admins from "@/pages/Admins";
import Rotas from "@/pages/Rotas";
import RotaEditor from "@/pages/RotaEditor";
import Holidays from "@/pages/Holidays";
import Requests from "@/pages/Requests";
import RequestLink from "@/pages/RequestLink";
import SetNewPassword from "@/pages/SetNewPassword";

function App() {
    return (
        <ThemeProvider>
            <AuthProvider>
                <BrowserRouter>
                    <Routes>
                        {/* Public — no auth, no Layout */}
                        <Route path="/r/:token" element={<RequestLink />} />
                        <Route path="/login" element={<Login />} />
                        <Route path="/set-new-password" element={<SetNewPassword />} />
                        {/* Authenticated app shell */}
                        <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
                            <Route path="/" element={<Navigate to="/dashboard" replace />} />
                            <Route path="/dashboard" element={<Dashboard />} />
                            <Route path="/rotas" element={<Rotas />} />
                            <Route path="/rotas/:id" element={<RotaEditor />} />
                            <Route path="/holidays" element={<Holidays />} />
                            <Route path="/requests" element={<Requests />} />
                            <Route path="/staff" element={<Staff />} />
                            <Route path="/service-users" element={<ServiceUsers />} />
                            <Route path="/rules" element={<Rules />} />
                            <Route path="/settings" element={<Settings />} />
                            <Route path="/admins" element={<Admins />} />
                        </Route>
                        <Route path="*" element={<Navigate to="/dashboard" replace />} />
                    </Routes>
                </BrowserRouter>
            </AuthProvider>
        </ThemeProvider>
    );
}

export default App;
