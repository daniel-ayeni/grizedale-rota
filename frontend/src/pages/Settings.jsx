import { useEffect, useState } from "react";
import { Save, Sun, Moon, Users as UsersIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import { useTheme } from "@/contexts/ThemeContext";

const SHIFT_KEYS = ["D", "D*", "N", "*", "OFF", "AL", "TRN"];

export default function Settings() {
    const [settings, setSettings] = useState(null);
    const [staff, setStaff] = useState([]);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const { theme, setTheme } = useTheme();

    useEffect(() => {
        Promise.all([api.get("/settings"), api.get("/staff")])
            .then(([sr, st]) => { setSettings(sr.data); setStaff(st.data); })
            .catch((e) => toast.error(formatApiError(e)));
    }, []);

    if (!settings) return <div className="text-sm text-muted-foreground" data-testid="settings-loading">Loading…</div>;

    // Dynamic senior choices — any staff flagged `is_senior` or `is_deputy`
    // on /staff becomes available in the weekend rotation dropdown.
    const seniorChoices = staff
        .filter((s) => s.active && (s.is_senior || s.is_deputy))
        .map((s) => s.initials)
        .sort();

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

            <div className="section-header" data-testid="settings-section-senior-rotation">Weekend Senior Rotation</div>
            <div className="app-card p-5" data-testid="settings-senior-rotation-card">
                <div className="text-sm text-muted-foreground mb-4 flex items-start gap-2">
                    <UsersIcon className="w-4 h-4 mt-0.5 shrink-0" />
                    <span>
                        Pick which senior covers Sat &amp; Sun of each week. The dropdown lists every
                        staff tagged <strong>SEN</strong> or <strong>DEP</strong> on /staff — promote someone to Senior and
                        they appear here automatically. If the assigned senior is on AL / TRN that weekend, the solver
                        automatically falls back to any other eligible senior.
                    </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    {[1, 2, 3, 4].map((wi) => {
                        const entry = (settings.senior_weekend_rotation || []).find((r) => r.week_index === wi)
                            || { week_index: wi, staff_initials: seniorChoices[(wi - 1) % Math.max(1, seniorChoices.length)] || "" };
                        const setRotationStaff = (newStaff) => {
                            const cur = (settings.senior_weekend_rotation || []).slice();
                            const idx = cur.findIndex((r) => r.week_index === wi);
                            const next = { week_index: wi, staff_initials: newStaff };
                            if (idx >= 0) cur[idx] = next; else cur.push(next);
                            cur.sort((a, b) => a.week_index - b.week_index);
                            update("senior_weekend_rotation", cur);
                        };
                        return (
                            <div key={wi} className="rounded-lg p-3"
                                 style={{ background: "hsl(var(--bg-elev))", border: "1px solid hsl(var(--border))" }}
                                 data-testid={`senior-rotation-week-${wi}`}>
                                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">Week {wi} weekend</div>
                                <Select value={entry.staff_initials} onValueChange={setRotationStaff}>
                                    <SelectTrigger data-testid={`senior-rotation-week-${wi}-trigger`}>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {seniorChoices.length === 0 && (
                                            <SelectItem value="none" disabled>No senior-flagged staff — tag staff with SEN or DEP on /staff</SelectItem>
                                        )}
                                        {seniorChoices.map((s) => (
                                            <SelectItem key={s} value={s}>{s}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div className="section-header" data-testid="settings-section-cover">Cover counts</div>
            <div className="app-card p-5 space-y-4" data-testid="settings-cover-card">
                <div className="text-sm text-muted-foreground">
                    How many staff must be on cover each day and each night. Default 2 / 2. Bump to 3
                    if you need a third staff for heavier days. Per-date overrides below take precedence.
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Field label="Day cover count (staff on D / D*)">
                        <Input
                            type="number" min={1} max={5}
                            value={settings.day_cover_count ?? 2}
                            onChange={(e) => update("day_cover_count", Math.max(1, parseInt(e.target.value, 10) || 1))}
                            data-testid="settings-day-cover-count"
                        />
                    </Field>
                    <Field label="Night cover count (waking N + sleepover)">
                        <Input
                            type="number" min={1} max={5}
                            value={settings.night_cover_count ?? 2}
                            onChange={(e) => update("night_cover_count", Math.max(1, parseInt(e.target.value, 10) || 1))}
                            data-testid="settings-night-cover-count"
                        />
                    </Field>
                </div>
                <CoverOverridesEditor
                    overrides={settings.cover_overrides || []}
                    defaultDay={settings.day_cover_count ?? 2}
                    defaultNight={settings.night_cover_count ?? 2}
                    onChange={(next) => update("cover_overrides", next)}
                />
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

/**
 * CoverOverridesEditor — per-date exceptions to the global day/night
 * cover counts. Useful for a heavy day (e.g. service-user admission
 * assessment) where the manager wants 3 day staff instead of 2.
 * Empty list → global counts apply everywhere.
 */
function CoverOverridesEditor({ overrides, defaultDay, defaultNight, onChange }) {
    const addRow = () => onChange([...(overrides || []), { date: "", day_count: defaultDay, night_count: defaultNight }]);
    const setRow = (idx, patch) => {
        const next = overrides.map((o, i) => (i === idx ? { ...o, ...patch } : o));
        onChange(next);
    };
    const removeRow = (idx) => onChange(overrides.filter((_, i) => i !== idx));
    return (
        <div className="pt-2" data-testid="settings-cover-overrides">
            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">Per-date overrides</div>
            {(overrides || []).length === 0 && (
                <div className="text-xs italic text-muted-foreground mb-2">No overrides — global counts apply every day.</div>
            )}
            {(overrides || []).map((ov, idx) => (
                <div key={idx} className="flex flex-wrap items-end gap-2 mb-2" data-testid={`cover-override-${idx}`}>
                    <Field label="Date">
                        <Input
                            type="date"
                            value={ov.date || ""}
                            onChange={(e) => setRow(idx, { date: e.target.value })}
                            className="w-40"
                            data-testid={`cover-override-${idx}-date`}
                        />
                    </Field>
                    <Field label="Day">
                        <Input
                            type="number" min={1} max={5}
                            value={ov.day_count ?? defaultDay}
                            onChange={(e) => setRow(idx, { day_count: parseInt(e.target.value, 10) || 1 })}
                            className="w-20"
                            data-testid={`cover-override-${idx}-day`}
                        />
                    </Field>
                    <Field label="Night">
                        <Input
                            type="number" min={1} max={5}
                            value={ov.night_count ?? defaultNight}
                            onChange={(e) => setRow(idx, { night_count: parseInt(e.target.value, 10) || 1 })}
                            className="w-20"
                            data-testid={`cover-override-${idx}-night`}
                        />
                    </Field>
                    <Button variant="ghost" size="sm" onClick={() => removeRow(idx)} data-testid={`cover-override-${idx}-remove`}>
                        Remove
                    </Button>
                </div>
            ))}
            <Button variant="outline" size="sm" onClick={addRow} data-testid="cover-override-add">
                + Add override date
            </Button>
        </div>
    );
}

