import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, AlertOctagon, Calendar, Plus, Trash2, ShieldCheck, AlertTriangle, Info, Sun, Moon, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import axios from "axios";
import { toast } from "sonner";
import { useTheme } from "@/contexts/ThemeContext";
import { Toaster } from "@/components/ui/sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const PREFS = [
    { value: "DEFAULT", label: "Default" },
    { value: "OFF", label: "Off" },
    { value: "AL", label: "Annual Leave" },
    { value: "WANT_N", label: "Want night" },
    { value: "WANT_D", label: "Want day" },
    { value: "AVOID", label: "Avoid" },
];

// Pretty-format the validity expiry. Returns:
//   { label: "Tuesday, 30 June 2026", days_left: 14, urgency: "ok"|"warn"|"expired" }
function formatExpiry(isoString) {
    if (!isoString) return null;
    const expires = new Date(isoString);
    if (isNaN(expires.getTime())) return null;
    const now = new Date();
    const diffMs = expires.getTime() - now.getTime();
    const days_left = Math.ceil(diffMs / 86400000);
    const label = expires.toLocaleDateString("en-GB", {
        weekday: "long", day: "numeric", month: "long", year: "numeric",
    });
    let urgency = "ok";
    if (days_left < 0) urgency = "expired";
    else if (days_left < 3) urgency = "warn";
    return { label, days_left, urgency };
}

