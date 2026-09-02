type Props = {
  rank: number;
  className?: string;
  label?: string;
};

const MEDALS: Record<number, string> = {
  1: "\u{1F947}",
  2: "\u{1F948}",
  3: "\u{1F949}",
};

export function RankingMedal({ rank, className = "", label }: Props) {
  const medal = MEDALS[rank];
  if (!medal) return null;

  const accessibleLabel = label || `Rank ${rank}`;

  return (
    <data
      className={`${className} rank-${rank}`.trim()}
      value={rank}
      role="img"
      aria-label={accessibleLabel}
      title={accessibleLabel}
    >
      {medal}
    </data>
  );
}
