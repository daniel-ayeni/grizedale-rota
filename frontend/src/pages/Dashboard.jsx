import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
    Users,
    HeartHandshake,
    Sliders,
    Settings as SettingsIcon,
    ShieldCheck,
    Sparkles,
    Calendar,
    CalendarDays,
    Inbox,
    Plane,
    ArrowRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

const CARDS = [
    { to: "/rotas", label: "Rotas", icon: CalendarDays, desc: "Edit 4-week rotas" },
    { to: "/holidays", label: "Holidays", icon: Plane, desc: "Annual leave & training" },
    { to: "/requests", label: "Requests", icon: Inbox, desc: "Pending staff requests" },
    { to: "/staff", label: "Staff", icon: Users, desc: "Edit staff, flags, target hours" },
    { to: "/service-users", label: "Service Users", icon: HeartHandshake, desc: "7 service users + needs" },
    { to: "/rules", label: "Rules", icon: Sliders, desc: "Hard / soft / off + weights" },
    { to: "/settings", label: "Settings", icon: SettingsIcon, desc: "Home, hours, holidays, theme" },
    { to: "/admins", label: "Admins", icon: ShieldCheck, desc: "Manage admin users" },
];

export default function Dashboard() {
    const navigate = useNavigate();
    const [counts, setCounts] = useState({ staff: 0, serviceUsers: 0, admins: 0, rotas: 0, pendingReqs: 0 });
    const [homeName, setHomeName] = useState("Grizedale");
    const [today] = useState(() => new Date().toLocaleDateString(undefined, {
        weekday: "long", year: "numeric", month: "long", day: "numeric",
    }));
    const [rotas, setRotas] = useState([]);
    const [genOpen, setGenOpen] = useState(false);
    const [pickedRota, setPickedRota] = useState("");
    const [newDate, setNewDate] = useState("");
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        Promise.all([
            api.get("/staff").then((r) => r.data.length).catch(() => 0),
            api.get("/service-users").then((r) => r.data.length).catch(() => 0),
            api.get("/admins").then((r) => r.data.length).catch(() => 0),
            api.get("/rotas").then((r) => r.data).catch(() => []),
            api.get("/requests?status=pending").then((r) => r.data.length).catch(() => 0),
            api.get("/settings").then((r) => r.data).catch(() => null),
        ]).then(([staff, serviceUsers, admins, rotaList, pendingReqs, settings]) => {
            setCounts({ staff, serviceUsers, admins, rotas: rotaList.length, pendingReqs });
            setRotas(rotaList);
            if (settings?.home_name) setHomeName(settings.home_name);
            const draft = rotaList.find((r) => r.status === "draft");
            if (draft) setPickedRota(draft.id);
            if (settings?.rota_start_date_default) setNewDate(settings.rota_start_date_default);
        });
    }, []);

    const startGenerate = async () => {
        setBusy(true);
        try {
            let rotaId = pickedRota;
            if (!rotaId) {
                if (!newDate) {
                    toast.error("Pick a draft rota or enter a start date");
                    return;
                }
                const { data } = await api.post("/rotas", { start_date: newDate, weeks: 4 });
                rotaId = data.id;
            }
            setGenOpen(false);
            navigate(`/rotas/${rotaId}?generate=1`);
        } catch (err) {
            toast.error(formatApiError(err));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-8" data-testid="dashboard-page">
            <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">{today}</div>
                    <h1 className="display text-3xl sm:text-4xl font-semibold">{homeName} Rota</h1>
                    <p className="text-sm text-muted-foreground mt-1">Manage staff, leave and rotas. Generate a 4-week rota in seconds.</p>
                </div>
                <Button className="btn-primary" onClick={() => setGenOpen(true)} data-testid="generate-rota-button">
                    <Sparkles className="w-4 h-4 mr-2" /> Generate Rota
                </Button>
            </header>

            <div className="grid grid-cols-2 sm:grid-cols-5 gap-4" data-testid="dashboard-stats">
                <StatCard label="Staff" value={counts.staff} icon={Users} testid="stat-staff" />
                <StatCard label="Service Users" value={counts.serviceUsers} icon={HeartHandshake} testid="stat-service-users" />
                <StatCard label="Rotas" value={counts.rotas} icon={CalendarDays} testid="stat-rotas" />
                <StatCard label="Pending Requests" value={counts.pendingReqs} icon={Inbox} testid="stat-pending" />
                <StatCard label="Admins" value={counts.admins} icon={ShieldCheck} testid="stat-admins" />
            </div>

            <div className="section-header" data-testid="dashboard-section-header">Manage</div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" data-testid="dashboard-nav-cards">
                {CARDS.map((c) => (
                    <Link key={c.to} to={c.to} data-testid={`card-${c.to.slice(1)}`}
                        className="app-card p-5 flex items-start gap-4 hover:translate-y-[-2px] transition-transform">
                        <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                            style={{ background: "hsl(var(--section) / .15)", color: "hsl(var(--section))" }}>
                            <c.icon className="w-5 h-5" />
                        </div>
                        <div className="min-w-0">
                            <div className="display text-base font-semibold flex items-center gap-1">{c.label} <ArrowRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100" /></div>
                            <div className="text-sm text-muted-foreground mt-0.5">{c.desc}</div>
                        </div>
                    </Link>
                ))}
            </div>

            {/* Generate dialog */}
            <Dialog open={genOpen} onOpenChange={setGenOpen}>
                <DialogContent data-testid="generate-dialog">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2"><Sparkles className="w-5 h-5" style={{ color: "hsl(var(--section))" }} />Generate a rota</DialogTitle>
                        <DialogDescription>
                            Pick an existing draft rota, or create a new one for a start date.
                            The solver fills empty cells, preserves locked + AL/TRN, and respects accepted requests.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div>
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">Existing draft rota</Label>
                            <Select value={pickedRota} onValueChange={(v) => { setPickedRota(v); setNewDate(""); }}>
                                <SelectTrigger className="mt-1.5" data-testid="generate-pick-rota"><SelectValue placeholder="(no draft selected)" /></SelectTrigger>
                                <SelectContent>
                                    {rotas.filter((r) => r.status === "draft").map((r) => (
                                        <SelectItem key={r.id} value={r.id}>{r.start_date} · {r.title}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="text-center text-xs text-muted-foreground">— or —</div>
                        <div>
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">Create new for start date</Label>
                            <Input type="date" value={newDate} onChange={(e) => { setNewDate(e.target.value); setPickedRota(""); }}
                                className="mt-1.5" data-testid="generate-new-date" />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button onClick={startGenerate} className="btn-primary" disabled={busy} data-testid="generate-go">
                            {busy ? "Opening…" : "Open editor"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
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
