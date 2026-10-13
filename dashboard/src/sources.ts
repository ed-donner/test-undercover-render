// A context file a lookup came from, with that file's source: what both the
// claim agent's steps and the Copilot's cards show of the context layer.
export interface Source {
  file: string;
  system: string;
  owner: string;
  reviewed: string;
}
