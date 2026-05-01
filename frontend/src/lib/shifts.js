/* Shift constants + theme-aware cell styling helpers
   Used by the rota grid editor and any place that displays a shift cell.
*/

export const SHIFT_TYPES = ["D", "D*", "N", "*", "OFF", "AL", "TRN"];

/* Click-cycle (single click on a cell):
   blank -> D -> D* -> N -> * -> blank
   AL/TRN/OFF are deliberately NOT in the click cycle — those are leave
   states the manager toggles via the right-click popover, not by mis-clicking.
   "OFF" is also excluded because blank is the natural "not working" state in
   the paper rota; OFF is reserved for explicit manager intent (set via popover).
*/
export const CYCLE = ["", "D", "D*", "N", "*"];

export function nextShift(current) {
    const idx = CYCLE.indexOf(current ?? "");
    if (idx < 0) return "D";  // anything not in cycle (OFF/AL/TRN) -> start at D
    return CYCLE[(idx + 1) % CYCLE.length];
}

/* Popover groupings — Working / Off / Leave. AL/TRN are visually demoted to
   the "Leave" group so they're never the first option a user sees. */
export const SHIFT_GROUPS = {
    Working: ["D", "D*", "N", "*"],
    Off: ["", "OFF"],
    Leave: ["AL", "TRN"],
};

export const SHIFT_LABEL = {
    "": "—",
    D: "D",
    "D*": "D*",
    N: "N",
    "*": "*",
    OFF: "OFF",
    AL: "AL",
    TRN: "T",
};

export const SHIFT_HOURS = {
    D: 12,
    "D*": 14,
    N: 12,
    "*": 0,
    OFF: 0,
    AL: 0,
    TRN: 0,
    "": 0,
};

/** Tailwind-ish class string per shift type. Uses CSS variables from
    index.css so paper / modern themes both work without branching. */
export function shiftCellClass(shift) {
    const base = "shift-cell";
    return `${base} shift-${(shift || "blank").replace("*", "star")}`;
}

export const DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

export function ymd(d) {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
}

export function parseYmd(s) {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
}

export function addDays(date, n) {
    const d = new Date(date);
    d.setDate(d.getDate() + n);
    return d;
}

export function dayLetter(date) {
    return DAY_LETTERS[(date.getDay() + 6) % 7];
}

export function isWeekend(date) {
    const dow = date.getDay();
    return dow === 0 || dow === 6;
}
