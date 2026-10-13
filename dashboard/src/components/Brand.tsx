import { ShieldCheck } from "lucide-react";

// UnderCover's mark, name and the dashboard's tagline, as the header and the
// sign-in page show them.
export function Brand() {
  return (
    <>
      <ShieldCheck />
      UnderCover <span className="tagline">claims</span>
    </>
  );
}
