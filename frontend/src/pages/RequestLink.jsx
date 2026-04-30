import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, AlertOctagon, Calendar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import axios from "axios";
import { toast } from "sonner";
import { useTheme } from "@/contexts/ThemeContext";
import { ymd, parseYmd, addDays, dayLetter } from "@/lib/shifts";
import { Toaster } from "@/components/ui/sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const PREFS = [
    { value: "DEFAULT", label: "Default" },
    { value: "OFF", label: "Off" },
    { value: "WANT_N", label: "Want night" },
    { value: "WANT_D", label: "Want day" },
    { value: "AVOID", label: "Avoid" },
];

export default function RequestLink() {
    const { token } = useParams();
    const { theme } = useTheme();
    const [info, setInfo] = useState(undefined); // undefined=loading, null=invalid
    const [error, setError] = useState(null);
    const [rows, setRows] = useState({}); // date -> {pref, notes}
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

    const dates = useMemo(() => {
        if (!info?.current_rota_window) return [];
        const start = parseYmd(info.current_rota_window.from);
        const end = parseYmd(info.current_rota_window.to);
        const days = Math.round((end - start) / 86400000) + 1;
        return Array.from({ length: days }, (_, i) => addDays(start, i));
    }, [info]);

    const submit = async () => {
        const payload = Object.entries(rows)
            .filter(([, v]) => v?.pref && v.pref !== "DEFAULT")
            .map(([date, v]) => ({ date, shift_preference: v.pref, notes: v.notes || "" }));
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
                <h1 className="display text-3xl sm:text-4xl font-semibold leading-tight">Hi {info.name || info.staff_initials}</h1>
                <p className="text-sm text-muted-foreground mt-2">
                    Submit your requests for the rota: <strong>{info.current_rota_window.from}</strong> → <strong>{info.current_rota_window.to}</strong>
                </p>

                <div className="app-card mt-6 divide-y" style={{ borderColor: "hsl(var(--border))" }}>
                    {dates.map((d) => {
                        const ds = ymd(d);
                        const row = rows[ds] || { pref: "DEFAULT", notes: "" };
                        const setRow = (patch) => setRows((r) => ({ ...r, [ds]: { ...row, ...patch } }));
                        return (
                            <div key={ds} className="p-3 flex flex-col sm:flex-row sm:items-center gap-2" data-testid={`rl-row-${ds}`}>
                                <div className="flex items-center gap-2 sm:w-32">
                                    <span className="text-xs font-semibold tabular-nums">{dayLetter(d)}</span>
                                    <span className="text-sm tabular-nums">{ds}</span>
                                </div>
                                <Select value={row.pref} onValueChange={(v) => setRow({ pref: v })}>
                                    <SelectTrigger className="sm:w-44" data-testid={`rl-pref-${ds}`}><SelectValue /></SelectTrigger>
                                    <SelectContent>{PREFS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent>
                                </Select>
                                {row.pref !== "DEFAULT" && (
                                    <Textarea
                                        rows={1}
                                        value={row.notes}
                                        onChange={(e) => setRow({ notes: e.target.value })}
                                        placeholder="Optional notes"
                                        className="flex-1"
                                        data-testid={`rl-notes-${ds}`}
                                    />
                                )}
                            </div>
                        );
                    })}
                </div>

                <div className="mt-6 flex justify-end">
                    <Button className="btn-primary" disabled={submitting} onClick={submit} data-testid="rl-submit">
                        {submitting ? "Submitting…" : "Submit requests"}
                    </Button>
                </div>
            </div>
        </div>
    );
}
