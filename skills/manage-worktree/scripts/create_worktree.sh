#!/usr/bin/env bash
# Usage: create_worktree.sh <repo_root> <branch> <build_type>
#   repo_root  — absolute path to the main git repo
#   branch     — branch to check out in the new worktree
#   build_type — Debug | RelWithDebInfo | Release
set -euo pipefail

if ! command -v direnv &>/dev/null; then
    echo "Error: direnv is required but not installed." >&2
    echo "Install it from https://direnv.net, then hook it into your shell:" >&2
    echo "  echo 'eval \"\$(direnv hook zsh)\"' >> ~/.zshrc && source ~/.zshrc" >&2
    exit 1
fi

REPO_ROOT="$1"
BRANCH="$2"
BUILD_TYPE="$3"

REPO_NAME="$(basename "$REPO_ROOT")"
REPO_PARENT="$(dirname "$REPO_ROOT")"
WORKTREES_DIR="$REPO_PARENT/$REPO_NAME-worktrees"
WORKTREE_PATH="$WORKTREES_DIR/$REPO_NAME-$BRANCH"
BUILD_TYPE_LOWER="$(echo "$BUILD_TYPE" | tr '[:upper:]' '[:lower:]')"
BUILD_PATH="$WORKTREE_PATH/build-$BUILD_TYPE_LOWER"

# --- Phase 2: create worktree ---
mkdir -p "$WORKTREES_DIR"

if [ -d "$WORKTREE_PATH" ]; then
    existing_branch="$(git -C "$WORKTREE_PATH" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    if [ "$existing_branch" = "$BRANCH" ]; then
        echo "Worktree already exists at $WORKTREE_PATH, reconfiguring build."
    else
        WORKTREE_PATH="${WORKTREE_PATH}-2"
        BUILD_PATH="$WORKTREE_PATH/build-$BUILD_TYPE_LOWER"
        git -C "$REPO_ROOT" worktree add -b "$BRANCH" "$WORKTREE_PATH" HEAD
    fi
elif git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$REPO_ROOT" worktree add "$WORKTREE_PATH" "$BRANCH"
elif git -C "$REPO_ROOT" show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    git -C "$REPO_ROOT" fetch origin "$BRANCH"
    git -C "$REPO_ROOT" worktree add "$WORKTREE_PATH" -b "$BRANCH" "origin/$BRANCH"
else
    git -C "$REPO_ROOT" worktree add -b "$BRANCH" "$WORKTREE_PATH" HEAD
fi

# --- Phase 3: configure cmake ---
# Toolchain file appends the flag rather than replacing CMAKE_CXX_FLAGS wholesale.
# CMAKE_CURRENT_LIST_DIR resolves to the worktree root at configure time.
cat > "$WORKTREE_PATH/worktree.cmake" <<'EOF'
string(APPEND CMAKE_C_FLAGS   " -fdebug-prefix-map=${CMAKE_CURRENT_LIST_DIR}=.")
string(APPEND CMAKE_CXX_FLAGS " -fdebug-prefix-map=${CMAKE_CURRENT_LIST_DIR}=.")
EOF

CCACHE_BASEDIR="$WORKTREE_PATH" cmake \
    -S "$WORKTREE_PATH" \
    -B "$BUILD_PATH" \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_TOOLCHAIN_FILE="$WORKTREE_PATH/worktree.cmake" \
    -G Ninja \
    -DLINKER=mold \
    -DBUILD_TESTING=On \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=On

# --- Phase 4: write .envrc and activate direnv ---
cat > "$WORKTREE_PATH/.envrc" <<'EOF'
export CCACHE_BASEDIR="$(pwd)"
EOF
direnv allow "$WORKTREE_PATH"

# --- Phase 5: summary ---
cat <<EOF

Worktree ready.

  Location  : $WORKTREE_PATH
  Build dir : $BUILD_PATH
  Branch    : $BRANCH
  Build type: $BUILD_TYPE

To build:
  cmake --build $BUILD_PATH [-- -j\$(nproc)]

ccache sharing : CCACHE_BASEDIR set automatically via direnv on cd
Debug paths    : -fdebug-prefix-map remaps DWARF paths to relative
EOF
