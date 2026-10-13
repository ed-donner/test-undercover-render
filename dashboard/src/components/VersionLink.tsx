import { Link } from "react-router";
import { recipePage, versionPage } from "../paths";

// A link to one version of the claim agent, such as "Version 3".
export function VersionLink({ number }: Readonly<{ number: number }>) {
  return <Link to={versionPage(number)}>Version {number}</Link>;
}

// A link to one version of the improver's recipe, such as "Recipe 2".
export function RecipeLink({ number }: Readonly<{ number: number }>) {
  return <Link to={recipePage(number)}>Recipe {number}</Link>;
}
