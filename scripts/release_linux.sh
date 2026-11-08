#!/usr/bin/env bash
# Build locally and upload through gh; never dispatch a workflow.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-}"
case "$MODE" in
  --help)
    echo "Usage: ./scripts/release_linux.sh [--build-only|--publish-only]"
    echo "Default: build locally, verify, push source/tag, and publish on GitHub."
    exit 0 ;;
  ""|--build-only|--publish-only) ;;
  *) echo "Unknown option: $MODE" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo "Only one option is supported." >&2
  exit 2
fi
if [ "$MODE" != --publish-only ]; then
  ./scripts/build_linux.sh
fi
if [ "$MODE" = --build-only ]; then
  exit 0
fi
command -v gh >/dev/null
gh auth status
PYTHON="$ROOT/.venv-release/bin/python"
VERSION="$("$PYTHON" -c 'from desktop_buddy import __version__; print(__version__)')"
TAG="v$VERSION"
RELEASE_DIR="$ROOT/dist/releases/$TAG"
NOTES="$ROOT/docs/releases/$TAG.md"
REPO="rajm012/Desktop-Buddy"
"$PYTHON" scripts/linux_release.py validate "$RELEASE_DIR"
if [ ! -f "$NOTES" ]; then
  echo "Write release notes in $NOTES before publishing." >&2
  exit 1
fi
if [ "$(git branch --show-current)" != main ]; then
  echo "Publish from main after merging your changes." >&2
  exit 1
fi
if [ "$(gh repo view --json nameWithOwner --jq .nameWithOwner)" != "$REPO" ]; then
  echo "origin must point to $REPO." >&2
  exit 1
fi
# Fail before pushing if GitHub cannot be queried or this version is public.
# Draft releases can be resumed after an interrupted upload.
DRAFT="$(gh api --paginate "repos/$REPO/releases?per_page=100" \
  --jq ".[] | select(.tag_name == \"$TAG\") | .draft")"
if [ "$DRAFT" = false ]; then
  echo "$TAG is already published; use a new version." >&2
  exit 1
fi
if git rev-parse --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  if [ "$(git rev-list -n 1 "$TAG")" != "$(git rev-parse HEAD)" ]; then
    echo "$TAG already points to another commit; bump the version." >&2
    exit 1
  fi
else
  git tag -a "$TAG" -m "Desktop Buddy $VERSION for Linux"
fi
git push origin HEAD:main "refs/tags/$TAG"
if [ -z "$DRAFT" ]; then
  gh release create "$TAG" --repo "$REPO" --verify-tag --draft \
    --title "Desktop Buddy $VERSION — Linux" --notes-file "$NOTES"
fi
gh release upload "$TAG" --repo "$REPO" --clobber \
  "$RELEASE_DIR/desktop-buddy-$VERSION-linux-x86_64.tar.gz" \
  "$RELEASE_DIR/desktop_buddy-$VERSION.tar.gz" \
  "$RELEASE_DIR/desktop_buddy-$VERSION-py3-none-any.whl" \
  "$RELEASE_DIR/BUILD_INFO.json" "$RELEASE_DIR/SHA256SUMS"
gh release edit "$TAG" --repo "$REPO" --draft=false --latest \
  --title "Desktop Buddy $VERSION — Linux" --notes-file "$NOTES"
gh release view "$TAG" --repo "$REPO" --json url --jq .url
