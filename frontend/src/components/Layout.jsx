import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import {
    LayoutDashboard,
    Users,
    HeartHandshake,
    Sliders,
    Settings as SettingsIcon,
    ShieldCheck,
    Sun,
    Moon,
    LogOut,
    Calendar,
    CalendarDays,
    Plane,
    Inbox,
} from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import api from "@/lib/api";

const NAV = [
    { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
    { to: "/rotas", label: "Rotas", icon: CalendarDays, testid: "nav-rotas" },
    { to: "/holidays", label: "Holidays", icon: Plane, testid: "nav-holidays" },
    { to: "/requests", label: "Requests", icon: Inbox, testid: "nav-requests" },
    { to: "/staff", label: "Staff", icon: Users, testid: "nav-staff" },
    { to: "/service-users", label: "Service Users", icon: HeartHandshake, testid: "nav-service-users" },
    { to: "/rules", label: "Rules", icon: Sliders, testid: "nav-rules" },
    { to: "/settings", label: "Settings", icon: SettingsIcon, testid: "nav-settings" },
    { to: "/admins", label: "Admins", icon: ShieldCheck, testid: "nav-admins" },
];

export default function Layout() {
    const { user, logout } = useAuth();
    const { theme, toggle } = useTheme();
    const navigate = useNavigate();
    const [homeName, setHomeName] = useState("Grizedale");

    useEffect(() => {
        api.get("/settings").then((r) => setHomeName(r.data.home_name || "Grizedale")).catch(() => {});
    }, []);

    const onLogout = async () => {
        await logout();
        navigate("/login", { replace: true });
    };

    return (
        <div className="min-h-screen flex" data-testid="app-layout">
            {/* Sidebar */}
            <aside className="app-sidebar w-64 shrink-0 hidden md:flex flex-col" data-testid="app-sidebar">
                <div className="px-5 py-6">
                    <div className="flex items-center gap-2">
                        <div
                            className="w-9 h-9 rounded-lg flex items-center justify-center"
                            style={{ background: "hsl(var(--section))", color: "hsl(var(--section-fg))" }}
                        >
                            <Calendar className="w-5 h-5" />
                        </div>
                        <div>
                            <div className="text-xs uppercase tracking-wider text-muted-foreground">Rota Builder</div>
                            <div className="display text-lg font-semibold leading-tight" data-testid="sidebar-home-name">{homeName}</div>
                        </div>
                    </div>
                </div>
                <nav className="px-3 flex-1 flex flex-col gap-1">
                    {NAV.map((item) => (
                        <NavLink
                            key={item.to}
                            to={item.to}
                            data-testid={item.testid}
                            className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                        >
                            <item.icon className="w-4 h-4" />
                            <span className="text-sm">{item.label}</span>
                        </NavLink>
                    ))}
                </nav>
                <div className="px-5 py-4 text-xs text-muted-foreground border-t" style={{ borderColor: "hsl(var(--border))" }}>
                    Phase 2 · v0.3.0
                </div>
            </aside>

            {/* Main column */}
            <div className="flex-1 flex flex-col min-w-0">
                {/* Top bar */}
                <header className="app-topbar h-16 px-6 flex items-center justify-between" data-testid="app-topbar">
                    <div className="flex items-center gap-3">
                        <span className="display text-xl font-semibold">{homeName}</span>
                        <span className="text-xs text-muted-foreground">·</span>
                        <span className="text-sm text-muted-foreground">Care Home Rota Builder</span>
                    </div>
                    <div className="flex items-center gap-3">
                        <button
                            type="button"
                            onClick={toggle}
                            data-testid="theme-toggle"
                            className="flex items-center gap-2 text-sm px-3 py-1.5 rounded-full border focus-ring"
                            style={{
                                borderColor: "hsl(var(--border-strong))",
                                background: "hsl(var(--bg))",
                            }}
                            aria-label="Toggle theme"
                        >
                            {theme === "paper" ? (
                                <Sun className="w-4 h-4" />
                            ) : (
                                <Moon className="w-4 h-4" />
                            )}
                            <span className="capitalize">{theme}</span>
                        </button>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <button
                                    type="button"
                                    data-testid="user-menu-trigger"
                                    className="flex items-center gap-2 text-sm px-3 py-1.5 rounded-full border focus-ring"
                                    style={{
                                        borderColor: "hsl(var(--border-strong))",
                                        background: "hsl(var(--bg))",
                                    }}
                                >
                                    <div
                                        className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold"
                                        style={{ background: "hsl(var(--primary))", color: "hsl(var(--primary-fg))" }}
                                    >
                                        {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
                                    </div>
                                    <span className="hidden sm:inline">{user?.name || user?.email}</span>
                                </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-56" data-testid="user-menu-content">
                                <DropdownMenuLabel>
                                    <div className="text-sm font-medium">{user?.name}</div>
                                    <div className="text-xs text-muted-foreground">{user?.email}</div>
                                </DropdownMenuLabel>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem onClick={onLogout} data-testid="logout-button">
                                    <LogOut className="w-4 h-4 mr-2" /> Log out
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                </header>

                {/* Mobile nav */}
                <nav className="md:hidden flex overflow-x-auto px-4 py-2 gap-2" data-testid="mobile-nav">
                    {NAV.map((item) => (
                        <NavLink
                            key={item.to}
                            to={item.to}
                            data-testid={`m-${item.testid}`}
                            className={({ isActive }) => `nav-link whitespace-nowrap ${isActive ? "active" : ""}`}
                        >
                            <item.icon className="w-4 h-4" />
                            <span className="text-sm">{item.label}</span>
                        </NavLink>
                    ))}
                </nav>

                <main className="flex-1 px-6 py-8 max-w-7xl w-full mx-auto" data-testid="app-main">
                    <Outlet />
                </main>
            </div>
            <Toaster richColors closeButton />
        </div>
    );
}
