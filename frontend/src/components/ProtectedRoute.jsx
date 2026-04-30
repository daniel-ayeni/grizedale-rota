import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

export default function ProtectedRoute({ children }) {
    const { user } = useAuth();
    if (user === undefined) {
        return (
            <div className="min-h-screen flex items-center justify-center text-sm text-muted-foreground" data-testid="auth-loading">
                Checking session…
            </div>
        );
    }
    if (!user) return <Navigate to="/login" replace />;
    return children;
}
