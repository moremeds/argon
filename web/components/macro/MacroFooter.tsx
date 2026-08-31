export function MacroFooter({ snapshotAsOf }: { snapshotAsOf: string | null }) {
  return (
    <footer>
      <div className="wrap">
        Live snapshot {snapshotAsOf ?? "unavailable"} · data details stay with
        the panel they describe.
      </div>
    </footer>
  );
}
