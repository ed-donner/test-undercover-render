import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { App } from "./App";
import type {
  Claim,
  ClaimSummary,
  Handler,
  Policy,
  PreviousClaim,
  Settings,
  SettingsPage,
} from "./api";

// Stands in for the backend: answers "METHOD /path" with the JSON given, or
// with the status and detail given as an error, and a 404 for anything else.
export type Routes = Record<string, unknown>;

export class Refusal {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {}
}

const dana: Handler = {
  handler_id: "HND-01",
  name: "Dana Whitfield",
  role: "Senior Claims Handler",
  email: "dana.whitfield@undercover.example",
  can_approve_over_limit: true,
};

export const marcus: Handler = {
  handler_id: "HND-02",
  name: "Marcus Oyelaran",
  role: "Claims Handler",
  email: "marcus.oyelaran@undercover.example",
  can_approve_over_limit: false,
};

const startingSettings: Settings = {
  number: 1,
  approval_limit: 1000,
  objectives: { accuracy: 0.6, grade: 1 },
  noise: {
    accuracy: 0.1,
    grade: 0.15,
    cost_per_claim: 0.15,
    seconds_per_claim: 0.15,
  },
  tolerance: {
    accuracy: 0.1,
    grade: 0.15,
    cost_per_claim: 1,
    seconds_per_claim: 0.25,
  },
  spending_limit: 0.5,
  agents: 25,
  changed_by: null,
  changed_at: "2026-10-04T09:00:00+00:00",
};

export const settings: SettingsPage = {
  current: startingSettings,
  changes: [startingSettings],
  models_allowed: [
    {
      model: "openai/gpt-6-luna",
      reasoning_efforts: ["none", "low", "medium"],
      input_price: 0.1,
      output_price: 0.5,
    },
  ],
};

// Every page is signed in as Dana unless the routes say otherwise.
export function stubApi(routes: Routes) {
  const signedIn: Routes = {
    "GET /api/me": dana,
    "GET /api/settings": settings,
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    const answer = { ...signedIn, ...routes }[
      `${init?.method ?? "GET"} ${path}`
    ];
    if (answer === undefined)
      return Promise.resolve(
        Response.json({ detail: "Not found" }, { status: 404 }),
      );
    if (answer instanceof Refusal)
      return Promise.resolve(
        Response.json({ detail: answer.detail }, { status: answer.status }),
      );
    return Promise.resolve(Response.json(answer));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// The bodies of the requests sent to "METHOD /path", in order.
export function sent(fetchMock: ReturnType<typeof stubApi>, route: string) {
  return fetchMock.mock.calls
    .filter(([path, init]) => `${init?.method ?? "GET"} ${path}` === route)
    .map(([, init]) =>
      typeof init?.body === "string"
        ? (JSON.parse(init.body) as unknown)
        : undefined,
    );
}

export function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

// Matches the element whose whole text is the text given, even when its words
// are split across elements, such as an amount set in mono.
export function wholeText(text: string) {
  return (_: string, element: Element | null) =>
    element?.textContent === text &&
    [...element.children].every((child) => child.textContent !== text);
}

// Finds the panel headed by the given heading, to look inside it.
export async function panel(heading: string) {
  return within(await screen.findByRole("region", { name: heading }));
}

export const claim: Claim = {
  claim_id: "CLM-1002",
  policy_id: "POL-2002",
  customer_id: "CUS-3002",
  customer_name: "Tom Becker",
  claim_type: "baggage",
  submitted_on: "2026-07-20",
  incident_date: "2026-06-21",
  incident_location: "Frankfurt, Germany",
  summary: "Suitcase lost on a connecting flight",
  story: "My suitcase never arrived in Prague.",
  items: [
    { description: "Hard-shell suitcase", category: "luggage", amount: 280 },
    { description: "Wool suit", category: "clothing", amount: 870 },
  ],
  amount_claimed: 1150,
  documents: [
    {
      name: "Lost baggage report",
      type: "carrier_report",
      content: "One checked bag not delivered.",
    },
  ],
  status: "waiting",
  thread_id: null,
  attempts: 0,
  evaluation_id: null,
  copy_of: null,
  decision: null,
  payment: null,
  sent_back_decisions: [],
};

export const summary: ClaimSummary = {
  claim_id: "CLM-1002",
  customer_name: "Tom Becker",
  claim_type: "baggage",
  summary: "Suitcase lost on a connecting flight",
  amount_claimed: 1150,
  submitted_on: "2026-07-20",
  status: "waiting",
  decision: null,
  payout: null,
  resuming: false,
};

export const policy: Policy = {
  policy_id: "POL-2002",
  customer_id: "CUS-3002",
  plan: "premium",
  add_ons: ["electronics_plus"],
  purchased_on: "2026-05-02",
  sold_through: "UnderCover website",
  trip: {
    destination: "Prague, Czech Republic",
    departs_on: "2026-06-20",
    returns_on: "2026-06-30",
    trip_cost: 2400,
  },
  travelers: ["Tom Becker"],
  status: "active",
};

export const history: PreviousClaim[] = [
  {
    claim_id: "CLM-0412",
    filed_on: "2024-08-19",
    incident_date: "2024-08-09",
    claim_type: "baggage_delay",
    summary: "Checked bag arrived 30 hours late in Lisbon",
    outcome: "approved",
    amount_paid: 140,
  },
];
