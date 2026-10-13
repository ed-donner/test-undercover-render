import { LogOut } from "lucide-react";
import { signOut } from "../auth";

export function SignOutButton({ className }: Readonly<{ className: string }>) {
  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        void signOut();
      }}
    >
      <LogOut />
      Sign out
    </button>
  );
}
