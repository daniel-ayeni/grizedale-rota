import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
    Users,
    HeartHandshake,
    Sliders,
    Settings as SettingsIcon,
    ShieldCheck,
    Sparkles,
    Calendar,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import api from "@/lib/api";

const CARDS = [
    { to: "/staff", label: "Staff", icon: Users, desc: "Edit staff, flags, target hours" },
    { to: "/service-users", label: "Service Users", icon: HeartHandshake, desc: "7 service users + needs" },
    { to: "/rules", label: "Rules", icon: Sliders, desc: "Hard / soft / off + weights" },
    { to: "/settings", label: "Settings", icon: SettingsIcon, desc: "Home, hours, holidays, theme" },
    { to: "/admins", label: "Admins", icon: ShieldCheck, desc: "Manage admin users" },
];

export default function Dashboard() {
    const [counts, setCounts] = useState({ staff: 0, serviceUsers: 0, admins: 0 });
    const [homeName, setHomeName] = useState("Grizedale");
    const [today] = useState(() => new Date().toLocaleDateString(undefined, {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
    }));

    useEffect(() => {
        Promise.all([
            api.get("/staff").then((r) => r.data.length).catch(() => 0),
            api.get("/service-users").then((r) => r.data.length).catch(() => 0),
            api.get("/admins").then((r) => r.data.length).catch(() => 0),
            api.get("/settings").then((r) => r.data.home_name).catch(() => null),
        ]).then(([staff, serviceUsers, admins, name]) => {
            setCounts({ staff, serviceUsers, admins });
            if (name) setHomeName(name);
        });
    }, []);

    return (
        <div className="space-y-8" data-testid="dashboard-page">
            <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
                        {today}
                    </div>
                    <h1 className="display text-3xl sm:text-4xl font-semibold">
                        {homeName} Rota
                    </h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Foundation built. Review staff, rules and settings, then generate the rota.
                    </p>
                </div>
                <TooltipProvider delayDuration={150}>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <span data-testid="generate-rota-button-wrapper">
                                <Button
                                    className="btn-primary"
                                    disabled
                                    data-testid="generate-rota-button"
                                >
                                    <Sparkles className="w-4 h-4 mr-2" />
                                    Generate Rota
                                </Button>
                            </span>
                        </TooltipTrigger>
                        <TooltipContent>Coming in Phase 3 — engine ready, wiring next.</TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </header>

            {/* Stat strip */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4" data-testid="dashboard-stats">
                <StatCard label="Staff" value={counts.staff} icon={Users} testid="stat-staff" />
                <StatCard label="Service Users" value={counts.serviceUsers} icon={HeartHandshake} testid="stat-service-users" />
                <StatCard label="Admins" value={counts.admins} icon={ShieldCheck} testid="stat-admins" />
            </div>

            {/* Section header band */}
            <div className="section-header" data-testid="dashboard-section-header">
                Manage
            </div>

            {/* Nav cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="dashboard-nav-cards">
                {CARDS.map((c) => (
                    <Link
                        key={c.to}
                        to={c.to}
                        data-testid={`card-${c.to.slice(1)}`}
                        className="app-card p-5 flex items-start gap-4 hover:translate-y-[-2px] transition-transform"
                    >
                        <div
                            className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                            style={{ background: "hsl(var(--section) / .15)", color: "hsl(var(--section))" }}
                        >
                            <c.icon className="w-5 h-5" />
                        </div>
                        <div className="min-w-0">
                            <div className="display text-base font-semibold">{c.label}</div>
                            <div className="text-sm text-muted-foreground mt-0.5">{c.desc}</div>
                        </div>
                    </Link>
                ))}
            </div>

            <div className="app-card p-5 flex items-center gap-3 text-sm" data-testid="dashboard-engine-status">
                <Calendar className="w-4 h-4" style={{ color: "hsl(var(--section))" }} />
                <span><strong>Solver engine status:</strong> ready. Hard rules + soft penalties active. Sub-second solves on the seed.</span>
            </div>
        </div>
    );
}

function StatCard({ label, value, icon: Icon, testid }) {
    return (
        <div className="app-card p-5" data-testid={testid}>
            <div className="flex items-center justify-between">
                <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
                <Icon className="w-4 h-4 text-muted-foreground" />
            </div>
            <div className="display text-3xl font-semibold mt-2">{value}</div>
        </div>
    );
}
