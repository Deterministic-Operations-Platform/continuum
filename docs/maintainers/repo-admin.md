# Maintainer repo admin

## GitHub repository transfer (CLI)

If you need to transfer this repository from a personal namespace to an organization, use the GitHub REST API through `gh api`:

```bash
gh auth login

gh api \
  -X POST \
  -H "Accept: application/vnd.github+json" \
  repos/nnabdelshahid/continuum/transfer \
  -f new_owner="Deterministic-Operations-Platform" \
  -f new_name="continuum"
```

Then update your local remote URL:

```bash
git remote set-url origin git@github.com:Deterministic-Operations-Platform/continuum.git
# or HTTPS:
# git remote set-url origin https://github.com/Deterministic-Operations-Platform/continuum.git
```

Notes:
- `new_name` is optional if `continuum` is available in the destination org.
- The caller needs admin access to the source repo and permission to create repos in the target org.
- Some org policies require owner acceptance before transfer completion.
