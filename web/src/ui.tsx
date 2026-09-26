/* Shared UI atoms for the Studio rail.  Before this file every group re-spelled its own
   title div (`.ap-title`, `.iw-title`, `.fld-lbl`), which is why the headings drifted apart
   in weight and colour — a title that is `--ink-faint` reads as disabled text, not as a label.
   One component, one colour, everywhere. */
import type { ReactNode } from "react";
import { t } from "./i18n";

export function Panel({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="ui-panel">
      <h3 className="ui-panel-title">{title}{note ? <span className="ui-panel-note">{note}</span> : null}</h3>
      {children}
    </section>
  );
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ui-row">
      <span className="ui-row-label">{label}</span>
      <div className="ui-row-body">{children}</div>
    </div>
  );
}

/** A real switch: role="switch" + aria-checked, so screen readers announce the state and the
    keyboard can reach it.  A styled checkbox cannot say what it is. */
export function Switch({ label, checked, onChange, hint }: {
  label: string; checked: boolean; onChange: (next: boolean) => void; hint?: string;
}) {
  return (
    <div className="ui-row">
      <span className="ui-row-label">{label}</span>
      <div className="ui-row-body">
        <button type="button" role="switch" aria-checked={checked} className={`ui-switch ${checked ? "on" : ""}`}
          onClick={() => onChange(!checked)}>
          <span className="ui-switch-knob" /><span className="ui-switch-txt">{checked ? "ON" : "OFF"}</span>
        </button>
        {hint ? <span className="ui-hint">{hint}</span> : null}
      </div>
    </div>
  );
}

/** The rail's tab strip: one group visible at a time instead of a 1500px scroll. */
export function RailMenu<T extends string>({ items, active, onChange }: {
  items: { id: T; label: string; badge?: string | number }[]; active: T; onChange: (id: T) => void;
}) {
  return (
    <div className="ui-rail-menu" role="tablist" aria-label={t("编辑面板")}>
      {items.map((it) => (
        <button key={it.id} type="button" role="tab" id={`rail-tab-${it.id}`}
          aria-selected={active === it.id} aria-controls={`rail-panel-${it.id}`}
          className={`ui-rail-tab ${active === it.id ? "on" : ""}`} onClick={() => onChange(it.id)}>
          {it.label}
          {it.badge !== undefined && it.badge !== "" ? <span className="ui-rail-badge">{it.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function RailPanel<T extends string>({ id, active, children }: { id: T; active: T; children: ReactNode }) {
  if (id !== active) return null;
  return <div className="ui-rail-panel" role="tabpanel" id={`rail-panel-${id}`} tabIndex={-1}>{children}</div>;
}
