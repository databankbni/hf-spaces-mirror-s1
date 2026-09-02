import React from "react";

interface SectionCardProps {
  title: string;
  children: React.ReactNode;
}

export const SectionCard: React.FC<SectionCardProps> = ({ title, children }) => {
  return (
    <div className="bg-card border border-border rounded-2xl p-4 gap-3.5 shadow-sm relative overflow-hidden flex flex-col">
      <h3 className="text-xs font-bold text-muted-foreground uppercase">{title}</h3>
      {children}
    </div>
  );
};
