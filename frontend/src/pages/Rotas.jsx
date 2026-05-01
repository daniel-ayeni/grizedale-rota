import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, ArrowRight, Copy, Calendar, Trash2, CheckSquare, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";

export default function Rotas() {
    const navigate = useNavigate();
    const [rotas, setRotas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [open, setOpen] = useState(false);
    const [creating, setCreating] = useState(false);
    const [defaultStart, setDefaultStart] = useState("");
    const [form, setForm] = useState({ start_date: "", weeks: 4, title: "" });

    // Multi-select state. When any rotas are selected, a bulk-delete bar
    // appears. Locked from running on `published` rotas — those need to
    // be unpublished first to be removed.
    const [selectMode, setSelectMode] = useState(false);
    const [selected, setSelected] = useState(() => new Set());
    const [confirmDelete, setConfirmDelete] = useState(null);  // { ids: [...], multi: bool }

    const load = async () => {
        setLoading(true);
        try {
            const [rotasRes, settingsRes] = await Promise.all([
                api.get("/rotas"),
                api.get("/settings"),
            ]);
            setRotas(rotasRes.data);
            const start = settingsRes.data?.rota_start_date_default || "";
            setDefaultStart(start);
            setForm((f) => ({ ...f, start_date: start }));
        } catch (e) {
            toast.error(formatApiError(e));
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => { load(); }, []);

    const create = async (e) => {
        e.preventDefault();
        setCreating(true);
        try {
            const { data } = await api.post("/rotas", form);
            toast.success("Rota created");
            setOpen(false);
            navigate(`/rotas/${data.id}`);
        } catch (err) {
            toast.error(formatApiError(err));
        } finally {
            setCreating(false);
        }
    };

    const createAndCopy = async () => {
        try {
            const start = form.start_date || defaultStart;
            const { data } = await api.post("/rotas", {
                start_date: start, weeks: 4,
                title: `Copy from previous (${start})`,
            });
            const copy = await api.post(`/rotas/${data.id}/copy-from-previous`);
            const h = copy.data?.validation_report?.summary?.hard ?? 0;
            toast.success(`Copied ${copy.data.assignments_count} cells. ${h} hard violations introduced.`);
            navigate(`/rotas/${data.id}`);
        } catch (err) {
            toast.error(formatApiError(err));
        }
    };

    const toggleSelect = (id) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };
    const selectAll = () => {
        // Select only deletable (non-published) rotas; published need to
        // be unpublished first.
        const deletable = rotas.filter((r) => r.status !== "published").map((r) => r.id);
        if (selected.size === deletable.length) {
            setSelected(new Set());
        } else {
            setSelected(new Set(deletable));
        }
    };

    const requestDelete = (rota) => {
        if (rota.status === "published") {
            toast.warning("This rota is published. Unpublish it first to delete.");
            return;
        }
        setConfirmDelete({ ids: [rota.id], multi: false, sample: rota });
    };
    const requestBulkDelete = () => {
        if (selected.size === 0) return;
        setConfirmDelete({ ids: Array.from(selected), multi: true });
    };

    const doDelete = async () => {
        if (!confirmDelete) return;
        const ids = confirmDelete.ids;
        let ok = 0;
        for (const id of ids) {
            try {
                await api.delete(`/rotas/${id}`);
                ok += 1;
            } catch (err) {
                toast.error(`Failed to delete ${id.slice(0, 8)}: ${formatApiError(err)}`);
            }
        }
        toast.success(ok === 1 ? "Rota deleted" : `${ok} rotas deleted`);
        setConfirmDelete(null);
        setSelected(new Set());
        setSelectMode(false);
        load();
    };

    return (
        <div className="space-y-6" data-testid="rotas-page">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                    <h1 className="display text-3xl font-semibold">Rotas</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Build and edit 4-week rotas. Copy from a previous cycle to save time.
                    </p>
                </div>
                <div className="flex gap-2 flex-wrap">
                    <Button
                        variant="outline"
                        onClick={() => { setSelectMode((v) => !v); setSelected(new Set()); }}
                        data-testid="rotas-select-toggle"
                    >
                        {selectMode
                            ? <CheckSquare className="w-4 h-4 mr-1.5" />
                            : <Square className="w-4 h-4 mr-1.5" />}
                        {selectMode ? "Cancel select" : "Select multiple"}
                    </Button>
                    <Button variant="outline" onClick={createAndCopy} data-testid="rotas-copy-from-previous">
                        <Copy className="w-4 h-4 mr-1.5" /> Copy from previous
                    </Button>
                    <Dialog open={open} onOpenChange={setOpen}>
                        <DialogTrigger asChild>
                            <Button className="btn-primary" data-testid="rotas-new-button">
                                <Plus className="w-4 h-4 mr-1.5" /> New rota
                            </Button>
                        </DialogTrigger>
                        <DialogContent data-testid="rotas-new-dialog">
                            <DialogHeader>
                                <DialogTitle>New rota</DialogTitle>
                                <DialogDescription>Create an empty 4-week rota you can fill in manually or copy from a previous cycle.</DialogDescription>
                            </DialogHeader>
                            <form onSubmit={create} className="space-y-3">
                                <div>
                                    <Label className="text-xs uppercase tracking-wider text-muted-foreground">Title (optional)</Label>
                                    <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="mt-1.5" data-testid="rotas-form-title" />
                                </div>
                                <div>
                                    <Label className="text-xs uppercase tracking-wider text-muted-foreground">Start date</Label>
                                    <Input type="date" required value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} className="mt-1.5" data-testid="rotas-form-start" />
                                </div>
                                <DialogFooter>
                                    <Button type="submit" className="btn-primary" disabled={creating} data-testid="rotas-form-submit">
                                        {creating ? "Creating…" : "Create"}
                                    </Button>
                                </DialogFooter>
                            </form>
                        </DialogContent>
                    </Dialog>
                </div>
            </div>

            {/* Bulk-action bar — visible when any rotas are selected */}
            {selectMode && selected.size > 0 && (
                <div className="bulk-action-toolbar" data-testid="rotas-bulk-bar" style={{ position: "static", display: "inline-flex" }}>
                    <span className="count" data-testid="rotas-bulk-count">{selected.size}</span>
                    <span className="count-staff">rota{selected.size === 1 ? "" : "s"} selected</span>
                    <Button size="sm" variant="outline" onClick={selectAll} data-testid="rotas-bulk-select-all">
                        {selected.size === rotas.filter((r) => r.status !== "published").length
                            ? "Clear selection"
                            : "Select all deletable"}
                    </Button>
                    <Button size="sm" variant="destructive" onClick={requestBulkDelete} data-testid="rotas-bulk-delete">
                        <Trash2 className="w-3.5 h-3.5 mr-1.5" /> Delete selected
                    </Button>
                </div>
            )}

            <div className="section-header" data-testid="rotas-section-header">All rotas · {rotas.length}</div>

            <div className="app-card overflow-x-auto" data-testid="rotas-table-wrap">
                <Table className="paper-table" data-testid="rotas-table">
                    <TableHeader>
                        <TableRow>
                            {selectMode && <TableHead style={{ width: 40 }}></TableHead>}
                            <TableHead>Start date</TableHead>
                            <TableHead className="hidden md:table-cell">Title</TableHead>
                            <TableHead>Weeks</TableHead>
                            <TableHead>Status</TableHead>
                            <TableHead className="hidden lg:table-cell">Updated</TableHead>
                            <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && <TableRow><TableCell colSpan={selectMode ? 7 : 6} className="text-center py-8 text-sm text-muted-foreground">Loading…</TableCell></TableRow>}
                        {!loading && rotas.length === 0 && (
                            <TableRow><TableCell colSpan={selectMode ? 7 : 6} className="text-center py-8 text-sm text-muted-foreground">No rotas yet — create one to get started.</TableCell></TableRow>
                        )}
                        {rotas.map((r) => {
                            const isPublished = r.status === "published";
                            return (
                                <TableRow key={r.id} data-testid={`rota-row-${r.id}`}>
                                    {selectMode && (
                                        <TableCell>
                                            <Checkbox
                                                checked={selected.has(r.id)}
                                                onCheckedChange={() => toggleSelect(r.id)}
                                                disabled={isPublished}
                                                aria-label={isPublished ? "Published rotas cannot be selected" : "Select rota"}
                                                data-testid={`rota-${r.id}-checkbox`}
                                            />
                                        </TableCell>
                                    )}
                                    <TableCell className="font-medium">
                                        <span className="inline-flex items-center gap-2">
                                            <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
                                            {r.start_date}
                                        </span>
                                    </TableCell>
                                    <TableCell className="hidden md:table-cell text-sm">{r.title || "—"}</TableCell>
                                    <TableCell>{r.weeks}</TableCell>
                                    <TableCell>
                                        <Badge variant={isPublished ? "default" : "outline"}>{r.status}</Badge>
                                    </TableCell>
                                    <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">{r.updated_at?.slice(0, 16).replace("T", " ")}</TableCell>
                                    <TableCell className="text-right">
                                        <div className="inline-flex items-center gap-1">
                                            <Link to={`/rotas/${r.id}`} data-testid={`rota-${r.id}-open`}>
                                                <Button size="sm" variant="ghost">
                                                    Open <ArrowRight className="w-4 h-4 ml-1" />
                                                </Button>
                                            </Link>
                                            <Button
                                                size="icon"
                                                variant="ghost"
                                                onClick={() => requestDelete(r)}
                                                title={isPublished
                                                    ? "Unpublish before deleting"
                                                    : "Delete rota"}
                                                aria-label="Delete rota"
                                                data-testid={`rota-${r.id}-delete`}
                                            >
                                                <Trash2 className="w-4 h-4 text-muted-foreground hover:text-destructive" />
                                            </Button>
                                        </div>
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </div>

            {/* Confirm-delete dialog (single + bulk) */}
            <AlertDialog
                open={!!confirmDelete}
                onOpenChange={(o) => { if (!o) setConfirmDelete(null); }}
            >
                <AlertDialogContent data-testid="rotas-delete-confirm">
                    <AlertDialogHeader>
                        <AlertDialogTitle>
                            {confirmDelete?.multi
                                ? `Delete ${confirmDelete.ids.length} rota${confirmDelete.ids.length === 1 ? "" : "s"}?`
                                : `Delete rota '${confirmDelete?.sample?.start_date}'?`}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                            {confirmDelete?.multi
                                ? `Permanently removes ${confirmDelete.ids.length} draft rotas. This cannot be undone.`
                                : `Permanently removes the draft rota '${confirmDelete?.sample?.title || confirmDelete?.sample?.start_date}' (status: ${confirmDelete?.sample?.status}). This cannot be undone.`}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel data-testid="rotas-delete-cancel">Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={doDelete}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            data-testid="rotas-delete-confirm-btn"
                        >
                            Delete
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
