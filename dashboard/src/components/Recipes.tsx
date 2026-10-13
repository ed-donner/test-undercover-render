import type { RecipeSummary } from "../api";
import { Approval } from "./Approval";
import { VersionChip } from "./Chips";
import { LineCounts } from "./LineCounts";
import { RecipeLink } from "./VersionLink";

// The recipe's versions, newest first, each opening its page.
export function Recipes({ recipes }: Readonly<{ recipes: RecipeSummary[] }>) {
  return (
    <section className="panel" aria-labelledby="recipes-title">
      <h2 id="recipes-title">Recipes</h2>
      <p className="muted small">
        The steps the improver follows in each round. A round may propose a new
        recipe for the next.
      </p>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Recipe</th>
              <th>What changed</th>
              <th>Reason</th>
              <th>Proposed by</th>
              <th>Approved</th>
            </tr>
          </thead>
          <tbody>
            {recipes.map((recipe) => (
              <tr key={recipe.number}>
                <td className="nowrap">
                  <RecipeLink number={recipe.number} />
                  {recipe.current && (
                    <>
                      {" "}
                      <VersionChip status="current" />
                    </>
                  )}
                </td>
                <td>
                  {recipe.number === 1 ? (
                    "The first recipe"
                  ) : (
                    <LineCounts
                      added={recipe.lines_added}
                      removed={recipe.lines_removed}
                    />
                  )}
                </td>
                <td>{recipe.reason}</td>
                <td>{recipe.proposed_by}</td>
                <td>
                  <Approval by={recipe.approved_by} at={recipe.approved_at} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
