import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Calendar, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { toast } from "sonner";

export default function Login() {
    const { user, login } = useAuth();
    const { theme, toggle } = useTheme();
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [forgotOpen, setForgotOpen] = useState(false);

    useEffect(() => {
        if (user) navigate("/dashboard", { replace: true });
    }, [user, navigate]);

    const onSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const loggedIn = await login(email, password);
            // If admin reset the password, force the change-password
            // dialog and pre-fill the temp password so the user only
            // has to choose a new one. We hand the temp password to
            // the dialog via location state so it survives the nav.
            if (loggedIn?.password_must_change) {
                toast.warning("You must set a new password before continuing");
                navigate("/set-new-password", { replace: true, state: { tempPassword: password } });
                return;
            }
            toast.success("Welcome back");
            navigate("/dashboard", { replace: true });
        } catch (err) {
            toast.error(err.message);
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center login-hero px-4" data-testid="login-page">
            <div className="app-card w-full max-w-md p-8 sm:p-10 shadow-xl" data-testid="login-card">
                {/* Brand: small icon + minimal heading. No marketing copy. */}
                <div className="flex items-center gap-3 mb-8">
                    <div
                        className="w-11 h-11 rounded-xl flex items-center justify-center"
                        style={{ background: "hsl(var(--section))", color: "hsl(var(--section-fg))" }}
                    >
                        <Calendar className="w-5 h-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Grizedale Care Home</div>
                        <h1 className="display text-lg font-semibold leading-tight truncate">Rota Builder</h1>
                    </div>
                    <button
                        type="button"
                        onClick={toggle}
                        data-testid="login-theme-toggle"
                        className="text-xs px-2.5 py-1 rounded-full border focus-ring capitalize"
                        style={{ borderColor: "hsl(var(--border-strong))" }}
                    >
                        {theme}
                    </button>
                </div>

                <form onSubmit={onSubmit} className="space-y-4">
                    <div>
                        <Label htmlFor="email" className="text-sm">Email</Label>
                        <Input
                            id="email"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            autoFocus
                            required
                            placeholder="manager@grizedale.local"
                            data-testid="login-email-input"
                            className="mt-1.5 focus-ring"
                        />
                    </div>
                    <div>
                        <Label htmlFor="password" className="text-sm">Password</Label>
                        <Input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            placeholder="••••••••••"
                            data-testid="login-password-input"
                            className="mt-1.5 focus-ring"
                        />
                    </div>
                    <Button
                        type="submit"
                        className="btn-primary w-full mt-6 group"
                        disabled={submitting}
                        data-testid="login-submit-button"
                    >
                        {submitting ? "Signing in…" : "Sign in"}
                        {!submitting && <ArrowRight className="w-4 h-4 ml-1 group-hover:translate-x-0.5 transition-transform" />}
                    </Button>
                </form>

                <div className="mt-4 text-center">
                    <button
                        type="button"
                        onClick={() => setForgotOpen(true)}
                        className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                        data-testid="login-forgot-link"
                    >
                        Forgot password? Contact your manager to reset.
                    </button>
                </div>

                <div className="mt-4 text-xs text-muted-foreground">
                    Sign in as manager or admin.
                </div>
            </div>
            <ForgotPasswordDialog open={forgotOpen} onOpenChange={setForgotOpen} />
        </div>
    );
}

function ForgotPasswordDialog({ open, onOpenChange }) {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-sm" data-testid="forgot-password-dialog">
                <DialogHeader>
                    <DialogTitle>Forgot password</DialogTitle>
                    <DialogDescription>
                        Ask your manager or another admin to reset your password from the Admins page.
                        Once they share a temporary password, log in and you'll be prompted to set a new one.
                    </DialogDescription>
                </DialogHeader>
                <Button onClick={() => onOpenChange(false)} className="btn-primary mt-2" data-testid="forgot-password-ok">
                    Got it
                </Button>
            </DialogContent>
        </Dialog>
    );
}