export default function RequestLink() {
    const { token } = useParams();
    const { theme, toggle } = useTheme();
    const [info, setInfo] = useState(undefined);  // undefined=loading, null=invalid
    const [error, setError] = useState(null);
    // rows: array of {id, date, pref, notes, slot?, checking}
    const [rows, setRows] = useState([]);
    // Add-mode toggle: "single" or "range"
    const [addMode, setAddMode] = useState("single");
    const [newDate, setNewDate] = useState("");
    const [rangeFrom, setRangeFrom] = useState("");
    const [rangeTo, setRangeTo] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [submitted, setSubmitted] = useState(false);

    useEffect(() => {
        axios.get(`${BACKEND_URL}/api/public/request-link/${token}`)
            .then((r) => setInfo(r.data))
            .catch((err) => {
                setInfo(null);
                setError(err?.response?.data?.detail || "Link not found");
            });
    }, [token]);

    /* Use the extended window field if the backend exposes it (today →
       end-of-next-year), falling back to the legacy current_rota_window. */
    const window_ = info?.window || info?.current_rota_window || null;
    const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);
    const expiry = useMemo(() => formatExpiry(info?.valid_until), [info?.valid_until]);

    /** Add a single date row OR a range of dates. Range mode expands
     *  the inclusive window into one row per date so the rest of the
     *  flow (slot check, edit pref, edit notes) is unchanged.
     */
    const addRow = () => {
        if (!window_) return;
        // Range mode: generate dates from rangeFrom..rangeTo inclusive.
        if (addMode === "range") {
            if (!rangeFrom || !rangeTo) { toast.error("Pick both From and To dates"); return; }
            if (rangeFrom > rangeTo)    { toast.error("From-date must be before to-date"); return; }
            if (rangeFrom < window_.from || rangeTo > window_.to) {
                toast.error(`Range must sit between ${window_.from} and ${window_.to}`);
                return;
            }
            const dates = [];
            const d0 = new Date(rangeFrom + "T00:00:00");
            const d1 = new Date(rangeTo + "T00:00:00");
            for (let d = new Date(d0); d <= d1; d.setDate(d.getDate() + 1)) {
                dates.push(d.toISOString().slice(0, 10));
            }
            const existing = new Set(rows.map((r) => r.date));
            const newRows = dates
                .filter((d) => !existing.has(d))
                .map((d, i) => ({
                    id: `${d}-${Date.now()}-${i}`, date: d, pref: "OFF", notes: "",
                    slot: null, checking: false,
                }));
            if (newRows.length === 0) {
                toast.error("All dates in that range are already added");
                return;
            }
            setRows((prev) => [...prev, ...newRows].sort((a, b) => a.date.localeCompare(b.date)));
            setRangeFrom(""); setRangeTo("");
            // Run slot check on each freshly added row.
            newRows.forEach((row, i) => {
                setTimeout(() => checkSlot(row.id, row.date, row.pref), 100 + i * 60);
            });
            toast.success(`Added ${newRows.length} date${newRows.length === 1 ? "" : "s"}`);
            return;
        }
        // Single mode (default).
        if (!newDate) { toast.error("Pick a date first"); return; }
        if (newDate < window_.from || newDate > window_.to) {
            toast.error(`Date must be between ${window_.from} and ${window_.to}`);
            return;
        }
        if (rows.some((r) => r.date === newDate)) {
            toast.error("You already have a request for that date");
            return;
        }
        const row = { id: `${newDate}-${Date.now()}`, date: newDate, pref: "OFF", notes: "", slot: null, checking: false };
        setRows((prev) => [...prev, row].sort((a, b) => a.date.localeCompare(b.date)));
        setNewDate("");
        setTimeout(() => checkSlot(row.id, row.date, row.pref), 100);
    };

    const setRow = (id, patch) => {
        setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
    };

    const deleteRow = (id) => {
        setRows((prev) => prev.filter((r) => r.id !== id));
    };

    /* Slot-availability check — calls /api/public/request-link/{t}/check
       and stores the rich response so the row can render either:
        - green "Slot is open" banner
        - red "Conflict" banner with offending staff + role + reason
        - amber info chip listing OTHER staff already off (no conflict) */
    const checkSlot = async (id, date, pref) => {
        if (!["OFF", "AL"].includes(pref)) {
            // Still query so we can show amber info chip if anyone else
            // is off that day — useful awareness even for non-OFF prefs.
            setRow(id, { checking: true });
            try {
                const { data } = await axios.get(
                    `${BACKEND_URL}/api/public/request-link/${token}/check`,
                    { params: { date, preference: pref || "WANT_D" } },
                );
                setRow(id, { slot: data, checking: false });
            } catch {
                setRow(id, { slot: null, checking: false });
            }
            return;
        }
        setRow(id, { checking: true });
        try {
            const { data } = await axios.get(
                `${BACKEND_URL}/api/public/request-link/${token}/check`,
                { params: { date, preference: pref } },
            );
            setRow(id, { slot: data, checking: false });
        } catch {
            setRow(id, { slot: null, checking: false });
        }
    };

    const submit = async () => {
        const payload = rows
            .filter((r) => r.pref && r.pref !== "DEFAULT")
            .map((r) => ({ date: r.date, shift_preference: r.pref, notes: r.notes || "" }));
        if (payload.length === 0) {
            toast.error("Pick at least one date with a preference");
            return;
        }
        setSubmitting(true);
        try {
            await axios.post(`${BACKEND_URL}/api/public/request-link/${token}/submit`, { requests: payload });
            setSubmitted(true);
        } catch (err) {
            toast.error(err?.response?.data?.detail || "Submit failed");
        } finally {
            setSubmitting(false);
        }
    };

    if (info === undefined) {
        return <div className="min-h-screen flex items-center justify-center text-sm text-muted-foreground" data-testid="rl-loading">Loading…</div>;
    }
    if (info === null) {
        return (
            <div className="min-h-screen login-hero flex items-center justify-center px-6" data-testid="rl-invalid">
                <div className="app-card p-10 max-w-md text-center">
                    <AlertOctagon className="w-10 h-10 mx-auto mb-3" style={{ color: "hsl(var(--accent-red))" }} />
                    <h1 className="display text-2xl font-semibold mb-2">Sorry, this link doesn't work</h1>
                    <p className="text-sm text-muted-foreground">{error}</p>
                </div>
            </div>
        );
    }
    if (submitted) {
        return (
            <div className="min-h-screen login-hero flex items-center justify-center px-6" data-testid="rl-submitted">
                <div className="app-card p-10 max-w-md text-center">
                    <CheckCircle2 className="w-10 h-10 mx-auto mb-3" style={{ color: "hsl(var(--accent-green))" }} />
                    <h1 className="display text-2xl font-semibold mb-2">Thanks, {info.name?.split(" ")[0] || ""}</h1>
                    <p className="text-sm text-muted-foreground">Your manager will review your requests.</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen login-hero" data-testid="request-link-page">
            <Toaster richColors closeButton />
            <div className="max-w-xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
                {/* Header — theme toggle + expiry */}
                <div className="flex items-center justify-between mb-3 gap-2">
                    <div className="flex items-center gap-1.5 text-[11px] sm:text-xs uppercase tracking-wider text-muted-foreground">
                        <Calendar className="w-3.5 h-3.5" />
                        <span className="truncate">Staff request</span>
                    </div>
                    <button
                        type="button"
                        onClick={toggle}
                        data-testid="rl-theme-toggle"
                        className="shrink-0 flex items-center gap-1.5 text-[11px] sm:text-xs px-2.5 py-1 rounded-full border focus-ring transition-colors"
                        style={{
                            borderColor: "hsl(var(--border-strong))",
                            background: "hsl(var(--bg))",
                        }}
                        aria-label="Toggle theme"
                        title={`Theme: ${theme} — click to switch`}
                    >
                        {theme === "paper" ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
                        <span className="capitalize">{theme}</span>
                    </button>
                </div>
                <h1 className="display text-2xl sm:text-4xl font-semibold leading-tight break-words" data-testid="rl-hi">
                    Hi {info.name || info.staff_initials}
                </h1>
                <p className="text-sm text-muted-foreground mt-2">
                    Submit requests for any date from <strong>{window_?.from}</strong> through <strong>{window_?.to}</strong>.
                </p>

                {/* Expiry banner */}
                {expiry && (
                    <ExpiryBanner expiry={expiry} />
                )}

                {/* Date picker — Single date or Date range. Range mode
                    expands the From/To window into one row per date so
                    the slot check + per-row preference edit still apply. */}
                <div className="app-card mt-4 p-3 sm:p-4 flex flex-col gap-3" data-testid="rl-add-card">
                    <div className="flex gap-1.5 text-xs" role="tablist">
                        <button
                            type="button"
                            role="tab"
                            aria-selected={addMode === "single"}
                            onClick={() => setAddMode("single")}
                            className="px-2.5 py-1 rounded-md border focus-ring transition-colors"
                            style={{
                                background: addMode === "single" ? "hsl(var(--bg-elev))" : "transparent",
                                borderColor: "hsl(var(--border-strong))",
                                color: addMode === "single" ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))",
                            }}
                            data-testid="rl-mode-single"
                        >
                            Single date
                        </button>
                        <button
                            type="button"
                            role="tab"
                            aria-selected={addMode === "range"}
                            onClick={() => setAddMode("range")}
                            className="px-2.5 py-1 rounded-md border focus-ring transition-colors"
                            style={{
                                background: addMode === "range" ? "hsl(var(--bg-elev))" : "transparent",
                                borderColor: "hsl(var(--border-strong))",
                                color: addMode === "range" ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))",
                            }}
                            data-testid="rl-mode-range"
                        >
                            Date range
                        </button>
                    </div>
                    {addMode === "single" ? (
                        <div className="w-full">
                            <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">
                                Pick a date
                            </label>
                            <Input
                                type="date"
                                value={newDate}
                                min={window_?.from || todayIso}
                                max={window_?.to || "2030-12-31"}
                                onChange={(e) => setNewDate(e.target.value)}
                                data-testid="rl-new-date"
                                className="focus-ring w-full"
                            />
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
                            <div>
                                <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">From</label>
                                <Input
                                    type="date"
                                    value={rangeFrom}
                                    min={window_?.from || todayIso}
                                    max={window_?.to || "2030-12-31"}
                                    onChange={(e) => setRangeFrom(e.target.value)}
                                    data-testid="rl-range-from"
                                    className="focus-ring w-full"
                                />
                            </div>
                            <div>
                                <label className="text-xs uppercase tracking-wider text-muted-foreground block mb-1">To</label>
                                <Input
                                    type="date"
                                    value={rangeTo}
                                    min={rangeFrom || window_?.from || todayIso}
                                    max={window_?.to || "2030-12-31"}
                                    onChange={(e) => setRangeTo(e.target.value)}
                                    data-testid="rl-range-to"
                                    className="focus-ring w-full"
                                />
                            </div>
                        </div>
                    )}
                    <Button
                        className="btn-primary w-full"
                        onClick={addRow}
                        data-testid="rl-add-row"
                    >
                        <Plus className="w-4 h-4 mr-1.5" />
                        {addMode === "range" ? "Add date range" : "Add request"}
                    </Button>
                </div>

                {rows.length > 0 && (
                    <div className="app-card mt-4 divide-y" style={{ borderColor: "hsl(var(--border))" }} data-testid="rl-rows">
                        {rows.map((r) => (
                            <div key={r.id} className="p-3 space-y-2" data-testid={`rl-row-${r.date}`}>
                                <div className="flex flex-wrap items-center gap-2">
                                    <div className="flex items-center gap-1 text-sm font-semibold tabular-nums">
                                        <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
                                        {r.date}
                                    </div>
                                    <div className="flex-1 min-w-[160px]">
                                    <Select
                                        value={r.pref}
                                        onValueChange={(v) => {
                                            setRow(r.id, { pref: v });
                                            checkSlot(r.id, r.date, v);
                                        }}
                                    >
                                        <SelectTrigger className="w-full" data-testid={`rl-pref-${r.date}`}>
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {PREFS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                    </div>
                                    <Button
                                        size="icon"
                                        variant="ghost"
                                        onClick={() => deleteRow(r.id)}
                                        title="Remove"
                                        data-testid={`rl-delete-${r.date}`}
                                        className="shrink-0"
                                    >
                                        <Trash2 className="w-4 h-4 text-muted-foreground hover:text-destructive" />
                                    </Button>
                                </div>
                                {/* Slot-availability hint */}
                                <SlotBanner row={r} />
                                <Textarea
                                    rows={2}
                                    value={r.notes}
                                    onChange={(e) => setRow(r.id, { notes: e.target.value })}
                                    placeholder="Optional notes"
                                    className="w-full resize-none text-sm"
                                    data-testid={`rl-notes-${r.date}`}
                                />
                            </div>
                        ))}
                    </div>
                )}

                <div className="mt-6 flex justify-end">
                    <Button
                        className="btn-primary w-full sm:w-auto"
                        disabled={submitting || rows.length === 0}
                        onClick={submit}
                        data-testid="rl-submit"
                    >
                        {submitting ? "Submitting…" : `Submit ${rows.length || ""} request${rows.length === 1 ? "" : "s"}`.trim()}
                    </Button>
                </div>
            </div>
        </div>
    );
}

