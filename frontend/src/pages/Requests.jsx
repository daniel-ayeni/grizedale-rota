import { useEffect, useMemo, useState } from "react";
import { Plus, Check, X as XIcon, Pencil, Link as LinkIcon, Copy, Trash2 } from "lucide-react";
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

    const resolveOne = async (req, status) => {
        try {
            await api.patch(`/requests/${req.id}`, { status });
            toast.success(status === "accepted" ? "Accepted" : status === "rejected" ? "Rejected" : "Updated");
            load();
        } catch (err) { toast.error(formatApiError(err)); }
    };
    const resolveBulk = async (status) => {
        if (selected.size === 0) return;
        try {
            const res = await api.post("/requests/bulk", { ids: Array.from(selected), status });
            toast.success(`${res.data?.updated?.length || 0} updated${res.data?.leave_created ? ` · ${res.data.leave_created} leave entries created` : ""}`);
            load();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    const toggleSel = (id) => setSelected((s) => {
        const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
    });

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

            {tab === "pending" && selected.size > 0 && (
                <div className="app-card p-3 flex items-center justify-between" data-testid="bulk-bar">
                    <div className="text-sm">{selected.size} selected</div>
                    <div className="flex gap-2">
                        <Button size="sm" variant="outline" onClick={() => resolveBulk("rejected")} data-testid="bulk-reject"><XIcon className="w-3.5 h-3.5 mr-1" />Reject</Button>
                        <Button size="sm" className="btn-primary" onClick={() => resolveBulk("accepted")} data-testid="bulk-accept"><Check className="w-3.5 h-3.5 mr-1" />Accept</Button>
                    </div>
                </div>
            )}

            <div className="app-card overflow-x-auto" data-testid="requests-table-wrap">
                <Table className="paper-table" data-testid="requests-table">
                    <TableHeader>
                        <TableRow>
                            {tab === "pending" && <TableHead className="w-[40px]" />}
                            <TableHead>Staff</TableHead>
                            <TableHead>Date</TableHead>
                            <TableHead>Preference</TableHead>
                            <TableHead className="hidden md:table-cell">Notes</TableHead>
                            <TableHead>Source</TableHead>
                            <TableHead>Status</TableHead>
                            <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {reqs.length === 0 && <TableRow><TableCell colSpan={tab === "pending" ? 8 : 7} className="text-center py-8 text-sm text-muted-foreground">No requests</TableCell></TableRow>}
                        {reqs.map((r) => (
                            <TableRow key={r.id} data-testid={`req-row-${r.id}`}>
                                {tab === "pending" && (
                                    <TableCell>
                                        <Checkbox checked={selected.has(r.id)} onCheckedChange={() => toggleSel(r.id)} data-testid={`req-${r.id}-select`} />
                                    </TableCell>
                                )}
                                <TableCell className="font-semibold">{r.staff_initials}</TableCell>
                                <TableCell>{r.date}</TableCell>
                                <TableCell><Badge variant="outline">{PREFS.find((p) => p.value === r.shift_preference)?.label || r.shift_preference}</Badge></TableCell>
                                <TableCell className="hidden md:table-cell text-sm text-muted-foreground max-w-xs truncate">{r.notes || "—"}</TableCell>
                                <TableCell><span className="text-xs uppercase">{r.source}</span></TableCell>
                                <TableCell><Badge variant={STATUS_BADGE[r.status] || "outline"}>{r.status}</Badge></TableCell>
                                <TableCell className="text-right">
                                    {r.status === "pending" ? (
                                        <div className="flex justify-end gap-1">
                                            <Button size="sm" variant="ghost" onClick={() => resolveOne(r, "accepted")} data-testid={`req-${r.id}-accept`}><Check className="w-4 h-4 text-green-600" /></Button>
                                            <Button size="sm" variant="ghost" onClick={() => resolveOne(r, "rejected")} data-testid={`req-${r.id}-reject`}><XIcon className="w-4 h-4 text-destructive" /></Button>
                                        </div>
                                    ) : (
                                        <span className="text-xs text-muted-foreground">{r.resolution_note || ""}</span>
                                    )}
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
            const fullUrl = `${window.location.origin}${data.url}`;
            await navigator.clipboard.writeText(fullUrl).catch(() => {});
            toast.success("Link copied to clipboard");
            onChange();
        } catch (err) { toast.error(formatApiError(err)); }
    };

    const copyOne = async (token) => {
        const url = `${window.location.origin}/r/${token}`;
        await navigator.clipboard.writeText(url).catch(() => {});
        toast.success("Link copied");
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
                        const fullUrl = `${window.location.origin}/r/${t.token}`;
                        return (
                            <div key={t.id} className="p-2 rounded border space-y-1.5" style={{ borderColor: "hsl(var(--border))" }} data-testid={`link-row-${t.id}`}>
                                <div className="flex items-center justify-between gap-2">
                                    <div className="min-w-0">
                                        <div className="text-sm font-semibold">{t.staff_initials}</div>
                                        <div className="text-xs text-muted-foreground">expires {t.expires_at?.slice(0, 10)}</div>
                                    </div>
                                    <div className="flex gap-1 shrink-0">
                                        <Button size="sm" variant="outline" onClick={() => copyOne(t.token)} data-testid={`link-copy-${t.id}`}>
                                            <Copy className="w-3.5 h-3.5 mr-1" /> Copy link
                                        </Button>
                                        <Button size="sm" variant="ghost" onClick={() => revoke(t.id)} data-testid={`link-revoke-${t.id}`} title="Revoke link">
                                            <Trash2 className="w-4 h-4 text-destructive" />
                                        </Button>
                                    </div>
                                </div>
                                {/* Short path chip — what the staff member needs */}
                                <code
                                    className="block px-2 py-1 rounded font-mono text-sm font-semibold cursor-pointer select-all"
                                    style={{ background: "hsl(var(--bg-elev))", color: "hsl(var(--primary))" }}
                                    onClick={() => copyOne(t.token)}
                                    data-testid={`link-short-${t.id}`}
                                    title="Click to copy full link"
                                >
                                    /r/{t.token}
                                </code>
                                <div className="text-[10px] text-muted-foreground truncate select-all" title={fullUrl}>
                                    {fullUrl}
                                </div>
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
