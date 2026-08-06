interface Phase {
  label: string;
  value: number;
}

export function PhaseMonitor({
  sectionNumber,
  title,
  description,
  phases,
}: {
  sectionNumber: string;
  title: string;
  description: string;
  phases: Phase[];
}) {
  return (
    <section id="phase-monitor" className="section phase-monitor">
      <div className="section-head">
        <span>{sectionNumber}</span>
        <h2>{title}</h2>
      </div>
      <p>{description}</p>
      <div className="phase-bars">
        {phases.map((p) => (
          <span key={p.label} style={{ "--p": p.value } as React.CSSProperties}>
            {p.label}
          </span>
        ))}
      </div>
    </section>
  );
}
