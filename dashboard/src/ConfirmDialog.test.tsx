import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./components/ConfirmDialog";

afterEach(cleanup);

function renderDialog(open: boolean) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open={open}
      title="Save the settings?"
      confirmLabel="Save the settings"
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      <p>Spending limit: $0.50 to $0.75</p>
    </ConfirmDialog>,
  );
  return { onConfirm, onCancel };
}

it("is a modal dialog with a title, the changes and two buttons", () => {
  const showModal = vi.spyOn(HTMLDialogElement.prototype, "showModal");
  const { onConfirm } = renderDialog(true);
  expect(showModal).toHaveBeenCalledOnce();
  const dialog = screen.getByRole("dialog", { name: "Save the settings?" });
  expect((dialog as HTMLDialogElement).open).toBe(true);
  expect(screen.getByText("Spending limit: $0.50 to $0.75")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Save the settings" }));
  expect(onConfirm).toHaveBeenCalledOnce();
});

it("cancels with its button or with Escape", () => {
  const { onCancel } = renderDialog(true);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  // A browser fires cancel on the dialog when Escape is pressed.
  fireEvent(screen.getByRole("dialog"), new Event("cancel"));
  expect(onCancel).toHaveBeenCalledTimes(2);
});

it("stays closed until it is opened", () => {
  renderDialog(false);
  expect(screen.queryByRole("dialog")).toBeNull();
});
