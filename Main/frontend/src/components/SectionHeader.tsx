interface SectionHeaderProps {
  step?: number;
  title: string;
  lead?: string;
  id?: string;
}

export function SectionHeader({ step, title, lead, id }: SectionHeaderProps) {
  return (
    <header className="section-header" id={id}>
      {step != null && <span className="section-step">{step}</span>}
      <div>
        <h2 className="section-title">{title}</h2>
        {lead && <p className="section-lead">{lead}</p>}
      </div>
    </header>
  );
}
