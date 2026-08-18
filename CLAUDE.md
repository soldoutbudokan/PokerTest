# CLAUDE.md

## Git identity

All commits are authored as `soldoutbudokan <68517314+soldoutbudokan@users.noreply.github.com>`,
never as Claude. A SessionStart hook in `.claude/settings.json` sets this, but verify before
your first commit: if `git config user.name` prints `Claude`, run

    git config --global user.name 'soldoutbudokan'
    git config --global user.email '68517314+soldoutbudokan@users.noreply.github.com'

and amend any commit you already made (`git commit --amend --reset-author --no-edit`).
Do not add `Co-Authored-By: Claude`, `Claude-Session:`, or "Generated with Claude Code"
lines to commit messages or PR bodies.
