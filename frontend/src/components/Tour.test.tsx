import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TOUR_STEPS, Tour, type TourStep } from "./Tour";

const STEPS: TourStep[] = [
  { title: "Hello", body: <p>Intro</p> },
  { target: "map", title: "The map", body: <p>Dots</p> },
  { target: "sidebar", panel: "risk", title: "Risk", body: <p>Scores</p> },
];

afterEach(cleanup);

describe("Tour", () => {
  it("steps forward and back, switching tabs as steps ask", async () => {
    const onPanel = vi.fn();
    const onClose = vi.fn();
    render(<Tour steps={STEPS} startPanel="now" onPanel={onPanel} onClose={onClose} />);
    expect(screen.getByRole("dialog", { name: "Hello" })).toBeTruthy();
    expect(onPanel).toHaveBeenLastCalledWith("now");

    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(screen.getByText("Step 2 of 3")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "Risk" })).toBeTruthy();
    expect(onPanel).toHaveBeenLastCalledWith("risk");

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(onPanel).toHaveBeenLastCalledWith("now");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(onClose).toHaveBeenCalled();
    expect(onPanel).toHaveBeenLastCalledWith("now");
  });

  it("moves with the arrow keys and closes on Escape", () => {
    const onClose = vi.fn();
    render(<Tour steps={STEPS} startPanel="overview" onPanel={() => {}} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "The map" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByRole("dialog", { name: "Hello" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("as a single pointer, closes when the control it points at is pressed", async () => {
    const onClose = vi.fn();
    render(
      <>
        <button data-tour="tab-risk">Risk</button>
        <Tour steps={[{ target: "tab-risk", title: "Risk", body: <p>Scores</p> }]} startPanel="now" onPanel={() => {}} onClose={onClose} />
      </>,
    );
    expect(screen.queryByText(/Step 1/)).toBeNull();
    expect(screen.getByRole("button", { name: "Got it" })).toBeTruthy();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Risk" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("can be skipped from any step", async () => {
    const onClose = vi.fn();
    render(<Tour startPanel="now" onPanel={() => {}} onClose={onClose} />);
    expect(screen.getByText(`Step 1 of ${TOUR_STEPS.length}`)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    expect(onClose).toHaveBeenCalled();
  });
});
