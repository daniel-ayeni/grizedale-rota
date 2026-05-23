import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { Calendar, Sun, Moon } from "lucide-react";
import ChangePasswordDialog from "@/components/ChangePasswordDialog";

/**
 * SetNewPassword — forced-password-change landing page reached when a
 * freshly-reset admin signs in with their temp password. The
 * ChangePasswordDialog opens in `firstLogin` mode (cannot be closed
 * without success) and pre-fills the temp password from router state.
 * On success the user is logged out and bounced back to /login.
 */
export default function SetNewPassword() {
    const { logout, user } = useAuth();
    const { theme, toggle } = useTheme();
    const navigate = useNavigate();
    const location = useLocation();
    const [open] = useState(true);
    const tempPassword = location.state?.tempPassword || "";

    const handleSuccess = async () => {
        await logout();
        navigate("/login", { replace: true });
    };

    return (
        <div className="min-h-screen login-hero flex items-center justify-center px-4" data-testid="set-new-password-page">
            <button
                type="button"
                onClick={toggle}
                className="absolute top-4 right-4 flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border focus-ring"
                style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg))" }}
                aria-label="Toggle theme"
                title={`Theme: ${theme} — click to switch`}
            >
                {theme === "paper" ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
                <span className="capitalize">{theme}</span>
            </button>
            <div className="app-card p-8 max-w-md w-full text-center">
                <Calendar className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
                <h1 className="display text-2xl font-semibold mb-2">
                    Welcome{user?.name ? `, ${user.name.split(" ")[0]}` : ""}
                </h1>
                <p className="text-sm text-muted-foreground">
                    Your password was reset by an admin. Set a new one before continuing.
                </p>
            </div>
            <ChangePasswordDialog
                open={open}
                firstLogin
                initialCurrentPassword={tempPassword}
                onOpenChange={() => {}}    // un-closable
                onSuccess={handleSuccess}
            />
        </div>
    );
}
