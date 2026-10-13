// The backend's paths to a run and a round, shared by the tests' requests and
// the stand-in for the agent.
export const runPath = (runId: string) => `/api/runs/${runId}`;
export const roundPath = (roundId: string) => `/api/rounds/${roundId}`;
