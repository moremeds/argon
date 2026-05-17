import { Clock } from "lucide-react";

type Props = {
  name: "CRI" | "VCG";
  description: string;
};

export default function PendingSubTab({ name, description }: Props) {
  return (
    <div
      className="regime-pending"
      data-testid={`regime-pending-${name.toLowerCase()}`}
    >
      <Clock size={48} strokeWidth={1.5} />
      <h2>{name} — coming soon</h2>
      <p>{description}</p>
      <p className="regime-pending-link">
        Pending IB-via-R2 reader integration. See the long-term roadmap (
        <code>docs/superpowers/plans/2026-05-16-port-regime-from-xenon.md</code>
        ) for the full plan.
      </p>
    </div>
  );
}
