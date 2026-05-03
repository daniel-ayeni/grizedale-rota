import { useEffect, useMemo, useState } from "react";
import { Plus, Check, X as XIcon, Pencil, Link as LinkIcon, Copy, Trash2, AlertTriangle, Eye, Calendar as CalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Tabs, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
    Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

const PREFS = [
    { value: "OFF", label: "Off" },
    { value: "WANT_N", label: "Want night" },
    { value: "WANT_D", label: "Want day" },
    { value: "WANT_DSTAR", label: "Want D*" },
    { value: "AVOID", label: "Avoid" },
    { value: "OTHER", label: "Other" },
];

const STATUS_BADGE = {
    pending: "outline",
    accepted: "default",
    rejected: "destructive",
    changed: "secondary",
};

export default function Requests() {
    const [tab, setTab] = useState("pending");
    const [reqs, setReqs] = useState([]);
    const [staff, setStaff] = useState([]);
    const [tokens, setTokens] = useState([]);
    const [selected, setSelected] = useState(new Set());
    const [addOpen, setAddOpen] = useState(false);
    const [linksOpen, setLinksOpen] = useState(false);
    const [inspectReq, setInspectReq] = useState(null);
    // Override dialog state — opened when a manager tries to accept a
    // request (single or bulk) whose slot has a hard-rule clash. The
    // manager must tick "I understand" + give a reason before the accept
    // is resubmitted with override_conflict=true.
    const [overrideCtx, setOverrideCtx] = useState(null);
    // Bulk-delete UI — date cutoff for the "Older than" filter on the
    // request list. Empty string = no filter.
    const [olderThanCutoff, setOlderThanCutoff] = useState("");

    const load = async () => {
        try {
            const [reqsRes, staffRes, tokensRes] = await Promise.all([
                api.get(`/requests${tab === "all" ? "" : `?status=${tab}`}`),
                api.get("/staff"),
                api.get("/request-tokens"),
            ]);
            setReqs(reqsRes.data);
            setStaff(staffRes.data.filter((s) => s.active));
            setTokens(tokensRes.data);
            setSelected(new Set());
        } catch (e) {
            toast.error(formatApiError(e));
        }
    };
    useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab]);

    /** Accept a single request. If the pending row carries a conflict
     *  (slot_open=false), open the override dialog instead of posting
     *  immediately. The manager confirms + supplies a reason; the dialog
     *  then re-posts with override_conflict=true. */
    const resolveOne = async (req, status) => {
        if (status === "accepted"
            && req.conflicts
            && req.conflicts.slot_open === false) {
            setOverrideCtx({ mode: "single", rows: [req] });
            return;
        }
        try {
            await api.patch(`/requests/${req.id}`, { status });
            toast.success(status === "accepted" ? "Accepted" : status === "rejected" ? "Rejected" : "Updated");
            load();
        } catch (err) {
            // Fallback — backend may have re-detected a conflict the
            // client didn't know about. Prompt for override.
            if (err?.response?.status === 409) {
                setOverrideCtx({
                    mode: "single",
                    rows: [{ ...req, conflicts: err.response.data?.detail }],
                });
                return;
            }
            toast.error(formatApiError(err));
        }
    };

    /** Accept/reject selected rows in bulk. Accept with conflicts opens
     *  a batch override dialog listing every clashing row. */
    const resolveBulk = async (status) => {
        if (selected.size === 0) return;
        const rows = reqs.filter((r) => selected.has(r.id));
        if (status === "accepted") {
            const conflictRows = rows.filter(
                (r) => r.conflicts && r.conflicts.slot_open === false
            );
            if (conflictRows.length > 0) {
                setOverrideCtx({ mode: "bulk", rows, conflictRows });
                return;
            }
        }
        try {
            const res = await api.post("/requests/bulk", { ids: Array.from(selected), status });
            toast.success(`${res.data?.updated?.length || 0} updated${res.data?.leave_created ? ` · ${res.data.leave_created} leave entries created` : ""}`);
            load();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    // Called by OverrideConflictDialog after the manager confirms.
    const submitOverride = async (reason) => {
        if (!overrideCtx) return;
        try {
            if (overrideCtx.mode === "single") {
                const req = overrideCtx.rows[0];
                await api.patch(`/requests/${req.id}`, {
                    status: "accepted",
                    override_conflict: true,
                    override_reason: reason,
                });
                toast.success("Accepted with override logged");
            } else {
                const res = await api.post("/requests/bulk", {
                    ids: overrideCtx.rows.map((r) => r.id),
                    status: "accepted",
                    override_conflict: true,
                    override_reason: reason,
                });
                toast.success(`${res.data?.updated?.length || 0} accepted · ${overrideCtx.conflictRows?.length || 0} override${overrideCtx.conflictRows?.length === 1 ? "" : "s"} logged`);
            }
            setOverrideCtx(null);
            load();
        } catch (err) {
            toast.error(formatApiError(err));
        }
    };

    const toggleSel = (id) => setSelected((s) => {
        const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
    });

    /** Bulk delete selected rows (any tab/status). */
    const bulkDeleteSelected = async () => {
        if (selected.size === 0) return;
        if (!window.confirm(`Delete ${selected.size} request${selected.size === 1 ? "" : "s"}? This can't be undone.`)) return;
        try {
            const { data } = await api.post("/requests/bulk-delete", { ids: Array.from(selected) });
            toast.success(`Deleted ${data?.deleted || 0} request${data?.deleted === 1 ? "" : "s"}`);
            load();
        } catch (e) { toast.error(formatApiError(e)); }
    };
    /** "Older than" cutoff — count matches client-side, delete via API. */
    const olderThanCount = useMemo(() => {
        if (!olderThanCutoff) return 0;
        return reqs.filter((r) => r.date && r.date < olderThanCutoff).length;
    }, [reqs, olderThanCutoff]);
    const selectAllOlderThan = () => {
        if (!olderThanCutoff) return;
        setSelected(new Set(reqs.filter((r) => r.date && r.date < olderThanCutoff).map((r) => r.id)));
    };
    const bulkDeleteOlderThan = async () => {
        if (!olderThanCutoff) return;
        if (!window.confirm(`Delete ALL requests dated before ${olderThanCutoff}? This can't be undone.`)) return;
        try {
            const { data } = await api.post("/requests/bulk-delete", { older_than: olderThanCutoff });
            toast.success(`Deleted ${data?.deleted || 0} request${data?.deleted === 1 ? "" : "s"}`);
            setOlderThanCutoff("");
            load();
        } catch (e) { toast.error(formatApiError(e)); }
    };

    return (
        <div className="space-y-6" data-testid="requests-page">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div>
                    <h1 className="display text-3xl font-semibold">Request Box</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Review staff requests for shifts off, preferences and notes. Accept to create leave automatically.
                    </p>
                </div>
                <div className="flex gap-2">
                    <Button variant="outline" onClick={() => setLinksOpen(true)} data-testid="manage-links-button"><LinkIcon className="w-4 h-4 mr-1.5" />Manage staff links</Button>
                    <Button className="btn-primary" onClick={() => setAddOpen(true)} data-testid="add-request-button"><Plus className="w-4 h-4 mr-1.5" />Add request</Button>
                </div>
            </div>

            <Tabs value={tab} onValueChange={setTab}>
                <TabsList data-testid="requests-tabs">
                    <TabsTrigger value="pending" data-testid="tab-pending">Pending</TabsTrigger>
                    <TabsTrigger value="accepted" data-testid="tab-accepted">Accepted</TabsTrigger>
                    <TabsTrigger value="rejected" data-testid="tab-rejected">Rejected</TabsTrigger>
                    <TabsTrigger value="all" data-testid="tab-all">All</TabsTrigger>
                </TabsList>
            </Tabs>

            {/* Older-than-date filter — quick way to clean out historic
                requests without ticking each checkbox. */}
            <div className="app-card p-3 flex flex-wrap items-end gap-2" data-testid="older-than-bar">
                <div>
                    <Label className="text-[10px] uppercase tracking-wider text-muted-foreground">Older than</Label>
                    <Input
                        type="date"
                        value={olderThanCutoff}
                        onChange={(e) => setOlderThanCutoff(e.target.value)}
                        className="w-44"
                        data-testid="older-than-date"
                    />
                </div>
                {olderThanCutoff && (
                    <>
                        <div className="text-xs text-muted-foreground self-center">
                            <strong>{olderThanCount}</strong> match{olderThanCount === 1 ? "" : "es"} in current view
                        </div>
                        <Button size="sm" variant="outline" onClick={selectAllOlderThan} data-testid="older-than-select-all">
                            Select matching
                        </Button>
                        <Button
                            size="sm"
                            variant="outline"
                            className="text-destructive border-destructive/40 hover:bg-destructive/10"
                            onClick={bulkDeleteOlderThan}
                            data-testid="older-than-delete-all"
                        >
                            <Trash2 className="w-3.5 h-3.5 mr-1" /> Delete all matching (server-side)
                        </Button>
                    </>
                )}
            </div>

            {selected.size > 0 && (
                <div className="app-card p-3 flex items-center justify-between" data-testid="bulk-bar">
                    <div className="text-sm">{selected.size} selected</div>
                    <div className="flex gap-2 flex-wrap">
                        {tab === "pending" && (
                            <>
                                <Button size="sm" variant="outline" onClick={() => resolveBulk("rejected")} data-testid="bulk-reject"><XIcon className="w-3.5 h-3.5 mr-1" />Reject</Button>
                                <Button size="sm" className="btn-primary" onClick={() => resolveBulk("accepted")} data-testid="bulk-accept"><Check className="w-3.5 h-3.5 mr-1" />Accept</Button>
                            </>
                        )}
                        <Button
                            size="sm"
                            variant="outline"
                            className="text-destructive border-destructive/40 hover:bg-destructive/10"
                            onClick={bulkDeleteSelected}
                            data-testid="bulk-delete"
                        >
                            <Trash2 className="w-3.5 h-3.5 mr-1" /> Delete selected
                        </Button>
                    </div>
                </div>
            )}

            <div className="app-card overflow-x-auto" data-testid="requests-table-wrap">
                <Table className="paper-table" data-testid="requests-table">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[40px]" />
                            <TableHead>Staff</TableHead>
                            <TableHead>Date</TableHead>
                            <TableHead>Preference</TableHead>
                            <TableHead className="hidden md:table-cell">Notes</TableHead>
                            <TableHead>Source</TableHead>
                            <TableHead>Status</TableHead>
                            <TableHead>Conflicts</TableHead>
                            <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {reqs.length === 0 && <TableRow><TableCell colSpan={9} className="text-center py-8 text-sm text-muted-foreground">No requests</TableCell></TableRow>}
                        {reqs.map((r) => (
                            <TableRow key={r.id} data-testid={`req-row-${r.id}`}>
                                <TableCell>
                                    <Checkbox checked={selected.has(r.id)} onCheckedChange={() => toggleSel(r.id)} data-testid={`req-${r.id}-select`} />
                                </TableCell>
                                <TableCell className="font-semibold">{r.staff_initials}</TableCell>
                                <TableCell>{r.date}</TableCell>
                                <TableCell><Badge variant="outline">{PREFS.find((p) => p.value === r.shift_preference)?.label || r.shift_preference}</Badge></TableCell>
                                <TableCell className="hidden md:table-cell text-sm text-muted-foreground max-w-xs truncate">{r.notes || "—"}</TableCell>
                                <TableCell><span className="text-xs uppercase">{r.source}</span></TableCell>
                                <TableCell><Badge variant={STATUS_BADGE[r.status] || "outline"}>{r.status}</Badge></TableCell>
                                <TableCell data-testid={`req-${r.id}-conflicts`}>
                                    <RequestConflictChips req={r} />
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="flex justify-end gap-0.5">
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            onClick={() => setInspectReq(r)}
                                            data-testid={`req-${r.id}-inspect`}
                                            title="Inspect day context"
                                        >
                                            <Eye className="w-4 h-4 text-muted-foreground" />
                                        </Button>
                                        {r.status === "pending" ? (
                                            <>
                                                <Button size="sm" variant="ghost" onClick={() => resolveOne(r, "accepted")} data-testid={`req-${r.id}-accept`}><Check className="w-4 h-4 text-green-600" /></Button>
                                                <Button size="sm" variant="ghost" onClick={() => resolveOne(r, "rejected")} data-testid={`req-${r.id}-reject`}><XIcon className="w-4 h-4 text-destructive" /></Button>
                                            </>
                                        ) : (
                                            <span className="text-xs text-muted-foreground">{r.resolution_note || ""}</span>
                                        )}
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            {/* Add request dialog */}
            <AddRequestDialog open={addOpen} onOpenChange={setAddOpen} staff={staff} onAdded={load} />
            {/* Manage staff links drawer */}
            <ManageLinksDrawer open={linksOpen} onOpenChange={setLinksOpen} staff={staff} tokens={tokens} onChange={load} />
            {/* Override conflict dialog */}
            <OverrideConflictDialog
                ctx={overrideCtx}
                onOpenChange={(v) => { if (!v) setOverrideCtx(null); }}
                onConfirm={submitOverride}
            />
            {/* Inspect-day panel */}
            <InspectRequestSheet
                req={inspectReq}
                onOpenChange={(v) => { if (!v) setInspectReq(null); }}
            />
        </div>
    );
}

function AddRequestDialog({ open, onOpenChange, staff, onAdded }) {
    const [form, setForm] = useState({ staff_initials: "", date: "", shift_preference: "OFF", notes: "" });
    useEffect(() => { if (!open) setForm({ staff_initials: "", date: "", shift_preference: "OFF", notes: "" }); }, [open]);

    const submit = async (e) => {
        e.preventDefault();
        try {
            await api.post("/requests", { ...form, source: "manager" });
            toast.success("Request added");
            onOpenChange(false);
            onAdded();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent data-testid="add-request-dialog">
                <DialogHeader>
                    <DialogTitle>Add request</DialogTitle>
                    <DialogDescription>Create a request on behalf of a staff member.</DialogDescription>
                </DialogHeader>
                <form onSubmit={submit} className="space-y-3">
                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Staff</Label>
                        <Select value={form.staff_initials} onValueChange={(v) => setForm((f) => ({ ...f, staff_initials: v }))}>
                            <SelectTrigger className="mt-1.5" data-testid="add-req-staff"><SelectValue placeholder="Select staff…" /></SelectTrigger>
                            <SelectContent>{staff.map((s) => <SelectItem key={s.initials} value={s.initials}>{s.initials} — {s.full_name}</SelectItem>)}</SelectContent>
                        </Select>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">Date</Label>
                            <Input type="date" required value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} className="mt-1.5" data-testid="add-req-date" />
                        </div>
                        <div>
                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">Preference</Label>
                            <Select value={form.shift_preference} onValueChange={(v) => setForm((f) => ({ ...f, shift_preference: v }))}>
                                <SelectTrigger className="mt-1.5" data-testid="add-req-pref"><SelectValue /></SelectTrigger>
                                <SelectContent>{PREFS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent>
                            </Select>
                        </div>
                    </div>
                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Notes</Label>
                        <Textarea value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} className="mt-1.5" rows={3} data-testid="add-req-notes" />
                    </div>
                    <DialogFooter>
                        <Button type="submit" className="btn-primary" disabled={!form.staff_initials || !form.date} data-testid="add-req-submit">Add</Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function ManageLinksDrawer({ open, onOpenChange, staff, tokens, onChange }) {
    const [staffPick, setStaffPick] = useState("");
    const [days, setDays] = useState(30);

    const generate = async () => {
        if (!staffPick) return;
        try {
            const { data } = await api.post("/request-tokens", { staff_initials: staffPick, expires_in_days: days });
            // Backend returns long_url + short_url + short_url_provider
            // (is.gd / da.gd / direct). Copy the short one if available.
            const longUrl = data.long_url || `${window.location.origin}${data.url}`;
            const linkToCopy = data.short_url || longUrl;
            await navigator.clipboard.writeText(linkToCopy).catch(() => {});
            const provider = data.short_url_provider || "direct";
            toast.success(data.short_url
                ? `Short link copied to clipboard (via ${provider})`
                : "Link copied to clipboard");
            onChange();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    const copyOne = async (t) => {
        // Prefer the short_url; fall back to long_url; then build from
        // token (legacy rows that pre-date long_url).
        const url = t.short_url || t.long_url || `${window.location.origin}/r/${t.token}`;
        await navigator.clipboard.writeText(url).catch(() => {});
        const provider = t.short_url_provider || (t.short_url ? "shortener" : "long");
        toast.success(t.short_url ? `Short link copied (via ${provider})` : "Link copied");
    };

    const revoke = async (id) => {
        try {
            await api.post(`/request-tokens/${id}/revoke`);
            toast.success("Revoked");
            onChange();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="overflow-y-auto sm:max-w-lg" data-testid="links-drawer">
                <SheetHeader>
                    <SheetTitle>Staff request links</SheetTitle>
                    <SheetDescription>Generate anonymous links staff can use to submit requests without logging in.</SheetDescription>
                </SheetHeader>

                <div className="app-card p-3 mt-4 space-y-2" data-testid="generate-link-card">
                    <Label className="text-xs uppercase tracking-wider text-muted-foreground">Generate new link</Label>
                    <div className="flex gap-2">
                        <Select value={staffPick} onValueChange={setStaffPick}>
                            <SelectTrigger className="flex-1" data-testid="gen-link-staff"><SelectValue placeholder="Pick staff…" /></SelectTrigger>
                            <SelectContent>{staff.map((s) => <SelectItem key={s.initials} value={s.initials}>{s.initials} — {s.full_name}</SelectItem>)}</SelectContent>
                        </Select>
                        <Input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-20" data-testid="gen-link-days" />
                        <Button onClick={generate} className="btn-primary" data-testid="gen-link-button">Generate</Button>
                    </div>
                    <div className="text-xs text-muted-foreground">Valid for {days} days. URL is copied to clipboard on generate.</div>
                </div>

                <div className="mt-4 space-y-2">
                    <Label className="text-xs uppercase tracking-wider text-muted-foreground">Active links · {tokens.length}</Label>
                    {tokens.length === 0 && <div className="text-sm text-muted-foreground py-2">No active links</div>}
                    {tokens.map((t) => {
                        const longUrl = t.long_url || `${window.location.origin}/r/${t.token}`;
                        const shortUrl = t.short_url;
                        return (
                            <div key={t.id} className="p-2 rounded border space-y-1.5" style={{ borderColor: "hsl(var(--border))" }} data-testid={`link-row-${t.id}`}>
                                <div className="flex items-center justify-between gap-2">
                                    <div className="min-w-0">
                                        <div className="text-sm font-semibold">{t.staff_initials}</div>
                                        <div className="text-xs text-muted-foreground">expires {t.expires_at?.slice(0, 10)}</div>
                                    </div>
                                    <div className="flex gap-1 shrink-0">
                                        <Button size="sm" variant="outline" onClick={() => copyOne(t)} data-testid={`link-copy-${t.id}`}>
                                            <Copy className="w-3.5 h-3.5 mr-1" /> Copy link
                                        </Button>
                                        <Button size="sm" variant="ghost" onClick={() => revoke(t.id)} data-testid={`link-revoke-${t.id}`} title="Revoke link">
                                            <Trash2 className="w-4 h-4 text-destructive" />
                                        </Button>
                                    </div>
                                </div>
                                {/* PRIMARY chip — short URL when available. */}
                                {shortUrl ? (
                                    <>
                                        <code
                                            className="block px-2 py-1.5 rounded font-mono text-sm font-semibold cursor-pointer select-all"
                                            style={{ background: "hsl(var(--bg-elev))", color: "hsl(var(--primary))" }}
                                            onClick={() => copyOne(t)}
                                            data-testid={`link-short-${t.id}`}
                                            title="Click to copy short link"
                                        >
                                            {shortUrl}
                                        </code>
                                        <div className="text-[10px] text-muted-foreground italic">
                                            via {t.short_url_provider || "shortener"} · expanded: <span className="select-all" title={longUrl}>{longUrl.replace(/^https?:\/\//, "")}</span>
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        {/* Fallback when shortener was unreachable — long URL only. */}
                                        <code
                                            className="block px-2 py-1.5 rounded font-mono text-xs cursor-pointer select-all"
                                            style={{ background: "hsl(var(--bg-elev))", color: "hsl(var(--primary))" }}
                                            onClick={() => copyOne(t)}
                                            data-testid={`link-short-${t.id}`}
                                            title="Click to copy link"
                                        >
                                            {longUrl}
                                        </code>
                                        <div className="text-[10px] text-muted-foreground italic">
                                            (Shortener unavailable — using long link)
                                        </div>
                                    </>
                                )}
                                <div className="text-[10px] text-muted-foreground italic">
                                    Staff can bookmark this link.
                                </div>
                            </div>
                        );
                    })}
                </div>
            </SheetContent>
        </Sheet>
    );
}

/**
 * Override conflict dialog — opened when accepting a request (single or
 * bulk) that would trigger `max_one_per_role_on_al`. Forces the manager
 * to tick "I understand" and enter a reason; only then enables the
 * "Accept with override" action. Backend logs each override to the
 * `audit_log` collection with the manager's email + reason.
 */
function OverrideConflictDialog({ ctx, onOpenChange, onConfirm }) {
    const [ack, setAck] = useState(false);
    const [reason, setReason] = useState("");
    useEffect(() => {
        if (ctx) { setAck(false); setReason(""); }
    }, [ctx]);

    if (!ctx) return null;
    const conflictRows = ctx.mode === "single"
        ? ctx.rows
        : (ctx.conflictRows || []);

    return (
        <Dialog open={!!ctx} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-lg" data-testid="override-conflict-dialog">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <AlertTriangle className="w-5 h-5 text-destructive" />
                        Conflict — manager override required
                    </DialogTitle>
                    <DialogDescription>
                        {ctx.mode === "single"
                            ? "Accepting this request will break the max-one-per-role-on-AL rule."
                            : `Accepting ${conflictRows.length} of the selected requests will break the max-one-per-role-on-AL rule. Non-clashing rows will be accepted normally.`}
                        {" "}Your override will be logged.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3 text-sm">
                    <div className="rounded-md border p-3 space-y-2 bg-[hsl(var(--bg-elev))]" style={{ borderColor: "hsl(var(--accent-red) / 0.4)" }}>
                        {conflictRows.map((r) => (
                            <div key={r.id} className="flex items-start gap-2" data-testid={`override-row-${r.id}`}>
                                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-destructive" />
                                <div className="text-xs">
                                    <div><strong>{r.staff_initials}</strong> · {r.date} · <code>{r.shift_preference}</code></div>
                                    {r.conflicts?.reason && (
                                        <div className="text-muted-foreground">{r.conflicts.reason}</div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>

                    <div>
                        <Label className="text-xs uppercase tracking-wider text-muted-foreground">
                            Reason for override <span className="text-destructive">*</span>
                        </Label>
                        <Textarea
                            rows={2}
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            placeholder="e.g. Family emergency — short-staffed but covered by bank worker"
                            className="mt-1.5"
                            data-testid="override-reason"
                        />
                    </div>

                    <div className="flex items-start gap-2 pt-1">
                        <Checkbox
                            id="override-ack"
                            checked={ack}
                            onCheckedChange={(v) => setAck(!!v)}
                            data-testid="override-ack"
                        />
                        <Label htmlFor="override-ack" className="text-xs leading-4 font-normal">
                            I understand this breaks <code className="font-mono">max_one_per_role_on_al</code> and I accept responsibility for the resulting rota clash.
                        </Label>
                    </div>
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="override-cancel">
                        Cancel
                    </Button>
                    <Button
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        disabled={!ack || !reason.trim()}
                        onClick={() => onConfirm(reason.trim())}
                        data-testid="override-confirm"
                    >
                        Accept with override
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}


/**
 * Conflict chips shown inline on the /requests Pending row. Three states:
 *  - Same-role clash → red "⚠ <initials> (<role>) <type>" chip per clashing staff
 *  - Different-role leave on same date → amber "ℹ <initials> (<role>) <type>"
 *  - Slot completely open → green "✓ Open"
 * The manager sees FULL conflict context before clicking anything.
 */
function RequestConflictChips({ req }) {
    if (!req.conflicts) return <span className="text-xs text-muted-foreground">—</span>;
    const { slot_open, existing_leave = [], reason } = req.conflicts;
    const reqRole = req.staff_role;
    const same = [];
    const other = [];
    for (const e of existing_leave) {
        if (e.staff_initials === req.staff_initials) continue;
        if (reqRole && e.role && e.role.toLowerCase() === reqRole.toLowerCase()) same.push(e);
        else other.push(e);
    }
    if (slot_open && same.length === 0 && other.length === 0) {
        return (
            <Badge variant="outline" className="text-xs" title="No conflicts — safe to accept">
                ✓ Open
            </Badge>
        );
    }
    return (
        <div className="flex flex-wrap gap-1 max-w-[260px]" title={reason || ""}>
            {same.map((e) => (
                <Badge
                    key={`s-${e.staff_initials}`}
                    className="text-[10px] font-medium"
                    style={{
                        background: "hsl(var(--accent-red) / 0.12)",
                        color: "hsl(var(--accent-red))",
                        border: "1px solid hsl(var(--accent-red) / 0.4)",
                    }}
                >
                    ⚠ {e.staff_initials}{e.role ? ` (${e.role})` : ""} {e.type}
                </Badge>
            ))}
            {other.map((e) => (
                <Badge
                    key={`o-${e.staff_initials}`}
                    className="text-[10px] font-medium"
                    style={{
                        background: "hsl(38 95% 55% / 0.14)",
                        color: "hsl(38 95% 28%)",
                        border: "1px solid hsl(38 95% 55% / 0.4)",
                    }}
                >
                    ℹ {e.staff_initials}{e.role ? ` (${e.role})` : ""} {e.type}
                </Badge>
            ))}
            {slot_open && same.length === 0 && other.length > 0 && (
                <Badge variant="outline" className="text-[10px]" title="No hard rule conflict — info only">
                    OK to accept
                </Badge>
            )}
        </div>
    );
}

/**
 * InspectRequestSheet — side panel that fetches /api/requests/{id}/inspect
 * and renders:
 *   • Request summary (staff, date, pref, notes)
 *   • All leave on that date (red if same role, amber otherwise)
 *   • Current rota assignments for that day (if any rota covers it)
 * Gives the manager a single-pane view to decide Accept / Reject without
 * clicking away.
 */
function InspectRequestSheet({ req, onOpenChange }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    useEffect(() => {
        if (!req?.id) { setData(null); return; }
        setLoading(true);
        api.get(`/requests/${req.id}/inspect`)
            .then((r) => setData(r.data))
            .catch((e) => toast.error(formatApiError(e)))
            .finally(() => setLoading(false));
    }, [req?.id]);

    return (
        <Sheet open={!!req} onOpenChange={onOpenChange}>
            <SheetContent className="sm:max-w-lg overflow-y-auto" data-testid="inspect-sheet">
                <SheetHeader>
                    <SheetTitle className="flex items-center gap-2">
                        <Eye className="w-4 h-4" /> Day context
                    </SheetTitle>
                    <SheetDescription>
                        Full rota picture for the day before deciding.
                    </SheetDescription>
                </SheetHeader>
                {loading && <div className="p-4 text-sm text-muted-foreground">Loading…</div>}
                {data && (
                    <div className="mt-4 space-y-5 text-sm">
                        <div className="app-card p-3 space-y-1">
                            <div className="font-semibold">{data.request.staff_initials}
                                {data.staff_full_name && <span className="text-muted-foreground"> — {data.staff_full_name}</span>}
                            </div>
                            <div className="text-xs text-muted-foreground flex items-center gap-2">
                                <CalIcon className="w-3 h-3" />
                                {data.request.date}
                                {data.staff_role && <Badge variant="outline" className="text-[10px]">{data.staff_role}</Badge>}
                            </div>
                            <div className="flex items-center gap-2 text-xs">
                                <span className="text-muted-foreground">Preference:</span>
                                <Badge>{data.request.shift_preference}</Badge>
                            </div>
                            {data.request.notes && (
                                <div className="text-xs italic text-muted-foreground mt-1">"{data.request.notes}"</div>
                            )}
                        </div>

                        <InspectSection
                            title={`Leave on ${data.request.date}`}
                            empty="No one else is on leave / training this day."
                            rows={data.day_leave}
                            render={(e, idx) => {
                                const sameRole = data.staff_role && e.role && e.role.toLowerCase() === data.staff_role.toLowerCase();
                                return (
                                    <div key={idx} className="flex items-center justify-between gap-2 text-xs py-1 border-b last:border-0" style={{ borderColor: "hsl(var(--border))" }}>
                                        <div className="flex items-center gap-2">
                                            <span className="font-semibold">{e.staff_initials}</span>
                                            {e.role && <span className="text-muted-foreground">({e.role})</span>}
                                        </div>
                                        <Badge
                                            className="text-[10px]"
                                            style={sameRole ? {
                                                background: "hsl(var(--accent-red) / 0.12)",
                                                color: "hsl(var(--accent-red))",
                                                border: "1px solid hsl(var(--accent-red) / 0.4)",
                                            } : { background: "hsl(38 95% 55% / 0.14)", color: "hsl(38 95% 28%)", border: "1px solid hsl(38 95% 55% / 0.4)" }}
                                        >
                                            {sameRole ? "⚠ same role" : "ℹ"} {e.type}
                                        </Badge>
                                    </div>
                                );
                            }}
                        />

                        <InspectSection
                            title={data.rota_title ? `Scheduled on "${data.rota_title}"` : "No rota covers this date yet"}
                            empty="Generate a rota that includes this date to see assignments."
                            rows={data.day_assignments}
                            render={(a, idx) => (
                                <div key={idx} className="flex items-center justify-between gap-2 text-xs py-1 border-b last:border-0" style={{ borderColor: "hsl(var(--border))" }}>
                                    <div className="flex items-center gap-2">
                                        <span className="font-semibold">{a.staff_initials}</span>
                                        {a.role && <span className="text-muted-foreground">({a.role})</span>}
                                    </div>
                                    <Badge variant="outline" className="font-mono text-[10px]">{a.shift || "—"}</Badge>
                                </div>
                            )}
                        />
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}

function InspectSection({ title, rows, render, empty }) {
    return (
        <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">{title}</div>
            <div className="app-card p-3">
                {(!rows || rows.length === 0)
                    ? <div className="text-xs text-muted-foreground italic">{empty}</div>
                    : rows.map(render)}
            </div>
        </div>
    );
}

