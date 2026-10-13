import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { api, type RecipeDetails } from "../api";
import { VersionChip } from "../components/Chips";
import { Approval } from "../components/Approval";
import { DiffView } from "../components/DiffView";
import { PageHeader } from "../components/PageHeader";
import { StateMessage } from "../components/StateMessage";
import { dateTime } from "../format";
import { IMPROVEMENT } from "../paths";
import { REFRESH_MS, useLoad } from "../useLoad";

export function RecipePage() {
  const { number = "" } = useParams();
  const load = useCallback(() => api.getRecipe(number), [number]);
  const { data: recipe, error } = useLoad(load, REFRESH_MS);

  if (!recipe)
    return (
      <>
        <PageHeader
          eyebrow={<Link to={IMPROVEMENT}>Improvement</Link>}
          title={`Recipe ${number}`}
        />
        <StateMessage
          error={error}
          notFound="Recipe not found. Choose one on the Improvement page."
        />
      </>
    );

  return (
    <>
      <PageHeader
        eyebrow={<Link to={IMPROVEMENT}>Improvement</Link>}
        title={`Recipe ${String(recipe.number)}`}
        status={recipe.current && <VersionChip status="current" />}
      />
      <div className="column">
        <RecipeFacts recipe={recipe} />
        <section className="panel" aria-labelledby="changes-title">
          <h2 id="changes-title">
            {recipe.number === 1
              ? "What changed"
              : `What changed from recipe ${String(recipe.number - 1)}`}
          </h2>
          {recipe.diff === null ? (
            <p className="muted">
              This is the first recipe, so there's nothing before it to compare.
            </p>
          ) : (
            <DiffView diff={recipe.diff} />
          )}
        </section>
        <section className="panel" aria-labelledby="recipe-title">
          <h2 id="recipe-title">Recipe</h2>
          <pre className="instructions">{recipe.recipe}</pre>
        </section>
      </div>
    </>
  );
}

function RecipeFacts({ recipe }: Readonly<{ recipe: RecipeDetails }>) {
  return (
    <section className="panel" aria-labelledby="facts-title">
      <h2 id="facts-title">Details</h2>
      <dl className="facts">
        <div>
          <dt>Proposed by</dt>
          <dd>{recipe.proposed_by}</dd>
        </div>
        <div>
          <dt>Approved</dt>
          <dd>
            <Approval by={recipe.approved_by} at={recipe.approved_at} />
          </dd>
        </div>
        <div>
          <dt>Made</dt>
          <dd>{dateTime(recipe.created_at)}</dd>
        </div>
        <div className="fact-wide">
          <dt>Reason</dt>
          <dd>{recipe.reason}</dd>
        </div>
      </dl>
    </section>
  );
}