/**
 * Expiry banner — shows "Valid until …" with a relative-days hint.
 *  - urgency=ok    → grey, neutral phrasing
 *  - urgency=warn  → amber, "ask manager for a new link"
 *  - urgency=expired → red (won't usually render: backend already 410s,
 *    but kept for safety)
 */
function ExpiryBanner({ expiry }) {
    const tone = expiry.urgency === "warn"
        ? { bg: "hsl(38 95% 55% / 0.12)", color: "hsl(38 95% 35%)", border: "hsl(38 95% 55% / 0.4)" }
        : expiry.urgency === "expired"
            ? { bg: "hsl(var(--accent-red) / 0.1)", color: "hsl(var(--accent-red))", border: "hsl(var(--accent-red) / 0.4)" }
            : { bg: "hsl(var(--bg-elev))", color: "hsl(var(--muted-foreground))", border: "hsl(var(--border))" };
    const dl = expiry.days_left;
    let suffix;
    if (dl < 0) suffix = `expired ${Math.abs(dl)} day${Math.abs(dl) === 1 ? "" : "s"} ago`;
    else if (dl === 0) suffix = "expires today";
    else if (dl === 1) suffix = "1 day left";
    else suffix = `${dl} days left`;
    return (
        <div
            className="mt-3 flex items-center gap-2 px-3 py-2 rounded-md border text-xs"
            style={{ background: tone.bg, color: tone.color, borderColor: tone.border }}
            data-testid="rl-expiry"
        >
            <Clock className="w-3.5 h-3.5 shrink-0" />
            <div>
                This link is valid until <strong>{expiry.label}</strong> · {suffix}.
                {expiry.urgency === "warn" && " Ask your manager for a new link if you need more time."}
            </div>
        </div>
    );
}

