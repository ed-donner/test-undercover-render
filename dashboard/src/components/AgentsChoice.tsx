// The most claim agents a dispatch or an evaluation works at once, as the
// backend allows, and how many a form offers first.
export const MOST_AGENTS = 25;
export const FIRST_CHOICE = 3;
const CHOICES = Array.from({ length: MOST_AGENTS }, (_, index) => index + 1);

export function AgentsChoice({
  agents,
  onChange,
}: Readonly<{ agents: number; onChange: (agents: number) => void }>) {
  return (
    <label>
      Claim agents at once
      <select
        value={agents}
        onChange={(event) => {
          onChange(Number(event.target.value));
        }}
      >
        {CHOICES.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    </label>
  );
}
