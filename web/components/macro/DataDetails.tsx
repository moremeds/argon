import type { ReactNode } from "react";

import type {
  BoardQuestions,
  PanelBasis,
} from "./domain/BoardPanel";
import { basisLabel } from "./presentation";

export function DataDetails({
  basis,
  questions,
  sourceLabel = "Source",
  source,
}: {
  basis: PanelBasis;
  questions: BoardQuestions;
  sourceLabel?: string;
  source: ReactNode;
}) {
  return (
    <details
      className="data-details"
      data-testid="macro-data-details"
      data-questions={questions.join(" ")}
      data-basis={basis}
    >
      <summary>Data details</summary>
      <div className="data-details-body">
        <span className={`basis basis-${basis.toLowerCase()}`}>
          {basisLabel(basis)}
        </span>
        <span>
          <b>{sourceLabel}</b> {source}
        </span>
      </div>
    </details>
  );
}
