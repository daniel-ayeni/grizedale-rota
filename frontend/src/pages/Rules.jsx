import { useEffect, useState } from "react";
import { Lock, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
    Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

const RULE_DEFS = [
    { key: "day_cover",            name: "Day cover: 2 staff (2D or D+D*)",      desc: "Each calendar day must have exactly two day-shift staff.", immovable: true },
    { key: "night_cover",          name: "Night cover: D*+N or *+N (never 2N)",  desc: "Each night needs one waking-night plus one sleepover; never two N.", immovable: true },
    { key: "no_n_to_d",            name: "No N → D back-to-back",                desc: "Staff cannot work a day shift the morning after a waking night.", immovable: true },
    { key: "no_dstar_to_dstar",    name: "No D* → D* back-to-back",              desc: "Sleepover-day shifts cannot be consecutive.", immovable: true },
    { key: "med_competent_required", name: "Medication-competent on every shift", desc: "Every day shift and every night shift includes ≥1 medication-competent staff." },
    { key: "first_aider_required",   name: "First-aider on every shift",          desc: "Every day shift and every night shift includes ≥1 first-aider." },
    { key: "no_male_pair_alone",     name: "Male staff cannot be alone together", desc: "If any male staff is on a shift, at least one female must be on the same shift." },
    { key: "manager_no_shifts",      name: "Manager (J.C.) does not work shifts", desc: "Admin-only staff are excluded from rota shifts unless explicitly locked." },
    { key: "contracted_hours_min",   name: "Every staff hits contracted hours",   desc: "Total scheduled hours ≥ target − leave/training hours (−2h tolerance)." },
    { key: "sleepover_preference",   name: "Sleepover-capable staff prefer D*",   desc: "When a sleepover-capable staff is on a day shift, prefer D* over D." },
    { key: "preferred_off_days",     name: "Honour staff day-of-week preferences", desc: "Avoid scheduling staff on their preferred-off days." },
    { key: "avoid_pairs",            name: "Avoid pairing flagged staff",         desc: "Avoid placing 'do not pair' staff together on the same shift." },
    { key: "weekend_fairness",       name: "Fair distribution of weekends off",   desc: "Spread weekend shifts proportionally to contracted hours." },
    { key: "overtime_prefer_flexi",  name: "Overtime preference → flexi staff",   desc: "When extra hours are needed above contracted minimums, prefer giving them to the flexi staff (default D.A.) up to a weekly cap.", hasParams: true },
    { key: "prefer_dstar_over_star", name: "Prefer D* over * on night cover",     desc: "When the night sleepover slot can be filled by D* (a day-staff who sleeps in) or * (sleepover-only), prefer D*." },
    { key: "non_flexi_overage",      name: "Non-flexi staff stay near contracted hours", desc: "Strong penalty for assigning non-flexi staff above their contracted weekly hours × weeks." },
];

const MODES = [
    { value: "hard", label: "Hard" },
    { value: "soft", label: "Soft" },
    { value: "off", label: "Off" },
];

export default function Rules() {
    const [config, setConfig] = useState(null);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        api.get("/rules").then((r) => setConfig(r.data)).catch((e) => toast.error(formatApiError(e)));
    }, []);

    if (!config) return <div className="text-sm text-muted-foreground" data-testid="rules-loading">Loading rules…</div>;

    const setMode = (key, mode) => {
        setConfig((c) => ({
            ...c,
            rules: { ...c.rules, [key]: { ...c.rules[key], mode } },
        }));
        setDirty(true);
    };
    const setWeight = (key, weight) => {
        setConfig((c) => ({
            ...c,
            rules: { ...c.rules, [key]: { ...c.rules[key], weight } },
        }));
        setDirty(true);
    };
    const setParam = (key, paramKey, value) => {
        setConfig((c) => ({
            ...c,
            rules: {
                ...c.rules,
                [key]: {
                    ...c.rules[key],
                    params: { ...(c.rules[key]?.params || {}), [paramKey]: value },
                },
            },
        }));
        setDirty(true);
    };

    const save = async () => {
        setSaving(true);
        try {
            const { data } = await api.put("/rules", { rules: config.rules });
            setConfig(data);
            setDirty(false);
            toast.success("Rules saved — solver will use these on next generate");
        } catch (err) {
            toast.error(formatApiError(err));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-6" data-testid="rules-page">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="display text-3xl font-semibold">Rules</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Toggle each rule between Hard, Soft (with weight) and Off.
                        Locked rules are immovable cover requirements.
                    </p>
                </div>
                <Button
                    className="btn-primary"
                    disabled={!dirty || saving}
                    onClick={save}
                    data-testid="rules-save-button"
                >
                    <Save className="w-4 h-4 mr-1.5" />
                    {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
                </Button>
            </div>

            <div className="section-header" data-testid="rules-section-header">Constraint Engine</div>

            <div className="grid grid-cols-1 gap-3" data-testid="rules-list">
                {RULE_DEFS.map((rd) => {
                    const r = config.rules[rd.key] || { mode: "off", weight: 0 };
                    const immovable = rd.immovable || r.immovable;
                    return (
                        <div key={rd.key} className="app-card p-5" data-testid={`rule-${rd.key}`}>
                            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <div className="display text-base font-semibold">{rd.name}</div>
                                        {immovable && (
                                            <Badge variant="outline" className="rule-locked text-[10px] uppercase tracking-wider" data-testid={`rule-${rd.key}-locked`}>
                                                <Lock className="w-3 h-3 mr-1" /> Immovable
                                            </Badge>
                                        )}
                                    </div>
                                    <div className="text-sm text-muted-foreground mt-1">{rd.desc}</div>
                                </div>

                                <Tabs value={r.mode} onValueChange={(v) => !immovable && setMode(rd.key, v)} className="shrink-0">
                                    <TabsList data-testid={`rule-${rd.key}-mode`}>
                                        {MODES.map((m) => (
                                            <TabsTrigger
                                                key={m.value}
                                                value={m.value}
                                                disabled={immovable && m.value !== r.mode}
                                                data-testid={`rule-${rd.key}-mode-${m.value}`}
                                            >
                                                {m.label}
                                            </TabsTrigger>
                                        ))}
                                    </TabsList>
                                </Tabs>
                            </div>

                            {r.mode === "soft" && !immovable && (
                                <div className="mt-4 pt-4 border-t" style={{ borderColor: "hsl(var(--border))" }}>
                                    <div className="flex items-center justify-between text-xs uppercase tracking-wider text-muted-foreground mb-2">
                                        <span>Penalty weight</span>
                                        <span data-testid={`rule-${rd.key}-weight-display`}>{r.weight ?? 1}</span>
                                    </div>
                                    <Slider
                                        min={1}
                                        max={100}
                                        step={1}
                                        value={[Math.min(100, Math.max(1, Number(r.weight) || 1))]}
                                        onValueChange={(v) => setWeight(rd.key, v[0])}
                                        data-testid={`rule-${rd.key}-weight-slider`}
                                    />
                                    {rd.hasParams && (
                                        <div className="mt-4 grid grid-cols-2 gap-3" data-testid={`rule-${rd.key}-params`}>
                                            <div>
                                                <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">Preferred staff initials</label>
                                                <input
                                                    className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                                                    style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                                                    value={r.params?.preferred_staff_initials || ""}
                                                    onChange={(e) => setParam(rd.key, "preferred_staff_initials", e.target.value)}
                                                    data-testid={`rule-${rd.key}-param-staff`}
                                                />
                                            </div>
                                            <div>
                                                <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">Weekly cap (hours)</label>
                                                <input
                                                    type="number"
                                                    min={0}
                                                    max={80}
                                                    className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                                                    style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                                                    value={r.params?.weekly_cap ?? 48}
                                                    onChange={(e) => setParam(rd.key, "weekly_cap", Number(e.target.value))}
                                                    data-testid={`rule-${rd.key}-param-cap`}
                                                />
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
