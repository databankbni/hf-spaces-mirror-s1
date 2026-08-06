interface TelemetryChannel {
  label: string;
  value: string;
  note: string;
}

export function TelemetryQueue({
  sectionNumber,
  title,
  description,
  channels,
}: {
  sectionNumber: string;
  title: string;
  description: string;
  channels: TelemetryChannel[];
}) {
  return (
    <section id="telemetry-queue" className="section telemetry-queue">
      <div className="section-head">
        <span>{sectionNumber}</span>
        <h2>{title}</h2>
      </div>
      <p>{description}</p>
      <div className="queue-board">
        {channels.map((ch) => (
          <article key={ch.label}>
            <b>{ch.label}</b>
            <strong>{ch.value}</strong>
            <span>{ch.note}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
