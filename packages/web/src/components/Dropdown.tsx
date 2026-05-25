import { useEffect, useRef, useState, type ReactNode } from "react";

type Props = {
  label: string;
  summary: string;
  children: ReactNode;
};

// Minimal popover dropdown — keep behavior tight: open on button click,
// close on outside click or Escape. No fancy animation or focus trap
// because the contents fit on screen and the popover is short-lived.
export function Dropdown({ label, summary, children }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="dropdown" ref={ref}>
      <button
        className={`dropdown-trigger ${open ? "on" : ""}`}
        onClick={() => setOpen((x) => !x)}
        aria-expanded={open}
      >
        <span className="dropdown-label">{label}</span>
        <span className="dropdown-summary">{summary}</span>
        <span className="dropdown-caret">▾</span>
      </button>
      {open && <div className="dropdown-panel">{children}</div>}
    </div>
  );
}
