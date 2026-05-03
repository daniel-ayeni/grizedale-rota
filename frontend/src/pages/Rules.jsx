import { useEffect, useMemo, useState } from "react";
import { Lock, Unlock, Save, Users as UsersIcon, Trash2, RotateCcw, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
    Tabs, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
    AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

const RULE_DEFS = [
    { key: "day_cover",            name: "Day cover: 2 staff (2D or D+D*)",      desc: "Each calendar day must have exactly two day-shift staff.", immovable: true },
    { key: "night_cover",          name: "Night cover: D*+N or *+N (never 2N)",  desc: "Each night needs one waking-night plus one sleepover; never two N.", immovable: true },
    { key: "no_n_to_d",            name: "No N → D back-to-back",                desc: "Staff cannot work a day shift the morning after a waking night.", immovable: true },
    { key: "no_dstar_to_dstar",    name: "No D* → D* back-to-back",              desc: "Sleepover-day shifts cannot be consecutive.", immovable: true },
    { key: "no_sleepover_before_leave", name: "No sleepover before AL / training", desc: "A D* or * sleeps until ~08:00 the next day, so staff cannot start annual leave or training straight after a sleepover.", immovable: true },
    { key: "senior_weekend_cover", name: "Senior on every weekend", desc: "Each Saturday and Sunday must have at least one staff flagged `is_senior` or `is_deputy` on a D or D*. Rotation across all eligible seniors (auto-includes any staff you promote to Senior) is set in /settings.", immovable: true },
    { key: "avoid_pair_seniors", name: "Avoid pairing first two seniors (legacy)", desc: "DEPRECATED — use `Avoid listed staff pairs` below for multi-pair configurations. Keep this off to prevent double-counting when the new rule is configured." },
    { key: "avoid_staff_pairs", name: "Avoid listed staff pairs on day cover", desc: "Manager-configured list of staff PAIRS that should not share day cover (D or D*). Add multiple pairs, each with its own weight. Promote / demote / hire staff without touching the pairs.", hasParams: true },
    { key: "weekend_off_per_rota", name: "Every staff gets ≥1 full weekend off per rota", desc: "Penalty when a staff has NO full (Sat+Sun) weekend OFF / AL / TRN across the rota. Ensures nobody is on shift every single weekend of the 4-week cycle. Staff on AL for the entire rota are exempt." },
    { key: "min_sleepover_per_week_for_seniors", name: "Senior / day staff minimum sleepovers per week", desc: "Listed staff should work ≥ N D* shifts each week (unless on AL/TRN that week). Manager can remove staff from the list or toggle to Hard for strict enforcement.", hasParams: true },
    { key: "max_one_per_role_on_al", name: "Max 1 staff per role on AL same date", desc: "Two staff sharing the same role (e.g. two Flexi or two Night Support) cannot be on annual leave on the same date. Enforced at the leave-creation endpoint. Single-occupant roles unaffected.", immovable: true },
    { key: "senior_monday_cover", name: "Senior on every Monday", desc: "Each Monday should have at least one of the listed staff (default L.M., L.D.) on a working shift. Soft default with strong weight 60 — flip to Hard for strict enforcement.", hasParams: true },
    { key: "respect_shift_preference", name: "Respect each staff's day/night preference", desc: "Dual-capable staff (can do both day and night) can express a preference on the Staff page. The solver nudges them toward their preferred shift while still using them for the other when needed." },
    { key: "avoid_star_then_night", name: "Avoid `*` followed by `N`", desc: "After a sleepover-only (*) the staff has slept at the home; going straight into a waking night the next day is undesirable. Penalises each (*, N) consecutive pair." },
    { key: "avoid_star_then_day", name: "Avoid `*` followed by `D`", desc: "After `*` the staff is leaving at 8am and a D the same morning cuts into rest. Per-staff overrides allow stronger weights for individuals who especially dislike this pattern (e.g. L.D. → 60).", hasParams: true },
    { key: "avoid_star_for_staff", name: "Avoid `*` for specific staff", desc: "Listed staff dislike bare `*` (sleepover-only, no day shift). They're fine with D or D* but `*` alone is unwanted. Soft penalty per `*` assigned.", hasParams: true },
    { key: "max_sleepover_per_week", name: "Maximum D* per week (cap)", desc: "Per-staff cap on D* count per week. Useful for staff who only want one sleepover-day each week (e.g. T.D. → max 1).", hasParams: true },
    { key: "fair_star_distribution", name: "Fair distribution of `*` shifts", desc: "Spread `*` (sleepover-only) across eligible staff (auto-detected: those with can_do_sleepover=true and not in avoid_star_for_staff). Penalises uneven distribution." },
    { key: "weekday_weekend_split", name: "Weekday / weekend split per week", desc: "Per-staff target count of shift types on weekdays vs weekends each week (e.g. J.R.: 1 weekday N + 1 weekend N). Auto-skips a sub-window when 0 days are available (AL/TRN cover the whole sub-window).", hasParams: true },
    { key: "pair_companion_on_day", name: "Pair a focal staff with a companion on a specific weekday", desc: "If a focal staff (e.g. C.E.) works a day shift on the configured weekday (e.g. Wed), at least one of the listed companions (e.g. L.M., L.D., D.A.) must also be working a day shift that same day. Auto-skips when the focal is on AL/TRN or all companions are on AL/TRN.", hasParams: true },
    { key: "med_competent_required", name: "Medication-competent on every shift", desc: "Every day shift and every night shift includes ≥1 medication-competent staff." },
    { key: "first_aider_required",   name: "First-aider on every shift",          desc: "Every day shift and every night shift includes ≥1 first-aider." },
    { key: "no_male_pair_alone",     name: "Male staff cannot be alone together", desc: "If any male staff is on a shift, at least one female must be on the same shift." },
    { key: "manager_no_shifts",      name: "Manager / admin-only staff do not work shifts", desc: "Staff flagged `is_manager` or `is_admin_only` are excluded from rota shifts unless explicitly locked. Promote any staff to Manager on /staff and this rule applies to them automatically." },
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

// Rules whose UNLOCK gesture must be confirmed via a warning dialog —
// the manager is acknowledging they're freeing a safety / cover rule
// from accidental edits. All other immovable rules unlock with a plain
// toggle. Locked status itself is just UI freeze; solver behaviour is
// driven by mode (hard/soft/off) regardless of lock state.
const SAFETY_RULES = new Set([
    "day_cover",
    "night_cover",
    "no_n_to_d",
    "no_dstar_to_dstar",
    "manager_no_shifts",
    "max_one_per_role_on_al",
    "no_sleepover_before_leave",
]);

export default function Rules() {
    const [config, setConfig] = useState(null);
    const [staff, setStaff] = useState([]);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    // Holds the rule_def for the safety-unlock warning dialog (or null).
    const [unlockTarget, setUnlockTarget] = useState(null);
    const [unlockAck, setUnlockAck] = useState(false);

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
    /** Persist the manager's lock/unlock decision per rule. UI freezes
     *  Hard/Soft/Off + weight + params editor when locked; solver
     *  behaviour is unaffected (it runs whatever mode is currently set).
     */
    const setImmovable = (key, locked) => {
        setConfig((c) => ({
            ...c,
            rules: { ...c.rules, [key]: { ...c.rules[key], immovable: !!locked } },
        }));
        setDirty(true);
    };
    /** Lock/unlock click handler. Calls into setImmovable directly for
     *  non-safety rules; for safety rules going UNLOCKED → opens the
     *  warning dialog. Lock direction (already-locked → locked again
     *  shouldn't happen, but locking from unlocked is always one-click).
     */
    const handleLockToggle = (rd, currentlyLocked) => {
        if (currentlyLocked && SAFETY_RULES.has(rd.key)) {
            // Going from locked → unlocked on a safety rule. Confirm.
            setUnlockAck(false);
            setUnlockTarget(rd);
            return;
        }
        setImmovable(rd.key, !currentlyLocked);
    };
    const confirmUnlock = () => {
        if (unlockTarget) {
            setImmovable(unlockTarget.key, false);
        }
        setUnlockTarget(null);
        setUnlockAck(false);
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

    const resetToDefaults = async () => {
        try {
            const { data } = await api.post("/rules/reset");
            setConfig(data);
            setDirty(false);
            toast.success("Rules reset to defaults");
        } catch (err) {
            toast.error(formatApiError(err));
        }
    };

    return (
        <div className="space-y-6" data-testid="rules-page">
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h1 className="display text-3xl font-semibold">Rules</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Toggle each rule between Hard, Soft (with weight) and Off.
                        Locked rules are immovable cover requirements.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <AlertDialog>
                        <AlertDialogTrigger asChild>
                            <Button variant="outline" size="sm" data-testid="rules-reset-button">
                                <RotateCcw className="w-3.5 h-3.5 mr-1.5" /> Reset to defaults
                            </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent data-testid="rules-reset-confirm">
                            <AlertDialogHeader>
                                <AlertDialogTitle>Reset all rules to defaults?</AlertDialogTitle>
                                <AlertDialogDescription>
                                    Every rule's mode (hard / soft / off), weight and per-row
                                    parameters will be reverted to the seed defaults. Staff,
                                    leave and rotas are not affected.
                                </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                                <AlertDialogCancel data-testid="rules-reset-cancel">Cancel</AlertDialogCancel>
                                <AlertDialogAction onClick={resetToDefaults} data-testid="rules-reset-confirm-btn">
                                    Reset
                                </AlertDialogAction>
                            </AlertDialogFooter>
                        </AlertDialogContent>
                    </AlertDialog>
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
            </div>

            <div className="section-header" data-testid="rules-section-header">Constraint Engine</div>

            <div className="grid grid-cols-1 gap-3" data-testid="rules-list">
                {RULE_DEFS.map((rd) => {
                    const r = config.rules[rd.key] || { mode: "off", weight: 0 };
                    // Manager's lock decision wins. If they've never set
                    // immovable on this rule, fall back to the spec
                    // default (rd.immovable). Hidden flag = unlocked
                    // (so a freshly-saved rule with immovable:false
                    // remains editable on reload).
                    const immovable = (r.immovable !== undefined) ? !!r.immovable : !!rd.immovable;
                    const isSafety = SAFETY_RULES.has(rd.key);
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
                                        {isSafety && (
                                            <Badge variant="outline" className="text-[10px] uppercase tracking-wider" style={{ borderColor: "hsl(var(--accent-red) / 0.5)", color: "hsl(var(--accent-red))" }} title="Unlocking requires manager confirmation — controls scheduling safety">
                                                <AlertTriangle className="w-3 h-3 mr-1" /> Safety
                                            </Badge>
                                        )}
                                    </div>
                                    <div className="text-sm text-muted-foreground mt-1">{rd.desc}</div>
                                </div>

                                <div className="flex items-start gap-3 shrink-0">
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
                                    {/* Lock toggle — always interactive. Flips immovable
                                        flag; safety-rule unlocks open the confirm dialog. */}
                                    <button
                                        type="button"
                                        onClick={() => handleLockToggle(rd, immovable)}
                                        className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider px-2 py-1.5 rounded-md border focus-ring transition-colors"
                                        style={{
                                            background: immovable ? "hsl(var(--bg-elev))" : "transparent",
                                            color: immovable ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))",
                                            borderColor: immovable ? "hsl(var(--border-strong))" : "hsl(var(--border))",
                                        }}
                                        data-testid={`rule-${rd.key}-lock-toggle`}
                                        data-locked={immovable ? "true" : "false"}
                                        title={immovable ? "Click to unlock and edit this rule" : "Click to lock this rule from edits"}
                                    >
                                        {immovable
                                            ? <><Lock className="w-3.5 h-3.5" /> Locked</>
                                            : <><Unlock className="w-3.5 h-3.5" /> Unlocked</>}
                                    </button>
                                </div>
                            </div>

                            {/* Frozen-state hint — shown only when the rule is locked
                                so the manager understands why the controls are disabled. */}
                            {immovable && (
                                <div className="mt-3 text-xs italic text-muted-foreground" data-testid={`rule-${rd.key}-locked-hint`}>
                                    This rule is locked. Click <strong>Locked</strong> above to unlock and edit.
                                </div>
                            )}

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
                                    {rd.key === "senior_monday_cover" && (
                                        <SeniorMondayParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key === "avoid_star_then_day" && (
                                        <AvoidStarThenDayParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key === "avoid_star_for_staff" && (
                                        <StaffListParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                            defaultList={["L.M.", "L.D.", "T.D."]}
                                            label="Staff who dislike bare `*`"
                                            testid="rule-avoid_star_for_staff-params"
                                        />
                                    )}
                                    {rd.key === "max_sleepover_per_week" && (
                                        <MaxSleepoverParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key === "weekday_weekend_split" && (
                                        <WeekdayWeekendSplitParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key === "pair_companion_on_day" && (
                                        <PairCompanionParams
                                            params={r.params || {}}
                                            staff={staff}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key === "avoid_staff_pairs" && (
                                        <AvoidStaffPairsParams
                                            params={r.params || {}}
                                            staff={staff}
                                            defaultWeight={r.weight ?? 40}
                                            setParam={(k, v) => setParam(rd.key, k, v)}
                                        />
                                    )}
                                    {rd.key !== "overtime_prefer_flexi" && rd.key !== "min_sleepover_per_week_for_seniors" && rd.key !== "senior_monday_cover" && rd.key !== "avoid_star_then_day" && rd.key !== "avoid_star_for_staff" && rd.key !== "max_sleepover_per_week" && rd.key !== "weekday_weekend_split" && rd.key !== "pair_companion_on_day" && rd.key !== "avoid_staff_pairs" && (
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

            {/* Safety-rule unlock confirmation. Asks the manager to ack
                the risk of unfreezing a scheduling-safety rule before
                exposing the Hard / Soft / Off + weight + params editor. */}
            <AlertDialog open={!!unlockTarget} onOpenChange={(v) => { if (!v) { setUnlockTarget(null); setUnlockAck(false); } }}>
                <AlertDialogContent data-testid="unlock-safety-dialog">
                    <AlertDialogHeader>
                        <AlertDialogTitle className="flex items-center gap-2">
                            <AlertTriangle className="w-5 h-5 text-destructive" />
                            Unlock safety rule?
                        </AlertDialogTitle>
                        <AlertDialogDescription asChild>
                            <div className="space-y-3 text-sm">
                                <div>
                                    Unlocking <strong>{unlockTarget?.name}</strong> allows you to change a safety
                                    rule. The system uses this to prevent unsafe scheduling. Are you sure you want
                                    to unlock?
                                </div>
                                <label className="flex items-start gap-2 cursor-pointer" onClick={(e) => e.stopPropagation()}>
                                    <Checkbox
                                        id="unlock-ack"
                                        checked={unlockAck}
                                        onCheckedChange={(v) => setUnlockAck(!!v)}
                                        data-testid="unlock-ack"
                                    />
                                    <span className="text-xs leading-4">I understand the risk of editing this rule.</span>
                                </label>
                            </div>
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="unlock-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={confirmUnlock}
                            disabled={!unlockAck}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            data-testid="unlock-confirm"
                        >
                            Unlock
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
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

    // Effective list = override (if set) intersected with accepts_overtime,
    // else autoDetected intersected with accepts_overtime.
    const acceptingByInit = useMemo(() => {
        const m = new Map();
        for (const s of staff) m.set(s.initials, !!s.accepts_overtime);
        return m;
    }, [staff]);

    const candidates = override.length > 0 ? override : autoDetected;
    const effective = candidates.filter((i) => acceptingByInit.get(i));
    const optedOut = candidates.filter((i) => !acceptingByInit.get(i));

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
                        : <span className="text-muted-foreground">— nobody (no staff matches role &amp; accepts overtime)</span>}
                    {optedOut.length > 0 && (
                        <span className="ml-2">
                            <span className="uppercase tracking-wider text-muted-foreground mr-1">Opted out:</span>
                            {optedOut.map((i) => (
                                <Badge key={i} variant="outline" className="mr-1 text-[10px] opacity-60 line-through"
                                       title="Staff has accepts_overtime=false on the Staff page"
                                       data-testid={`overtime-optedout-${i}`}>{i}</Badge>
                            ))}
                        </span>
                    )}
                    <div className="text-muted-foreground mt-1">
                        {override.length > 0
                            ? "Using manual override list (below). Uncheck all to fall back to auto-detect."
                            : `Auto-detected from role "${role}" + accepts_overtime=true. Tick boxes below to override.`}
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



/**
 * SeniorMondayParams — editor for `senior_monday_cover`.
 * Multi-select staff list (default L.M., L.D.).
 */
function SeniorMondayParams({ params, staff, setParam }) {
    const selected = Array.isArray(params.staff_initials)
        ? params.staff_initials
        : ["L.M.", "L.D."];
    const activeStaff = staff.filter((s) => s.active !== false);

    const toggleStaff = (initials, checked) => {
        const next = new Set(selected);
        if (checked) next.add(initials); else next.delete(initials);
        setParam("staff_initials", Array.from(next));
    };

    return (
        <div className="space-y-3" data-testid="rule-senior_monday_cover-params">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
                Senior staff that should cover Mondays
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {activeStaff.map((s) => (
                    <label
                        key={s.initials}
                        className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                        style={{ background: "hsl(var(--bg-elev))" }}
                        data-testid={`monday-cover-${s.initials}`}
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
                <div className="text-xs text-muted-foreground">No staff selected — rule has no effect.</div>
            )}
        </div>
    );
}

/**
 * AvoidStarThenDayParams — editor for `avoid_star_then_day`.
 * General-weight slider + per-staff override grid where each entry is
 * (staff initials, override weight). Default override: L.D. → 60.
 */
function AvoidStarThenDayParams({ params, staff, setParam }) {
    const generalWeight = params.general_weight ?? 20;
    const overrides = params.staff_overrides || { "L.D.": 60, "L.M.": 60 };
    const activeStaff = staff.filter((s) => s.active !== false);

    const setOverride = (initials, val) => {
        const next = { ...overrides };
        if (val == null || val === "") delete next[initials];
        else next[initials] = Math.max(0, Math.min(200, Number(val) || 0));
        setParam("staff_overrides", next);
    };

    return (
        <div className="space-y-4" data-testid="rule-avoid_star_then_day-params">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                    <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">
                        General penalty weight
                    </label>
                    <input
                        type="number"
                        min={0}
                        max={200}
                        className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                        style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                        value={generalWeight}
                        onChange={(e) => setParam("general_weight", Math.max(0, Number(e.target.value) || 0))}
                        data-testid="rule-avoid_star_then_day-param-general"
                    />
                </div>
            </div>
            <div>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                    Per-staff override weights (leave blank to use general weight)
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {activeStaff.map((s) => {
                        const cur = overrides[s.initials];
                        return (
                            <div
                                key={s.initials}
                                className="flex items-center gap-2 text-sm px-2 py-1.5 rounded"
                                style={{ background: "hsl(var(--bg-elev))" }}
                                data-testid={`avoid-star-then-day-${s.initials}`}
                            >
                                <span className="font-mono text-xs w-10 shrink-0">{s.initials}</span>
                                <input
                                    type="number"
                                    placeholder={`${generalWeight}`}
                                    className="w-16 text-sm px-1.5 py-1 rounded border"
                                    style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg))" }}
                                    value={cur ?? ""}
                                    onChange={(e) => setOverride(s.initials, e.target.value)}
                                />
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}


/**
 * Generic multi-select staff picker for rules with a single `staff_initials` array param.
 */
function StaffListParams({ params, staff, setParam, defaultList, label, testid }) {
    const selected = Array.isArray(params.staff_initials) ? params.staff_initials : defaultList;
    const activeStaff = staff.filter((s) => s.active !== false);
    const toggleStaff = (initials, checked) => {
        const next = new Set(selected);
        if (checked) next.add(initials); else next.delete(initials);
        setParam("staff_initials", Array.from(next));
    };
    return (
        <div className="space-y-3" data-testid={testid}>
            <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {activeStaff.map((s) => (
                    <label
                        key={s.initials}
                        className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                        style={{ background: "hsl(var(--bg-elev))" }}
                        data-testid={`${testid}-${s.initials}`}
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
        </div>
    );
}

/**
 * RowDeleteButton — small trash icon with a 2-step inline confirm.
 * Used by every multi-row rule editor below to ensure managers don't
 * lose a rule row by mis-clicking. First click flips the icon to a
 * confirm pill; second click within 3s actually deletes (after which
 * the parent re-renders without the row).
 */
function RowDeleteButton({ onConfirm, testid, title = "Remove row" }) {
    const [armed, setArmed] = useState(false);
    useEffect(() => {
        if (!armed) return;
        const t = setTimeout(() => setArmed(false), 3000);
        return () => clearTimeout(t);
    }, [armed]);
    if (armed) {
        return (
            <button
                type="button"
                onClick={onConfirm}
                className="text-xs px-2 py-1 rounded bg-destructive text-destructive-foreground font-semibold flex items-center gap-1"
                data-testid={`${testid}-confirm`}
            >
                <Trash2 className="w-3 h-3" /> Confirm delete?
            </button>
        );
    }
    return (
        <button
            type="button"
            onClick={() => setArmed(true)}
            className="p-1.5 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            title={title}
            aria-label={title}
            data-testid={testid}
        >
            <Trash2 className="w-3.5 h-3.5" />
        </button>
    );
}


/**
 * MaxSleepoverParams — editor for `max_sleepover_per_week`.
 * Renders a list of (staff_initials, max_per_week) entries, where each
 * entry caps the number of D* shifts per week for the listed staff.
 */
function MaxSleepoverParams({ params, staff, setParam }) {
    const rules = Array.isArray(params.rules) ? params.rules : [{ staff_initials: ["T.D."], max_per_week: 1 }];
    const activeStaff = staff.filter((s) => s.active !== false);

    const updateRule = (idx, updater) => {
        const next = rules.map((r, i) => (i === idx ? updater(r) : r));
        setParam("rules", next);
    };
    const addRule = () => {
        setParam("rules", [...rules, { staff_initials: [], max_per_week: 2 }]);
    };
    const removeRule = (idx) => {
        setParam("rules", rules.filter((_, i) => i !== idx));
    };

    return (
        <div className="space-y-3" data-testid="rule-max_sleepover_per_week-params">
            {rules.map((r, idx) => {
                const selected = Array.isArray(r.staff_initials) ? r.staff_initials : [];
                const cap = r.max_per_week ?? 1;
                return (
                    <div
                        key={idx}
                        className="rounded-md p-3 space-y-2"
                        style={{ background: "hsl(var(--bg-elev))", border: "1px solid hsl(var(--border))" }}
                        data-testid={`rule-max_sleepover_per_week-row-${idx}`}
                    >
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs uppercase tracking-wider text-muted-foreground">Cap rule {idx + 1}</span>
                            <div className="flex items-center gap-2">
                                <label className="text-xs text-muted-foreground">Max D* / week</label>
                                <input
                                    type="number"
                                    min={0}
                                    max={7}
                                    value={cap}
                                    onChange={(e) => updateRule(idx, (cur) => ({
                                        ...cur,
                                        max_per_week: Math.max(0, Number(e.target.value) || 0),
                                    }))}
                                    className="w-16 text-sm px-1.5 py-1 rounded border"
                                    style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg))" }}
                                    data-testid={`rule-max_sleepover_per_week-row-${idx}-cap`}
                                />
                                <button
                                    type="button"
                                    onClick={() => removeRule(idx)}
                                    className="text-xs px-2 py-1 rounded text-muted-foreground hover:text-foreground"
                                    title="Remove rule"
                                    data-testid={`rule-max_sleepover_per_week-row-${idx}-remove-old`}
                                    style={{ display: "none" }}
                                >
                                    ✕
                                </button>
                                <RowDeleteButton
                                    onConfirm={() => removeRule(idx)}
                                    testid={`rule-max_sleepover_per_week-row-${idx}-remove`}
                                    title="Remove cap rule"
                                />
                            </div>
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            {activeStaff.map((s) => (
                                <label
                                    key={s.initials}
                                    className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                                    style={{ background: "hsl(var(--bg))" }}
                                >
                                    <Checkbox
                                        checked={selected.includes(s.initials)}
                                        onCheckedChange={(checked) => updateRule(idx, (cur) => {
                                            const next = new Set(Array.isArray(cur.staff_initials) ? cur.staff_initials : []);
                                            if (checked) next.add(s.initials); else next.delete(s.initials);
                                            return { ...cur, staff_initials: Array.from(next) };
                                        })}
                                    />
                                    <span className="font-mono text-xs">{s.initials}</span>
                                </label>
                            ))}
                        </div>
                    </div>
                );
            })}
            <button
                type="button"
                onClick={addRule}
                className="text-xs px-3 py-1.5 rounded border"
                style={{ borderColor: "hsl(var(--border-strong))" }}
                data-testid="rule-max_sleepover_per_week-add"
            >
                + Add cap rule
            </button>
        </div>
    );
}


/**
 * WeekdayWeekendSplitParams — editor for `weekday_weekend_split`.
 * Each row: staff_initials list, weekday_target, weekend_target, shift_types.
 */
function WeekdayWeekendSplitParams({ params, staff, setParam }) {
    const rules = Array.isArray(params.rules)
        ? params.rules
        : [{ staff_initials: ["J.R."], weekday_target: 1, weekend_target: 1, shift_types: ["N"] }];
    const activeStaff = staff.filter((s) => s.active !== false);
    const SHIFT_OPTIONS = ["D", "D*", "N", "*"];

    const updateRule = (idx, updater) => {
        setParam("rules", rules.map((r, i) => (i === idx ? updater(r) : r)));
    };
    const addRule = () => {
        setParam("rules", [...rules, { staff_initials: [], weekday_target: 1, weekend_target: 1, shift_types: ["N"] }]);
    };
    const removeRule = (idx) => {
        setParam("rules", rules.filter((_, i) => i !== idx));
    };

    return (
        <div className="space-y-3" data-testid="rule-weekday_weekend_split-params">
            {rules.map((r, idx) => {
                const inits = Array.isArray(r.staff_initials)
                    ? r.staff_initials
                    : (r.staff_initials ? [r.staff_initials] : []);
                const types = Array.isArray(r.shift_types) ? r.shift_types : ["N"];
                return (
                    <div
                        key={idx}
                        className="rounded-md p-3 space-y-2"
                        style={{ background: "hsl(var(--bg-elev))", border: "1px solid hsl(var(--border))" }}
                        data-testid={`rule-weekday_weekend_split-row-${idx}`}
                    >
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                            <span className="text-xs uppercase tracking-wider text-muted-foreground">Split rule {idx + 1}</span>
                            <div className="flex items-center gap-3 flex-wrap">
                                <label className="text-xs text-muted-foreground flex items-center gap-1.5">
                                    Weekday target
                                    <input
                                        type="number"
                                        min={0} max={7}
                                        value={r.weekday_target ?? 1}
                                        onChange={(e) => updateRule(idx, (cur) => ({
                                            ...cur,
                                            weekday_target: Math.max(0, Number(e.target.value) || 0),
                                        }))}
                                        className="w-14 text-sm px-1.5 py-1 rounded border"
                                        style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg))" }}
                                    />
                                </label>
                                <label className="text-xs text-muted-foreground flex items-center gap-1.5">
                                    Weekend target
                                    <input
                                        type="number"
                                        min={0} max={2}
                                        value={r.weekend_target ?? 1}
                                        onChange={(e) => updateRule(idx, (cur) => ({
                                            ...cur,
                                            weekend_target: Math.max(0, Number(e.target.value) || 0),
                                        }))}
                                        className="w-14 text-sm px-1.5 py-1 rounded border"
                                        style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg))" }}
                                    />
                                </label>
                                <RowDeleteButton
                                    onConfirm={() => removeRule(idx)}
                                    testid={`rule-weekday_weekend_split-row-${idx}-remove`}
                                    title="Remove split rule"
                                />
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-muted-foreground mb-1">Staff</div>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                {activeStaff.map((s) => (
                                    <label
                                        key={s.initials}
                                        className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                                        style={{ background: "hsl(var(--bg))" }}
                                    >
                                        <Checkbox
                                            checked={inits.includes(s.initials)}
                                            onCheckedChange={(checked) => updateRule(idx, (cur) => {
                                                const cur_arr = Array.isArray(cur.staff_initials)
                                                    ? cur.staff_initials
                                                    : (cur.staff_initials ? [cur.staff_initials] : []);
                                                const next = new Set(cur_arr);
                                                if (checked) next.add(s.initials); else next.delete(s.initials);
                                                return { ...cur, staff_initials: Array.from(next) };
                                            })}
                                        />
                                        <span className="font-mono text-xs">{s.initials}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-muted-foreground mb-1">Shift types</div>
                            <div className="flex flex-wrap gap-2">
                                {SHIFT_OPTIONS.map((opt) => (
                                    <label
                                        key={opt}
                                        className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                                        style={{ background: "hsl(var(--bg))" }}
                                    >
                                        <Checkbox
                                            checked={types.includes(opt)}
                                            onCheckedChange={(checked) => updateRule(idx, (cur) => {
                                                const cur_arr = Array.isArray(cur.shift_types) ? cur.shift_types : [];
                                                const next = new Set(cur_arr);
                                                if (checked) next.add(opt); else next.delete(opt);
                                                return { ...cur, shift_types: Array.from(next) };
                                            })}
                                        />
                                        <span className="font-mono text-xs">{opt}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    </div>
                );
            })}
            <button
                type="button"
                onClick={addRule}
                className="text-xs px-3 py-1.5 rounded border"
                style={{ borderColor: "hsl(var(--border-strong))" }}
            >
                + Add split rule
            </button>
        </div>
    );
}



/**
 * PairCompanionParams — editor for `pair_companion_on_day`.
 * Each row: focal staff + day_of_week (Mon..Sun) + companion_initials list +
 * shift_types list. Useful for "C.E. on Wed must pair with L.M./L.D./D.A.".
 */
const DOW_OPTIONS = [
    { value: "Mon", label: "Mon" },
    { value: "Tue", label: "Tue" },
    { value: "Wed", label: "Wed" },
    { value: "Thu", label: "Thu" },
    { value: "Fri", label: "Fri" },
    { value: "Sat", label: "Sat" },
    { value: "Sun", label: "Sun" },
];

function PairCompanionParams({ params, staff, setParam }) {
    const rules = Array.isArray(params.rules)
        ? params.rules
        : [{ staff_initials: "C.E.", companion_initials: ["L.M.", "L.D.", "D.A."], day_of_week: "Wed", shift_types: ["D", "D*"] }];
    const activeStaff = staff.filter((s) => s.active !== false);
    const SHIFT_OPTIONS = ["D", "D*", "N", "*"];

    const updateRule = (idx, updater) => {
        setParam("rules", rules.map((r, i) => (i === idx ? updater(r) : r)));
    };
    const addRule = () => {
        setParam("rules", [...rules, {
            staff_initials: "",
            companion_initials: [],
            day_of_week: "Wed",
            shift_types: ["D", "D*"],
        }]);
    };
    const removeRule = (idx) => {
        setParam("rules", rules.filter((_, i) => i !== idx));
    };

    return (
        <div className="space-y-3" data-testid="rule-pair_companion_on_day-params">
            {rules.map((r, idx) => {
                const focal = typeof r.staff_initials === "string"
                    ? r.staff_initials
                    : (Array.isArray(r.staff_initials) && r.staff_initials.length > 0 ? r.staff_initials[0] : "");
                const dow = r.day_of_week || "Wed";
                const companions = Array.isArray(r.companion_initials) ? r.companion_initials : [];
                const types = Array.isArray(r.shift_types) ? r.shift_types : ["D", "D*"];
                return (
                    <div
                        key={idx}
                        className="rounded-md p-3 space-y-3"
                        style={{ background: "hsl(var(--bg-elev))", border: "1px solid hsl(var(--border))" }}
                        data-testid={`rule-pair_companion_on_day-row-${idx}`}
                    >
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                            <span className="text-xs uppercase tracking-wider text-muted-foreground">Companion rule {idx + 1}</span>
                            <RowDeleteButton
                                onConfirm={() => removeRule(idx)}
                                testid={`rule-pair_companion_on_day-row-${idx}-remove`}
                                title="Remove companion rule"
                            />
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div>
                                <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">Focal staff</label>
                                <Select
                                    value={focal}
                                    onValueChange={(v) => updateRule(idx, (cur) => ({ ...cur, staff_initials: v }))}
                                >
                                    <SelectTrigger data-testid={`pco-row-${idx}-focal`}>
                                        <SelectValue placeholder="Pick staff" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {activeStaff.map((s) => (
                                            <SelectItem key={s.initials} value={s.initials}>
                                                {s.initials} — {s.role || ""}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div>
                                <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">Day of week</label>
                                <Select
                                    value={dow}
                                    onValueChange={(v) => updateRule(idx, (cur) => ({ ...cur, day_of_week: v }))}
                                >
                                    <SelectTrigger data-testid={`pco-row-${idx}-dow`}>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {DOW_OPTIONS.map((o) => (
                                            <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                        <div>
                            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Acceptable companions</div>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                {activeStaff
                                    .filter((s) => s.initials !== focal)
                                    .map((s) => (
                                        <label
                                            key={s.initials}
                                            className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                                            style={{ background: "hsl(var(--bg))" }}
                                            data-testid={`pco-row-${idx}-companion-${s.initials}`}
                                        >
                                            <Checkbox
                                                checked={companions.includes(s.initials)}
                                                onCheckedChange={(checked) => updateRule(idx, (cur) => {
                                                    const cur_arr = Array.isArray(cur.companion_initials) ? cur.companion_initials : [];
                                                    const next = new Set(cur_arr);
                                                    if (checked) next.add(s.initials); else next.delete(s.initials);
                                                    return { ...cur, companion_initials: Array.from(next) };
                                                })}
                                            />
                                            <span className="font-mono text-xs">{s.initials}</span>
                                            <span className="text-muted-foreground text-xs truncate">{s.role || "—"}</span>
                                        </label>
                                    ))}
                            </div>
                            {companions.length === 0 && (
                                <div className="text-xs text-muted-foreground mt-1">No companions selected — rule has no effect.</div>
                            )}
                        </div>
                        <div>
                            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Trigger shift types (focal)</div>
                            <div className="flex flex-wrap gap-2">
                                {SHIFT_OPTIONS.map((opt) => (
                                    <label
                                        key={opt}
                                        className="flex items-center gap-2 text-sm px-2 py-1.5 rounded cursor-pointer"
                                        style={{ background: "hsl(var(--bg))" }}
                                    >
                                        <Checkbox
                                            checked={types.includes(opt)}
                                            onCheckedChange={(checked) => updateRule(idx, (cur) => {
                                                const cur_arr = Array.isArray(cur.shift_types) ? cur.shift_types : [];
                                                const next = new Set(cur_arr);
                                                if (checked) next.add(opt); else next.delete(opt);
                                                return { ...cur, shift_types: Array.from(next) };
                                            })}
                                        />
                                        <span className="font-mono text-xs">{opt}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    </div>
                );
            })}
            <button
                type="button"
                onClick={addRule}
                className="text-xs px-3 py-1.5 rounded border"
                style={{ borderColor: "hsl(var(--border-strong))" }}
                data-testid="rule-pair_companion_on_day-add"
            >
                + Add companion rule
            </button>
        </div>
    );
}


/**
 * AvoidStaffPairsParams — editor for `avoid_staff_pairs`. Each row is
 * {staff_a_initials, staff_b_initials, weight}. Manager adds/removes
 * pairs with a single click; solver penalises every day the pair shares
 * day cover. No hardcoded staff — fully driven by /staff and is_senior
 * role flags.
 */
function AvoidStaffPairsParams({ params, staff, setParam, defaultWeight = 40 }) {
    const pairs = Array.isArray(params?.pairs) ? params.pairs : [];
    const activeStaff = staff.filter((s) => s.active).sort((a, b) => a.initials.localeCompare(b.initials));

    const setPair = (idx, patch) => {
        const next = pairs.map((p, i) => (i === idx ? { ...p, ...patch } : p));
        setParam("pairs", next);
    };
    const addPair = () => {
        // Default new pair to the first two seniors (if at least two
        // exist) so the UX mirrors the legacy behaviour.
        const seniors = activeStaff.filter((s) => s.is_senior || s.is_deputy);
        const defaults = seniors.length >= 2
            ? { staff_a_initials: seniors[0].initials, staff_b_initials: seniors[1].initials }
            : { staff_a_initials: activeStaff[0]?.initials || "", staff_b_initials: activeStaff[1]?.initials || "" };
        setParam("pairs", [...pairs, { ...defaults, weight: defaultWeight }]);
    };
    const removePair = (idx) => setParam("pairs", pairs.filter((_, i) => i !== idx));

    return (
        <div className="space-y-3" data-testid="rule-avoid_staff_pairs-params">
            {pairs.length === 0 && (
                <div className="text-xs italic text-muted-foreground">
                    No pairs configured — rule is a no-op. Click <strong>+ Add pair</strong> below to block a combination.
                </div>
            )}
            {pairs.map((p, idx) => (
                <div key={idx} className="flex flex-wrap items-end gap-2" data-testid={`rule-avoid_staff_pairs-pair-${idx}`}>
                    <div className="flex-1 min-w-[140px]">
                        <label className="text-[10px] uppercase tracking-wider text-muted-foreground block mb-1">Staff A</label>
                        <select
                            className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                            style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                            value={p.staff_a_initials || ""}
                            onChange={(e) => setPair(idx, { staff_a_initials: e.target.value })}
                            data-testid={`rule-avoid_staff_pairs-a-${idx}`}
                        >
                            <option value="">—</option>
                            {activeStaff.map((s) => (
                                <option key={s.initials} value={s.initials}>{s.initials} — {s.full_name || s.role}</option>
                            ))}
                        </select>
                    </div>
                    <div className="flex-1 min-w-[140px]">
                        <label className="text-[10px] uppercase tracking-wider text-muted-foreground block mb-1">Staff B</label>
                        <select
                            className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                            style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                            value={p.staff_b_initials || ""}
                            onChange={(e) => setPair(idx, { staff_b_initials: e.target.value })}
                            data-testid={`rule-avoid_staff_pairs-b-${idx}`}
                        >
                            <option value="">—</option>
                            {activeStaff.map((s) => (
                                <option key={s.initials} value={s.initials}>{s.initials} — {s.full_name || s.role}</option>
                            ))}
                        </select>
                    </div>
                    <div className="w-24">
                        <label className="text-[10px] uppercase tracking-wider text-muted-foreground block mb-1">Weight</label>
                        <input
                            type="number"
                            min={1}
                            max={1000}
                            className="w-full text-sm px-2 py-1.5 rounded border focus-ring"
                            style={{ borderColor: "hsl(var(--border-strong))", background: "hsl(var(--bg-elev))" }}
                            value={p.weight ?? defaultWeight}
                            onChange={(e) => setPair(idx, { weight: parseInt(e.target.value, 10) || defaultWeight })}
                            data-testid={`rule-avoid_staff_pairs-w-${idx}`}
                        />
                    </div>
                    <button
                        type="button"
                        onClick={() => removePair(idx)}
                        className="h-9 px-2 text-xs rounded border hover:border-destructive hover:text-destructive transition-colors"
                        style={{ borderColor: "hsl(var(--border-strong))" }}
                        data-testid={`rule-avoid_staff_pairs-remove-${idx}`}
                        title="Remove pair"
                    >
                        ×
                    </button>
                </div>
            ))}
            <button
                type="button"
                onClick={addPair}
                className="text-xs px-3 py-1.5 rounded border"
                style={{ borderColor: "hsl(var(--border-strong))" }}
                data-testid="rule-avoid_staff_pairs-add"
            >
                + Add pair
            </button>
        </div>
    );
}
