import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, AlertOctagon, Calendar, Plus, Trash2, ShieldCheck, AlertTriangle } from "lucide-react";
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

export default function RequestLink() {
    const { token } = useParams();
    const { theme } = useTheme();
    const [info, setInfo] = useState(undefined);  // undefined=loading, null=invalid
    const [error, setError] = useState(null);
    // rows: array of {id, date, pref, notes, slot?: {slot_open, reason, existing_leave}, checking: bool}
    const [rows, setRows] = useState([]);
    const [newDate, setNewDate] = useState("");
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

    const addRow = () => {
        if (!newDate) { toast.error("Pick a date first"); return; }
        if (!window_) return;
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
       so the staff member sees a green "slot open" or red "slot taken"
       hint BEFORE submitting their OFF/AL request. Best-effort; failure
       silently leaves slot=null and the request is submittable. */
    const checkSlot = async (id, date, pref) => {
        if (!["OFF", "AL"].includes(pref)) {
            setRow(id, { slot: null, checking: false });
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
            <div className="max-w-2xl mx-auto px-6 py-10">
                <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground mb-2">
                    <Calendar className="w-3.5 h-3.5" /> Theme: {theme}
                </div>
                <h1 className="display text-3xl sm:text-4xl font-semibold leading-tight" data-testid="rl-hi">
                    Hi {info.name || info.staff_initials}
                </h1>
                <p className="text-sm text-muted-foreground mt-2">
                    Submit requests for any date from <strong>{window_?.from}</strong> through <strong>{window_?.to}</strong>.
                </p>

                {/* Date picker + add */}
                <div className="app-card mt-6 p-4 flex flex-col sm:flex-row gap-2" data-testid="rl-add-card">
                    <div className="flex-1">
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
                            className="focus-ring"
                        />
                    </div>
                    <Button
                        className="btn-primary sm:self-end"
                        onClick={addRow}
                        data-testid="rl-add-row"
                    >
                        <Plus className="w-4 h-4 mr-1.5" /> Add request
                    </Button>
                </div>

                {rows.length > 0 && (
                    <div className="app-card mt-4 divide-y" style={{ borderColor: "hsl(var(--border))" }} data-testid="rl-rows">
                        {rows.map((r) => (
                            <div key={r.id} className="p-3 space-y-2" data-testid={`rl-row-${r.date}`}>
                                <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                                    <div className="sm:w-32 flex items-center gap-1 text-sm font-semibold tabular-nums">
                                        <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
                                        {r.date}
                                    </div>
                                    <Select
                                        value={r.pref}
                                        onValueChange={(v) => {
                                            setRow(r.id, { pref: v });
                                            checkSlot(r.id, r.date, v);
                                        }}
                                    >
                                        <SelectTrigger className="sm:w-48" data-testid={`rl-pref-${r.date}`}>
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {PREFS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                    <Button
                                        size="icon"
                                        variant="ghost"
                                        onClick={() => deleteRow(r.id)}
                                        title="Remove"
                                        data-testid={`rl-delete-${r.date}`}
                                    >
                                        <Trash2 className="w-4 h-4 text-muted-foreground hover:text-destructive" />
                                    </Button>
                                </div>
                                {/* Slot availability hint for OFF / AL */}
                                {r.slot && (
                                    <div
                                        className="flex items-start gap-2 px-3 py-2 rounded text-xs"
                                        style={{
                                            background: r.slot.slot_open
                                                ? "hsl(142 62% 35% / 0.1)"
                                                : "hsl(var(--accent-red) / 0.1)",
                                            color: r.slot.slot_open
                                                ? "hsl(142 62% 30%)"
                                                : "hsl(var(--accent-red))",
                                        }}
                                        data-testid={`rl-slot-${r.date}`}
                                    >
                                        {r.slot.slot_open ? <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" /> : <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />}
                                        <div>
                                            <div className="font-semibold">
                                                {r.slot.slot_open ? "Slot is open" : "Slot taken"}
                                            </div>
                                            {r.slot.reason && <div className="mt-0.5">{r.slot.reason}</div>}
                                            {!r.slot.slot_open && (
                                                <div className="mt-0.5 italic">
                                                    You can still submit — your manager will decide.
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}
                                <Textarea
                                    rows={1}
                                    value={r.notes}
                                    onChange={(e) => setRow(r.id, { notes: e.target.value })}
                                    placeholder="Optional notes"
                                    className="w-full"
                                    data-testid={`rl-notes-${r.date}`}
                                />
                            </div>
                        ))}
                    </div>
                )}

                <div className="mt-6 flex justify-end">
                    <Button
                        className="btn-primary"
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
