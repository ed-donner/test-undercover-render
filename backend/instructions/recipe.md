1. Call read_results to see how the current version is doing and which evaluation claims it got wrong or explained poorly.
2. Look at the model and reasoning effort of the current version and of the version each earlier round tried. If one of the models allowed, at one of its reasoning efforts, hasn't been used by any of them, try it this round, starting with a higher reasoning effort on the current model. Keep the instructions as they are, so the round shows what the model and reasoning effort alone change, and go to step 4.
3. Otherwise, for each of those claims, add a rule to the instructions that would make the agent get that claim right, keeping the same model and reasoning effort.
4. Call propose_change with the new configuration.
5. Call run_evaluation to test the new version on both sets.
6. Improve this recipe, so that the next round makes a better change. Look at what happened in this round and in earlier rounds, then call propose_recipe with the new recipe. Keep this as the last step of the new recipe.
