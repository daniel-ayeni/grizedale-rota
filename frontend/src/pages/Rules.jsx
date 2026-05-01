import { useEffect, useMemo, useState } from "react";
import { Lock, Save, Users as UsersIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
    Tabs, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

const RULE_DEFS = [
    { key: "day_cover",            name: "Day cover: 2 staff (2D or D+D*)",      desc: "Each calendar day must have exactly two day-shift staff.", immovable: true },
    { key: "night_cover",          name: "Night cover: D*+N or *+N (never 2N)",  desc: "Each night needs one waking-night plus one sleepover; never two N.", immovable: true },
    { key: "no_n_to_d",            name: "No N → D back-to-back",                desc: "Staff cannot work a day shift the morning after a waking night.", immovable: true },
    { key: "no_dstar_to_dstar",    name: "No D* → D* back-to-back",              desc: "Sleepover-day shifts cannot be consecutive.", immovable: true },
    { key: "no_sleepover_before_leave", name: "No sleepover before AL / training", desc: "A D* or * sleeps until ~08:00 the next day, so staff cannot start annual leave or training straight after a sleepover.", immovable: true },
    { key: "senior_weekend_cover", name: "Senior on every weekend", desc: "Each Saturday and Sunday must have at least one of L.M. (Deputy) or L.D. (Senior Care Support) on a D or D*. Rotation preference set in /settings.", immovable: true },
    { key: "avoid_pair_seniors", name: "Avoid pairing L.M. and L.D. on the same shift", desc: "Manager prefers to split L.M. and L.D. so each pairs with other staff. Penalty when both are on day cover the same date." },
    { key: "min_sleepover_per_week_for_seniors", name: "Senior / day staff minimum sleepovers per week", desc: "Listed staff should work ≥ N D* shifts each week (unless on AL/TRN that week). Manager can remove staff from the list or toggle to Hard for strict enforcement.", hasParams: true },
    { key: "max_one_per_role_on_al", name: "Max 1 staff per role on AL same date", desc: "Two staff sharing the same role (e.g. two Flexi or two Night Support) cannot be on annual leave on the same date. Enforced at the leave-creation endpoint. Single-occupant roles unaffected.", immovable: true },
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
    const [staff, setStaff] = useState([]);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        Promise.all([
            api.get("/rules"),
            api.get("/staff"),
        ]).then(([rulesRes, staffRes]) => {
            setConfig(rulesRes.data);
            setStaff(staffRes.data);
        }).catch((e) => toast.error(formatApiError(e)));
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
                                </div>
                            )}

                            {/* Params editor — visible whenever the rule is active (Soft or Hard) and has params */}
                            {rd.hasParams && r.mode !== "off" && !immovable && (
                                <div className="mt-4 pt-4 border-t" style={{ borderColor: "hsl(var(--border))" }}>
                                    {rd.key === "overtime_prefer_flexi" && (
                                        <OvertimeParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key === "min_sleepover_per_week_for_seniors" && (
                                        <MinSleepoverParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key !== "overtime_prefer_flexi" && rd.key !== "min_sleepover_per_week_for_seniors" && (
                                        <div className="grid grid-cols-2 gap-3" data-testid={`rule-${rd.key}-params`}>
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

/**
 * Overtime preference params editor.
 *
 * The rule auto-detects flexi staff by role name (default "Flexi") so when
 * staff are added or have their role updated the rule "follows them" without
 * needing to manually edit initials. An optional override list is also
 * supported — leaving it empty means "use auto-detect".
 */
function OvertimeParams({ params, staff, setParam }) {
    const role = params.applies_to_role || "Flexi";
    const override = Array.isArray(params.staff_initials_override) ? params.staff_initials_override : [];
    const cap = params.weekly_cap ?? 48;

    const roles = useMemo(() => {
        const set = new Set();
        for (const s of staff) if (s.role) set.add(s.role);
        if (!set.has(role)) set.add(role);
        return Array.from(set).sort();
    }, [staff, role]);

    const autoDetected = useMemo(
        () => staff.filter((s) => s.active !== false && s.role === role).map((s) => s.initials),
        [staff, role],
    );

    const effective = override.length > 0 ? override : autoDetected;

    const toggleOverride = (initials, checked) => {
        const next = new Set(override);
        if (checked) next.add(initials); else next.delete(initials);
        setParam("staff_initials_override", Array.from(next));
    };

    return (
        <div className="mt-4 space-y-4" data-testid="rule-overtime_prefer_flexi-params">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                    <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">
                        Auto-detect by role
                    </label>
                    <Select value={role} onValueChange={(v) => setParam("applies_to_role", v)}>
                        <SelectTrigger data-testid="rule-overtime_prefer_flexi-role">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {roles.map((r) => (
                                <SelectItem key={r} value={r}>{r}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div>
                    <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">
                        Weekly cap (hours)
                    </label>
                    <input
                        type="number"
                        min={0}
                        max={80}
                        className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                        style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                        value={cap}
                        onChange={(e) => setParam("weekly_cap", Number(e.target.value))}
                        data-testid="rule-overtime_prefer_flexi-param-cap"
                    />
                </div>
            </div>

            <div className="rounded-md p-3 text-xs flex items-start gap-2"
                 style={{ background: "hsl(var(--bg-elev))", border: "1px solid hsl(var(--border))" }}
                 data-testid="rule-overtime_prefer_flexi-effective">
                <UsersIcon className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <div>
                    <span className="uppercase tracking-wider text-muted-foreground mr-1">Currently rewarding overtime to:</span>
                    {effective.length > 0
                        ? effective.map((i) => (
                            <Badge key={i} variant="outline" className="mr-1 text-[10px]" data-testid={`overtime-effective-${i}`}>{i}</Badge>
                        ))
                        : <span className="text-muted-foreground">— nobody (no staff matches role &amp; no override set)</span>}
                    <div className="text-muted-foreground mt-1">
                        {override.length > 0
                            ? "Using manual override list (below). Uncheck all to fall back to auto-detect."
                            : `Auto-detected from role "${role}". Tick boxes below to override.`}
                    </div>
                </div>
            </div>

            <div>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                    Override staff (optional)
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {staff.filter((s) => s.active !== false).map((s) => (
                        <label
                            key={s.initials}
                            className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                            style={{ background: "hsl(var(--bg-elev))" }}
                            data-testid={`overtime-override-${s.initials}`}
                        >
                            <Checkbox
                                checked={override.includes(s.initials)}
                                onCheckedChange={(c) => toggleOverride(s.initials, !!c)}
                            />
                            <span className="font-mono text-xs">{s.initials}</span>
                            <span className="text-muted-foreground text-xs truncate">{s.role || "—"}</span>
                        </label>
                    ))}
                </div>
            </div>
        </div>
    );
}

/**
 * MinSleepoverParams — editor for `min_sleepover_per_week_for_seniors`.
 * - Multi-select checkbox grid of active staff (default L.M./L.D./T.D.).
 * - Number input for the minimum D* per week (default 1).
 */
function MinSleepoverParams({ params, staff, setParam }) {
    const selected = Array.isArray(params.staff_initials)
        ? params.staff_initials
        : ["L.M.", "L.D.", "T.D."];
    const minPerWeek = params.min_sleepovers_per_week ?? 1;

    const activeStaff = staff.filter((s) => s.active !== false);

    const toggleStaff = (initials, checked) => {
        const next = new Set(selected);
        if (checked) next.add(initials); else next.delete(initials);
        setParam("staff_initials", Array.from(next));
    };

    return (
        <div className="space-y-4" data-testid="rule-min_sleepover_per_week_for_seniors-params">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                    <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">
                        Minimum D* per week
                    </label>
                    <input
                        type="number"
                        min={0}
                        max={7}
                        className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                        style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                        value={minPerWeek}
                        onChange={(e) => setParam("min_sleepovers_per_week", Math.max(0, Number(e.target.value) || 0))}
                        data-testid="rule-min_sleepover_per_week_for_seniors-param-min"
                    />
                </div>
            </div>

            <div>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                    Staff required to meet this minimum
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {activeStaff.map((s) => (
                        <label
                            key={s.initials}
                            className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                            style={{ background: "hsl(var(--bg-elev))" }}
                            data-testid={`min-sleepover-staff-${s.initials}`}
                        >
                            <Checkbox
                                checked={selected.includes(s.initials)}
                                onCheckedChange={(c) => toggleStaff(s.initials, !!c)}
                            />
                            <span className="font-mono text-xs">{s.initials}</span>
                            <span className="text-muted-foreground text-xs truncate">{s.role || "—"}</span>
                        </label>
                    ))}
                </div>
                {selected.length === 0 && (
                    <div className="text-xs text-muted-foreground mt-2" data-testid="min-sleepover-empty-warning">
                        No staff selected — rule has no effect.
                    </div>
                )}
            </div>
        </div>
    );
}

