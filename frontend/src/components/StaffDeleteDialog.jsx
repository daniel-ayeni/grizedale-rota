import { useEffect, useState } from "react";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
    AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { AlertTriangle, Loader2 } from "lucide-react";
import api, { formatApiError } from "@/lib/api";
import { toast } from "sonner";

/**
 * Staff deletion dialog that fetches /api/staff/{id}/references first and
 * shows a detailed list of what will be affected. The manager must tick
 * "I understand" before the Delete button activates, preventing accidental
 * loss of history. Rules that reference the staff auto-drop the missing
 * initials at solve time — the dialog surfaces those explicitly.
 */
export default function StaffDeleteDialog({ row, open, onOpenChange, onDeleted }) {
    const [refs, setRefs] = useState(null);
    const [loading, setLoading] = useState(false);
    const [acknowledged, setAcknowledged] = useState(false);
    const [deleting, setDeleting] = useState(false);

    useEffect(() => {
        if (!open || !row?.id) return;
        setRefs(null);
        setAcknowledged(false);
        setLoading(true);
        api.get(`/staff/${row.id}/references`)
            .then((res) => setRefs(res.data))
            .catch((err) => toast.error(formatApiError(err)))
            .finally(() => setLoading(false));
    }, [open, row?.id]);

    const handleDelete = async () => {
        setDeleting(true);
        try {
            await api.delete(`/staff/${row.id}`);
            toast.success(`${row.initials} deleted`);
            onDeleted?.(row);
            onOpenChange(false);
        } catch (err) {
            toast.error(formatApiError(err));
        } finally {
            setDeleting(false);
        }
    };

    const hasReferences = refs && (
        (refs.rule_references?.length || 0) > 0 ||
        (refs.assignments_count || 0) > 0 ||
        (refs.leave_count || 0) > 0 ||
        (refs.requests_count || 0) > 0 ||
        (refs.active_tokens_count || 0) > 0
    );

    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent data-testid="staff-delete-dialog">
                <AlertDialogHeader>
                    <AlertDialogTitle className="flex items-center gap-2">
                        <AlertTriangle className="w-5 h-5 text-destructive" />
                        Delete {row?.initials}?
                    </AlertDialogTitle>
                    <AlertDialogDescription asChild>
                        <div className="space-y-3 text-sm">
                            {loading && (
                                <div className="flex items-center gap-2 text-muted-foreground">
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Checking references…
                                </div>
                            )}
                            {refs && !hasReferences && (
                                <div className="text-muted-foreground">
                                    <strong>{row?.initials} — {row?.full_name}</strong> is not referenced anywhere.
                                    Safe to delete.
                                </div>
                            )}
                            {refs && hasReferences && (
                                <>
                                    <div>
                                        Deleting <strong>{row?.initials} — {row?.full_name}</strong> will
                                        orphan the following references:
                                    </div>
                                    <div className="rounded-md border p-3 space-y-2 text-xs" style={{ borderColor: "hsl(var(--border))" }}>
                                        <RefRow label="Rota shift assignments (historic + current)" count={refs.assignments_count} hint="kept for audit but no new shifts will be scheduled." />
                                        <RefRow label="Leave / training entries" count={refs.leave_count} hint="historic leave remains on record." />
                                        <RefRow label="Pending / resolved requests" count={refs.requests_count} hint="history preserved." />
                                        <RefRow label="Active request-link tokens" count={refs.active_tokens_count} hint="become dead links." />
                                        {refs.rule_references?.length > 0 && (
                                            <div className="pt-2 border-t" style={{ borderColor: "hsl(var(--border))" }}>
                                                <div className="font-semibold mb-1 text-destructive">
                                                    Rules naming this staff explicitly ({refs.rule_references.length})
                                                </div>
                                                <ul className="list-disc list-inside space-y-0.5 text-muted-foreground">
                                                    {refs.rule_references.map((r) => (
                                                        <li key={r.rule_id}>
                                                            <code className="font-mono text-xs">{r.rule_id}</code> <span className="text-[10px] uppercase">({r.mode})</span>
                                                        </li>
                                                    ))}
                                                </ul>
                                                <div className="mt-1 italic">
                                                    Solver auto-drops the missing initials at solve time, but consider editing these rules to remove the stale reference.
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </>
                            )}
                            {refs && hasReferences && (
                                <div className="flex items-start gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
                                    <Checkbox
                                        id="staff-delete-confirm"
                                        checked={acknowledged}
                                        onCheckedChange={(v) => setAcknowledged(!!v)}
                                        data-testid="staff-delete-ack"
                                    />
                                    <Label htmlFor="staff-delete-confirm" className="text-xs leading-4">
                                        I understand — delete {row?.initials} and orphan the references above.
                                    </Label>
                                </div>
                            )}
                        </div>
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel data-testid="staff-delete-cancel">Cancel</AlertDialogCancel>
                    <AlertDialogAction
                        onClick={(e) => { e.preventDefault(); handleDelete(); }}
                        disabled={deleting || (hasReferences && !acknowledged) || loading}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        data-testid="staff-delete-confirm-btn"
                    >
                        {deleting ? "Deleting…" : "Delete"}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}

function RefRow({ label, count, hint }) {
    if (!count) return null;
    return (
        <div className="flex items-start justify-between gap-3">
            <div>
                <div>{label}</div>
                {hint && <div className="text-[10px] text-muted-foreground italic">{hint}</div>}
            </div>
            <div className="tabular-nums font-semibold shrink-0">{count}</div>
        </div>
    );
}