/**
 * Slot banner — three states:
 *  - slot_status === "open" with no other-staff leave → green ✓
 *  - slot_status === "open" but OTHER staff are off → amber info chip
 *    listing who's off (no conflict; staff just sees the heads-up)
 *  - slot_status === "role_conflict" / "hard_limit" → red banner with
 *    full reason + offending staff. Submit stays enabled.
 */
function SlotBanner({ row }) {
    if (!row.slot) return null;
    const slot = row.slot;
    const others = (slot.existing_leave || []).filter(
        (e) => e.staff_initials && e.type !== "self"
    );
    const conflict = slot.slot_status && slot.slot_status !== "open";
    if (conflict) {
        return (
            <div
                className="flex items-start gap-2 px-3 py-2 rounded text-xs"
                style={{
                    background: "hsl(var(--accent-red) / 0.1)",
                    color: "hsl(var(--accent-red))",
                    border: "1px solid hsl(var(--accent-red) / 0.4)",
                }}
                data-testid={`rl-slot-${row.date}`}
            >
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                    <div className="font-semibold">Slot taken</div>
                    {slot.reason && <div className="mt-0.5">{slot.reason}</div>}
                    <div className="mt-0.5 italic">
                        You can still submit — your manager will review.
                    </div>
                </div>
            </div>
        );
    }
    if (others.length > 0) {
        return (
            <div
                className="flex items-start gap-2 px-3 py-2 rounded text-xs"
                style={{
                    background: "hsl(38 95% 55% / 0.1)",
                    color: "hsl(38 95% 25%)",
                    border: "1px solid hsl(38 95% 55% / 0.4)",
                }}
                data-testid={`rl-slot-${row.date}`}
            >
                <Info className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                    <div className="font-semibold">FYI — others off this day</div>
                    <div className="mt-0.5">
                        {others
                            .map((e) => `${e.staff_initials}${e.role ? ` (${e.role})` : ""} on ${e.type}`)
                            .join("; ")}
                    </div>
                    <div className="mt-0.5 italic">
                        No rule conflict — you're fine to submit.
                    </div>
                </div>
            </div>
        );
    }
    return (
        <div
            className="flex items-start gap-2 px-3 py-2 rounded text-xs"
            style={{
                background: "hsl(142 62% 35% / 0.1)",
                color: "hsl(142 62% 25%)",
                border: "1px solid hsl(142 62% 35% / 0.4)",
            }}
            data-testid={`rl-slot-${row.date}`}
        >
            <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
            <div>
                <div className="font-semibold">Slot is open</div>
                <div className="mt-0.5">No one else is off on this date.</div>
            </div>
        </div>
    );
}
