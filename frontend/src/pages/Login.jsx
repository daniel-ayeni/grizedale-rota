import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Calendar, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

    useEffect(() => {
        if (user) navigate("/dashboard", { replace: true });
    }, [user, navigate]);

    const onSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            await login(email, password);
            toast.success("Welcome back");
            navigate("/dashboard", { replace: true });
        } catch (err) {
            toast.error(err.message);
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen flex login-hero" data-testid="login-page">
            <div className="hidden lg:flex flex-1 items-center justify-center px-12">
                <div className="max-w-md">
                    <div
                        className="w-12 h-12 rounded-xl flex items-center justify-center mb-6"
                        style={{ background: "hsl(var(--section))", color: "hsl(var(--section-fg))" }}
                    >
                        <Calendar className="w-6 h-6" />
                    </div>
                    <h1 className="display text-4xl sm:text-5xl font-semibold leading-tight mb-4">
                        Rotas built<br />the way they should be.
                    </h1>
                    <p className="text-base text-muted-foreground leading-relaxed">
                        A constraint-aware rota builder for Grizedale — designed around the rules
                        you already follow, with the look-and-feel of the paper rota you trust.
                    </p>
                    <ul className="mt-8 space-y-3 text-sm">
                        <li className="flex items-start gap-2">
                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full" style={{ background: "hsl(var(--section))" }} />
                            <span>4-week cycles, 8 staff, 7 service users.</span>
                        </li>
                        <li className="flex items-start gap-2">
                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full" style={{ background: "hsl(var(--section))" }} />
                            <span>Hard constraints honoured automatically.</span>
                        </li>
                        <li className="flex items-start gap-2">
                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full" style={{ background: "hsl(var(--section))" }} />
                            <span>Soft preferences tuned by you.</span>
                        </li>
                    </ul>
                </div>
            </div>

            <div className="flex-1 flex items-center justify-center px-6 py-10">
                <div className="app-card w-full max-w-md p-8 sm:p-10 shadow-xl" data-testid="login-card">
                    <div className="flex items-center justify-between mb-8">
                        <div>
                            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
                                Sign in
                            </div>
                            <h2 className="display text-2xl font-semibold">Welcome back</h2>
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

                    <div className="mt-8 pt-6 border-t text-xs text-muted-foreground" style={{ borderColor: "hsl(var(--border))" }}>
                        Need help? Speak to your administrator. Default credentials are
                        printed in the backend logs.
                    </div>
                </div>
            </div>
        </div>
    );
}
