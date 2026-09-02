import React from "react";

interface PageHeaderProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, icon }) => {
  return (
    <div className="flex flex-col gap-1 select-none">
      <div className="flex items-center gap-2.5">
        {icon && (
          <div className="bg-gradient-to-tr from-violet-600 via-indigo-600 to-accent p-1.5 rounded-lg text-white">
            {icon}
          </div>
        )}
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">{title}</h1>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
    </div>
  );
};
