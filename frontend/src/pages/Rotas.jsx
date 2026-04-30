import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, ArrowRight, Copy, Calendar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
    Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
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

    return (
        <div className="space-y-6" data-testid="rotas-page">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                    <h1 className="display text-3xl font-semibold">Rotas</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Build and edit 4-week rotas. Copy from a previous cycle to save time.
                    </p>
                </div>
                <div className="flex gap-2">
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

            <div className="section-header" data-testid="rotas-section-header">All rotas · {rotas.length}</div>

            <div className="app-card overflow-x-auto" data-testid="rotas-table-wrap">
                <Table className="paper-table" data-testid="rotas-table">
                    <TableHeader>
                        <TableRow>
                            <TableHead>Start date</TableHead>
                            <TableHead className="hidden md:table-cell">Title</TableHead>
                            <TableHead>Weeks</TableHead>
                            <TableHead>Status</TableHead>
                            <TableHead className="hidden lg:table-cell">Updated</TableHead>
                            <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && <TableRow><TableCell colSpan={6} className="text-center py-8 text-sm text-muted-foreground">Loading…</TableCell></TableRow>}
                        {!loading && rotas.length === 0 && (
                            <TableRow><TableCell colSpan={6} className="text-center py-8 text-sm text-muted-foreground">No rotas yet — create one to get started.</TableCell></TableRow>
                        )}
                        {rotas.map((r) => (
                            <TableRow key={r.id} data-testid={`rota-row-${r.id}`}>
                                <TableCell className="font-medium">
                                    <span className="inline-flex items-center gap-2">
                                        <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
                                        {r.start_date}
                                    </span>
                                </TableCell>
                                <TableCell className="hidden md:table-cell text-sm">{r.title || "—"}</TableCell>
                                <TableCell>{r.weeks}</TableCell>
                                <TableCell>
                                    <Badge variant={r.status === "published" ? "default" : "outline"}>
                                        {r.status}
                                    </Badge>
                                </TableCell>
                                <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">{r.updated_at?.slice(0, 16).replace("T", " ")}</TableCell>
                                <TableCell className="text-right">
                                    <Link to={`/rotas/${r.id}`} data-testid={`rota-${r.id}-open`}>
                                        <Button size="sm" variant="ghost">
                                            Open <ArrowRight className="w-4 h-4 ml-1" />
                                        </Button>
                                    </Link>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}
