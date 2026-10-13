import { beforeEach, vi } from "vitest";
import { startSession } from "./fakeAuth";

// The tests never reach Supabase Auth: they sign in through a stand-in, and
// start each test signed in.
vi.mock("./auth", () => import("./fakeAuth"));

beforeEach(() => {
  startSession();
  localStorage.clear();
});

// jsdom has no modal dialogs, so the tests stand in for opening and closing
// one.
HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
  this.open = true;
};
HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
  this.open = false;
};
// Nor does it scroll, so the tests stand in for bringing an element into view.
Element.prototype.scrollIntoView = () => undefined;
