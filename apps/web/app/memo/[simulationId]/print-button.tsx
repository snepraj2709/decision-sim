"use client";

export function PrintButton() {
  return (
    <button
      className="print-hide px-4 py-2 rounded text-[13px] font-medium"
      style={{ background: "var(--ink)", color: "var(--bg)" }}
      onClick={() => window.print()}
    >
      Print / Export PDF
    </button>
  );
}
