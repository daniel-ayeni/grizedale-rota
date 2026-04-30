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

function App() {
    return (
        <ThemeProvider>
            <AuthProvider>
                <BrowserRouter>
                    <Routes>
                        <Route path="/login" element={<Login />} />
                        <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
                            <Route path="/" element={<Navigate to="/dashboard" replace />} />
                            <Route path="/dashboard" element={<Dashboard />} />
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
