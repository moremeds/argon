import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Body } from "@/components/flash/Body";
import { tickerSet } from "@/lib/flash/tickers";

const spans = (root: HTMLElement) =>
  [...root.querySelectorAll("span")].map((s) => s.textContent);

/**
 * A ticker in a sentence is highlighted; an uppercase word that is not a
 * ticker is left alone. The set is the whole test — nothing about `SPY` and
 * `ET` distinguishes them by shape, and a page that guessed would turn every
 * "ET" and "OAS" helium writes into a symbol.
 */
describe("Body ticker highlighting", () => {
  it("wraps SPY and leaves ET as prose", () => {
    const { container } = render(
      <Body
        text="SPY closed at 772.33 before the 16:00 ET print."
        tickers={tickerSet()}
      />,
    );
    expect(spans(container)).toEqual(["SPY"]);
    expect(container.textContent).toBe(
      "SPY closed at 772.33 before the 16:00 ET print.",
    );
  });

  it("wraps a name only this page knows about", () => {
    const text = "CRWD held above entry into the close.";
    // Not on the static list: without the page's own set it is just a word.
    const plain = render(<Body text={text} />);
    expect(spans(plain.container)).toEqual([]);

    const { container } = render(
      <Body text={text} tickers={tickerSet(["CRWD"])} />,
    );
    expect(spans(container)).toEqual(["CRWD"]);
    expect(container.textContent).toBe(text);
  });
});
