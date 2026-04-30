import { useEffect, useState } from "react";
import { Save, Sun, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import { useTheme } from "@/contexts/ThemeContext";

const SHIFT_KEYS = ["D", "D*", "N", "*", "OFF", "AL", "TRN"];

export default function Settings() {
    const [settings, setSettings] = useState(null);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const { theme, setTheme } = useTheme();

    useEffect(() => {
        api.get("/settings").then((r) => setSettings(r.data)).catch((e) => toast.error(formatApiError(e)));
    }, []);

    if (!settings) return <div className="text-sm text-muted-foreground" data-testid="settings-loading">Loading…</div>;

    const update = (k, v) => { setSettings((s) => ({ ...s, [k]: v })); setDirty(true); };
    const updateShiftHours = (k, v) => {
        setSettings((s) => ({ ...s, shift_hours: { ...s.shift_hours, [k]: Number(v) } }));
        setDirty(true);
    };

    const save = async () => {
        setSaving(true);
        try {
            const { data } = await api.put("/settings", settings);
            setSettings(data);
            setDirty(false);
            toast.success("Settings saved");
        } catch (err) {
            toast.error(formatApiError(err));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-6" data-testid="settings-page">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="display text-3xl font-semibold">Settings</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Home configuration, shift hours, holidays and theme.
                    </p>
                </div>
                <Button className="btn-primary" disabled={!dirty || saving} onClick={save} data-testid="settings-save-button">
                    <Save className="w-4 h-4 mr-1.5" />
                    {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
                </Button>
            </div>

            <div className="section-header" data-testid="settings-section-home">Home</div>
            <div className="app-card p-5 grid grid-cols-1 sm:grid-cols-2 gap-4" data-testid="settings-home-card">
                <Field label="Home name">
                    <Input value={settings.home_name || ""} onChange={(e) => update("home_name", e.target.value)} data-testid="settings-home-name" />
                </Field>
                <Field label="Rota length (weeks)">
                    <Input type="number" value={settings.rota_length_weeks ?? 4} disabled data-testid="settings-rota-length" />
                </Field>
                <Field label="Rota start day">
                    <Input value={settings.rota_start_day || "Mon"} onChange={(e) => update("rota_start_day", e.target.value)} data-testid="settings-rota-start-day" />
                </Field>
                <Field label="Default rota start date">
                    <Input type="date" value={settings.rota_start_date_default || ""} onChange={(e) => update("rota_start_date_default", e.target.value)} data-testid="settings-rota-start-date" />
                </Field>
            </div>

            <div className="section-header" data-testid="settings-section-hours">Shift Hours</div>
            <div className="app-card overflow-x-auto" data-testid="settings-shift-hours-card">
                <Table className="paper-table">
                    <TableHeader>
                        <TableRow>
                            <TableHead>Shift code</TableHead>
                            <TableHead>Description</TableHead>
                            <TableHead className="text-right">Hours</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {SHIFT_KEYS.map((k) => (
                            <TableRow key={k}>
                                <TableCell className="font-semibold">{k}</TableCell>
                                <TableCell className="text-sm text-muted-foreground">{describe(k)}</TableCell>
                                <TableCell className="text-right">
                                    <Input
                                        type="number"
                                        className="w-24 inline-block text-right"
                                        value={settings.shift_hours?.[k] ?? 0}
                                        onChange={(e) => updateShiftHours(k, e.target.value)}
                                        data-testid={`settings-hours-${k.replace("*","star")}`}
                                    />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            <div className="section-header" data-testid="settings-section-holidays">UK Public Holidays · 2026</div>
            <div className="app-card p-5" data-testid="settings-holidays-card">
                <ul className="text-sm grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    {(settings.public_holidays || []).map((h) => (
                        <li key={h.date} className="flex items-center justify-between p-2 rounded border" style={{ borderColor: "hsl(var(--border))" }}>
                            <span className="font-mono text-xs">{h.date}</span>
                            <span className="text-sm">{h.name}</span>
                        </li>
                    ))}
                </ul>
            </div>

            <div className="section-header" data-testid="settings-section-theme">Theme</div>
            <div className="app-card p-5 flex flex-wrap gap-3" data-testid="settings-theme-card">
                <ThemeButton active={theme === "paper"} onClick={() => { setTheme("paper"); update("theme_default", "paper"); }} icon={Sun} label="Paper" desc="Cream + orange — evokes the printed rota" testid="settings-theme-paper" />
                <ThemeButton active={theme === "modern"} onClick={() => { setTheme("modern"); update("theme_default", "modern"); }} icon={Moon} label="Modern" desc="Slate + teal accent, generous whitespace" testid="settings-theme-modern" />
            </div>
        </div>
    );
}

function describe(k) {
    return {
        D: "Day shift (08:00–20:00)",
        "D*": "Day + sleepover (08:00 → 08:00)",
        N: "Waking night (19:00–08:00)",
        "*": "Sleepover only",
        OFF: "Day off",
        AL: "Annual leave",
        TRN: "Training",
    }[k] || "";
}

function Field({ label, children }) {
    return (
        <div>
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
            <div className="mt-1.5">{children}</div>
        </div>
    );
}

function ThemeButton({ active, onClick, icon: Icon, label, desc, testid }) {
    return (
        <button
            type="button"
            onClick={onClick}
            data-testid={testid}
            className="text-left p-4 rounded-lg border flex-1 min-w-[220px] transition focus-ring"
            style={{
                borderColor: active ? "hsl(var(--primary))" : "hsl(var(--border))",
                background: active ? "hsl(var(--section) / .12)" : "transparent",
            }}
        >
            <div className="flex items-center gap-2">
                <Icon className="w-4 h-4" />
                <div className="display text-base font-semibold">{label}</div>
                {active && <span className="ml-auto text-xs uppercase tracking-wider" style={{ color: "hsl(var(--primary))" }}>Active</span>}
            </div>
            <div className="text-sm text-muted-foreground mt-1">{desc}</div>
        </button>
    );
}
