# Git guide for the coding agent

How to help the student share their work in a pull request (PR) and pull the latest code. The student can follow it too.

The student may be on Windows (PowerShell) or a Mac; every command here works on both.

The course uses `git checkout` to change branches, never `git switch`, so use `git checkout` too.

## Sharing work in a pull request

Ed often encourages students to share their work with a PR that adds it to `community_contributions/`. Other students learn from it, and the student is credited on GitHub as a contributor to the repo. Ed's overview of the steps is at https://edwarddonner.com/pr.

### 1. Fork the repo and set the remotes

The student cloned `ed-donner/undercover`, so `origin` is Ed's repo. Keep it as `origin`: the course pulls from it and reads Ed's branches as `origin/<branch>`. Add the student's fork as a second remote to push to.

1. On GitHub, the student forks https://github.com/ed-donner/undercover to their own account, leaving **Copy the main branch only** ticked.
2. Add the fork: `git remote add fork https://github.com/<username>/undercover.git`
3. Check with `git remote -v`: `origin` is `ed-donner/undercover` and `fork` is the student's.

If `origin` is already the student's fork, because they cloned the fork, add Ed's repo with `git remote add upstream https://github.com/ed-donner/undercover.git`. Then read `upstream` wherever this guide says `origin`, and `origin` wherever it says `fork`.

### 2. A self-contained change goes in a folder of its own

For a change that stands on its own, such as an improved lab or a few modules, the files go in a folder named for the student inside `community_contributions/`:

```
community_contributions/<student_name>/my_improved_lab3.ipynb
```

The PR comes from a new branch that starts at Ed's latest `main`, so it carries nothing else from the student's work:

1. Copy the files into `community_contributions/<student_name>/`.
2. Commit or stash everything else, so that `git status` shows only the new folder.
3. Make the branch. The new folder comes with you, since git leaves untracked files alone:
   ```
   git fetch origin
   git checkout --no-track -b <student_name>-<topic> origin/main
   ```

### 3. Clear the notebook outputs

Every notebook in the PR has its outputs cleared. In VS Code or Cursor, the student can press **Clear All Outputs** in the notebook's toolbar and save. Or run this on each notebook:

```
uv run python -c "import sys, nbformat; p = sys.argv[1]; nb = nbformat.read(p, as_version=4); [c.update(outputs=[], execution_count=None) for c in nb.cells if c.cell_type == 'code']; nbformat.write(nb, p)" <notebook>
```

### 4. Commit, check and submit

```
git add community_contributions/<student_name>
git commit -m "<what it is>"
git diff --numstat origin/main...HEAD
```

`--numstat` lists each file in the PR with its lines added and deleted. Before submitting, check all of these:

- Under 5 files
- Under 2,000 lines changed in total
- No file changed outside `community_contributions/`
- No lines deleted
- No API keys or `.env` contents, no unnecessary test files, no wordy README or `.env.example`, and no emojis or other LLM artifacts

If the PR fails a check, fix it, or share a write-up instead (step 5). Then push the branch to the fork:

```
git push -u fork <student_name>-<topic>
```

On GitHub, the fork's page offers **Compare & pull request**. The base repository is `ed-donner/undercover` and the base branch `main`. Give the PR a short title and a line or two on what it is. With the GitHub CLI, `gh pr create --repo ed-donner/undercover --base main --head <username>:<student_name>-<topic>` does the same.

Afterwards, go back to the branch the student was working on with `git checkout <branch>`, and run `git stash pop` if they stashed.

### 5. A bigger change: share a write-up

When the work is bigger than that, such as the student's own version of a build, the PR adds a single Markdown file instead, in `community_contributions/` or a folder inside it. It describes the change and the student's takeaways, and links to the work in their fork.

1. Push the branch with the work to the fork: `git push -u fork <their-branch>`. The link is `https://github.com/<username>/undercover/tree/<their-branch>`.
2. Make the PR with the Markdown file alone, following steps 2 and 4.

### 6. A fix to a bug in the repo

A fix to Ed's code, a lab or a guide is welcome as a PR outside `community_contributions/`. Unless the fix is obvious, the student checks with Ed first, in the course's Q&A on Udemy or by email to ed@edwarddonner.com.

Branch from the branch with the bug: `origin/main` for a lab or a guide, or the day branch for a bug in Ed's build. Make the smallest change that fixes it, clear any notebook outputs, and open the PR against that branch, saying what was wrong.

## Pulling the latest code

Ed adds improvements to the course over time. To bring them in:

1. `git status` shows the student's local changes.
2. Set them aside, one of two ways:
   - If the student doesn't need them: `git stash`. They stay in the stash, where `git stash pop` brings them back and `git stash drop` deletes them.
   - To keep them: `git add -A`, then `git commit -m "My changes"`.
3. `git pull --no-rebase` brings in Ed's latest for the current branch, merging it with any commits of the student's. On a branch of the student's own, use `git pull --no-rebase origin main`.
4. If git reports conflicts, `git status` lists the files. In each one, keep the right lines, delete the conflict markers, then `git add` the file. For a notebook, take one side whole: `git checkout --theirs <file>` for Ed's version or `git checkout --ours <file>` for the student's, then `git add` it. When every file is added, `git commit` finishes the merge. `git merge --abort` goes back to before the pull.
5. Run `uv sync` and `npm install`, in case the dependencies changed.
