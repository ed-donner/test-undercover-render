import { CircleAlert } from "lucide-react";
import type { ReactNode } from "react";

// Why the backend refused what a handler asked, or why the request failed,
// shown where they asked it and read out as soon as it shows.
export function FormError({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <p className="form-error" role="alert">
      <CircleAlert />
      <span>{children}</span>
    </p>
  );
}
