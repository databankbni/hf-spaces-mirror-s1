interface OpsCheck {
  label: string;
}

export function OpsStack({
  sectionNumber,
  title,
  description,
  checks,
}: {
  sectionNumber: string;
  title: string;
  description: string;
  checks: OpsCheck[];
}) {
  return (
    <section id="ops-stack" className="section ops-stack">
      <div className="section-head">
        <span>{sectionNumber}</span>
        <h2>{title}</h2>
      </div>
      <p>{description}</p>
      <ul>
        {checks.map((c) => (
          <li key={c.label}>{c.label}</li>
        ))}
      </ul>
    </section>
  );
}
