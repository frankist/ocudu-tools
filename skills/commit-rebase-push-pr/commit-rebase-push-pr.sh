#!/usr/bin/env bash
#
# commit-rebase-push-pr.sh
# Implements the full commit, rebase, push, and create PR/MR workflow
#
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$SKILL_DIR/scripts"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
AUTO_YES=false
TITLE=""
TARGET_BRANCH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y)
      AUTO_YES=true
      shift
      ;;
    --title)
      TITLE="$2"
      shift 2
      ;;
    --target)
      TARGET_BRANCH="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# Helper function to prompt user
prompt_user() {
  local question="$1"
  local -a options=("${@:2}")
  local choice

  echo -e "${YELLOW}$question${NC}"
  for i in "${!options[@]}"; do
    echo "  $((i + 1)). ${options[$i]}"
  done

  while true; do
    read -p "Choose (1-${#options[@]}): " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#options[@]} ]; then
      echo $((choice - 1))
      return
    fi
    echo "Invalid choice. Please try again."
  done
}

# ============================================================================
# PHASE 1: Resolve branches
# ============================================================================
echo "Phase 1: Resolving branches..."

REMOTE_MAIN_BRANCH=$(git ls-remote --symref origin HEAD | awk '/^ref:/ { sub("refs/heads/", "", $2); print $2 }')
echo "  Remote main branch: $REMOTE_MAIN_BRANCH"

SOURCE_BRANCH=$(git branch --show-current)
echo "  Current branch: $SOURCE_BRANCH"

if [[ -z "$TARGET_BRANCH" ]]; then
  TARGET_BRANCH="$REMOTE_MAIN_BRANCH"
fi
echo "  Target branch: $TARGET_BRANCH"

# Check if we're on the target branch
if [[ "$SOURCE_BRANCH" == "$TARGET_BRANCH" ]]; then
  echo ""
  echo -e "${RED}You are currently on the target branch ('$TARGET_BRANCH'). To commit changes, you should work on a separate branch. What do you want to do?${NC}"

  choice=$(prompt_user "" "Stop" "Create and checkout a new branch")

  case $choice in
    0)
      echo "Stopping skill."
      exit 0
      ;;
    1)
      echo ""
      read -p "Enter new branch name: " new_branch

      # Validate branch name
      if [[ -z "$new_branch" ]] || [[ "$new_branch" =~ " " ]]; then
        echo -e "${RED}Error: Branch name cannot be empty or contain spaces.${NC}"
        exit 1
      fi
      if [[ "$new_branch" == "$TARGET_BRANCH" ]]; then
        echo -e "${RED}Error: Branch name cannot be the same as target branch.${NC}"
        exit 1
      fi

      git checkout -b "$new_branch"
      SOURCE_BRANCH="$new_branch"
      echo "Created and switched to branch: $SOURCE_BRANCH"
      ;;
  esac
fi

# ============================================================================
# PHASE 2: Add local changes to staging area
# ============================================================================
echo ""
echo "Phase 2: Checking for local changes..."

STATUS=$(git status --porcelain)

if [[ -z "$STATUS" ]]; then
  echo "  No changes detected. Skipping to Phase 4."
else
  # Check for untracked files
  UNTRACKED=$(echo "$STATUS" | grep "^??" | cut -c4- | head -10)
  UNTRACKED_COUNT=$(echo "$STATUS" | grep -c "^??" || true)

  if [[ $UNTRACKED_COUNT -gt 0 ]]; then
    echo ""
    echo "Found $UNTRACKED_COUNT untracked files:"
    if [[ $UNTRACKED_COUNT -gt 10 ]]; then
      echo "$UNTRACKED"
      echo "  ... and $((UNTRACKED_COUNT - 10)) more"
    else
      echo "$UNTRACKED"
    fi

    choice=$(prompt_user "What should I do?" "Abort" "Add all" "Delete all" "Exclude all")

    case $choice in
      0)
        echo "Aborting."
        exit 0
        ;;
      1)
        while IFS= read -r file; do
          git add "$file"
        done < <(echo "$STATUS" | grep "^??" | cut -c4-)
        echo "  Untracked files added."
        ;;
      2)
        read -p "Are you sure you want to delete all untracked files? (yes/no): " confirm
        if [[ "$confirm" == "yes" ]]; then
          while IFS= read -r file; do
            rm -rf "$file"
          done < <(echo "$STATUS" | grep "^??" | cut -c4-)
          echo "  Untracked files deleted."
        else
          echo "  Deletion cancelled."
        fi
        ;;
      3)
        mkdir -p .git/info
        while IFS= read -r file; do
          echo "$file" >> .git/info/exclude
        done < <(echo "$STATUS" | grep "^??" | cut -c4-)
        echo "  Untracked files excluded."
        ;;
    esac
  fi

  # Stage modified tracked files
  git add -u
  echo "  Staged modified tracked files."
fi

# ============================================================================
# PHASE 3: Commit with a good message
# ============================================================================
echo ""
echo "Phase 3: Creating commit..."

# Check if there are staged changes
STAGED=$(git diff --staged --name-only)
if [[ -z "$STAGED" ]]; then
  echo "  No staged changes. Skipping commit."
else
  # Show what's being committed
  echo "  Staged changes:"
  git diff --staged --name-status | sed 's/^/    /'

  # Always prompt for commit message when there are staged changes
  echo ""
  echo "  Enter commit message:"
  read -p "  Subject line: " subject_line

  if [[ -z "$subject_line" ]]; then
    echo -e "${RED}Error: Commit message cannot be empty.${NC}"
    exit 1
  fi

  echo "  Body (optional, enter blank line to finish):"
  body=""
  while IFS= read -r line; do
    if [[ -z "$line" ]]; then
      break
    fi
    if [[ -n "$body" ]]; then
      body="$body
$line"
    else
      body="$line"
    fi
  done

  if [[ -n "$body" ]]; then
    COMMIT_MSG="$subject_line

$body"
  else
    COMMIT_MSG="$subject_line"
  fi

  git commit -m "$COMMIT_MSG"
  echo "  Commit created."
fi

# ============================================================================
# PHASE 4: Rebase on target branch
# ============================================================================
echo ""
echo "Phase 4: Preparing to rebase on origin/$TARGET_BRANCH..."

if [[ $AUTO_YES == false ]]; then
  choice=$(prompt_user "Do you want to rebase your branch on origin/$TARGET_BRANCH?" "Yes" "No")
  if [[ $choice -eq 1 ]]; then
    echo "Stopping skill. Branch is ready for manual rebase."
    exit 0
  fi
fi

git fetch origin

if git rebase origin/"$TARGET_BRANCH"; then
  echo "  Rebase successful."
else
  git rebase --abort
  CONFLICTS=$(git diff --name-only --diff-filter=U || true)
  echo -e "${RED}Rebase conflicts detected in:${NC}"
  echo "$CONFLICTS" | sed 's/^/  /'
  echo "Please resolve them manually and re-run the skill."
  exit 1
fi

# ============================================================================
# PHASE 5: Push to remote
# ============================================================================
echo ""
echo "Phase 5: Pushing to remote..."

if [[ "$REMOTE_MAIN_BRANCH" == "$SOURCE_BRANCH" ]]; then
  echo -e "${RED}Error: It is forbidden to push to the remote main branch ($SOURCE_BRANCH).${NC}"
  exit 1
fi

git push origin --force-with-lease "$SOURCE_BRANCH"
echo "  Branch pushed to remote."

# ============================================================================
# PHASE 6: Detect platform and extract repository info
# ============================================================================
echo ""
echo "Phase 6: Detecting platform and extracting repository info..."

if [[ $AUTO_YES == false ]]; then
  choice=$(prompt_user "Do you want to create a PR/MR for your branch with target origin/$TARGET_BRANCH?" "Yes" "No")
  if [[ $choice -eq 1 ]]; then
    echo "Stopping skill. Branch is pushed and ready for manual PR/MR creation."
    exit 0
  fi
fi

GIT_REMOTE=$(git config --get remote.origin.url)
echo "  Git remote: $GIT_REMOTE"

# Detect platform
if [[ "$GIT_REMOTE" == *"github.com"* ]]; then
  PLATFORM="github"
elif [[ "$GIT_REMOTE" == *"gitlab"* ]]; then
  PLATFORM="gitlab"
else
  echo -e "${RED}Error: Unknown platform. Expected github.com or gitlab.${NC}"
  exit 1
fi
echo "  Platform: $PLATFORM"

# Extract repository information
if [[ "$PLATFORM" == "github" ]]; then
  # Extract owner/repo from https://github.com/owner/repo.git or git@github.com:owner/repo.git
  PROJECT_PATH=$(echo "$GIT_REMOTE" | sed -E 's|.*[:/]([^/]+)/([^/]+?)(\.git)?$|\1/\2|')
elif [[ "$PLATFORM" == "gitlab" ]]; then
  # Extract GitLab base URL and project path
  if [[ "$GIT_REMOTE" == "https://"* ]]; then
    GIT_REPO_BASE=$(echo "$GIT_REMOTE" | sed -E 's|^(https://[^/]+).*|\1|')
    PROJECT_PATH=$(echo "$GIT_REMOTE" | sed -E 's|^https://[^/]+/(.+?)(\.git)?$|\1|')
  else
    # SSH format: git@gitlab.com:path/to/project.git
    GIT_REPO_BASE=$(echo "$GIT_REMOTE" | sed -E 's|git@([^:]+):|https://\1|')
    PROJECT_PATH=$(echo "$GIT_REMOTE" | sed -E 's|.*:(.+?)(\.git)?$|\1|')
  fi
fi

echo "  Project path: $PROJECT_PATH"

# ============================================================================
# PHASE 7: Check for existing PR/MR
# ============================================================================
echo ""
echo "Phase 7: Checking for existing PR/MR..."

if [[ "$PLATFORM" == "github" ]]; then
  EXISTING=$(gh pr list --head "$SOURCE_BRANCH" --base "$TARGET_BRANCH" --json url,title --limit 1 2>/dev/null)
  if [[ -n "$EXISTING" ]] && [[ "$EXISTING" != "[]" ]]; then
    EXISTING_TITLE=$(echo "$EXISTING" | python3 -c "import sys,json; pr=json.load(sys.stdin)[0]; print(pr['title'])")
    EXISTING_URL=$(echo "$EXISTING" | python3 -c "import sys,json; pr=json.load(sys.stdin)[0]; print(pr['url'])")
    echo "A PR already exists for $SOURCE_BRANCH: $EXISTING_TITLE ($EXISTING_URL)"
    exit 0
  fi
elif [[ "$PLATFORM" == "gitlab" ]]; then
  ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT_PATH")
  EXISTING=$(curl -sf -H "PRIVATE-TOKEN: ${GITLAB_AI_TOKEN:-}" \
    "$GIT_REPO_BASE/api/v4/projects/$ENC/merge_requests?source_branch=$SOURCE_BRANCH&target_branch=$TARGET_BRANCH&state=opened" 2>/dev/null)
  if [[ -n "$EXISTING" ]] && [[ "$EXISTING" != "[]" ]]; then
    EXISTING_TITLE=$(echo "$EXISTING" | python3 -c "import sys,json; mr=json.load(sys.stdin)[0]; print(mr['title'])")
    EXISTING_URL=$(echo "$EXISTING" | python3 -c "import sys,json; mr=json.load(sys.stdin)[0]; print(mr['web_url'])")
    echo "An MR already exists for $SOURCE_BRANCH: $EXISTING_TITLE ($EXISTING_URL)"
    exit 0
  fi
fi

# ============================================================================
# PHASE 8: Draft PR/MR Title and Description
# ============================================================================
echo ""
echo "Phase 8: Drafting PR/MR title and description..."

# Get commits ahead of target branch
COMMIT_LOG=$(git log "origin/${TARGET_BRANCH}...HEAD" --oneline 2>/dev/null | head -20)

if [[ -z "$COMMIT_LOG" ]]; then
  echo "No commits found between $SOURCE_BRANCH and origin/$TARGET_BRANCH. Nothing to create a PR/MR for."
  exit 0
fi

# Determine title
if [[ -n "$TITLE" ]]; then
  FINAL_TITLE="$TITLE"
elif [[ $(echo "$COMMIT_LOG" | wc -l) -eq 1 ]]; then
  # Single commit: use its subject line
  FINAL_TITLE=$(echo "$COMMIT_LOG" | head -1 | cut -d' ' -f2-)
else
  # Multiple commits: prettify branch name
  FINAL_TITLE=$(echo "$SOURCE_BRANCH" | sed 's/[-_]/ /g' | sed 's/\b\(.\)/\u\1/g')
fi

# Determine description
SINGLE_COMMIT=false
COMMIT_COUNT=$(echo "$COMMIT_LOG" | wc -l)
if [[ $COMMIT_COUNT -eq 1 ]]; then
  SINGLE_COMMIT=true
  # Check if single commit has a body
  COMMIT_HASH=$(echo "$COMMIT_LOG" | cut -d' ' -f1)
  COMMIT_BODY=$(git log -1 --format=%b "$COMMIT_HASH" 2>/dev/null)

  if [[ -n "$COMMIT_BODY" ]]; then
    FINAL_DESCRIPTION="$COMMIT_BODY"
  else
    FINAL_DESCRIPTION="- $FINAL_TITLE"
  fi
else
  # Multiple commits: list them
  FINAL_DESCRIPTION=$(echo "$COMMIT_LOG" | tac | awk '{print "- " $0}')
fi

# Generate review URL
if [[ "$PLATFORM" == "github" ]]; then
  REVIEW_URL="https://github.com/$PROJECT_PATH/compare/$TARGET_BRANCH...$SOURCE_BRANCH"
else
  REVIEW_URL="$GIT_REPO_BASE/$PROJECT_PATH/-/merge_requests/new"
fi

# ============================================================================
# PHASE 9: Confirm with user
# ============================================================================
echo ""
echo "About to create PR/MR:"
echo ""
echo "  Title:  $FINAL_TITLE"
echo "  Source: $SOURCE_BRANCH → $TARGET_BRANCH"
echo "  URL:    $REVIEW_URL"
echo ""
echo "  Description:"
echo "  ---"
echo "$FINAL_DESCRIPTION" | sed 's/^/  /'
echo "  ---"
echo ""

if [[ $AUTO_YES == true ]]; then
  response="yes"
fi

while true; do
  if [[ $AUTO_YES == false ]]; then
    read -p "Proceed? (yes / edit title / edit description / cancel): " response
  fi
  case "$response" in
    yes)
      break
      ;;
    "edit title")
      read -p "Enter new title: " FINAL_TITLE
      echo "Title updated to: $FINAL_TITLE"
      echo ""
      echo "About to create PR/MR:"
      echo ""
      echo "  Title:  $FINAL_TITLE"
      echo "  Source: $SOURCE_BRANCH → $TARGET_BRANCH"
      echo "  URL:    $REVIEW_URL"
      echo ""
      echo "  Description:"
      echo "  ---"
      echo "$FINAL_DESCRIPTION" | sed 's/^/  /'
      echo "  ---"
      echo ""
      ;;
    "edit description")
      echo "Enter new description (press Ctrl+D when done):"
      FINAL_DESCRIPTION=$(cat)
      echo ""
      echo "About to create PR/MR:"
      echo ""
      echo "  Title:  $FINAL_TITLE"
      echo "  Source: $SOURCE_BRANCH → $TARGET_BRANCH"
      echo "  URL:    $REVIEW_URL"
      echo ""
      echo "  Description:"
      echo "  ---"
      echo "$FINAL_DESCRIPTION" | sed 's/^/  /'
      echo "  ---"
      echo ""
      ;;
    cancel)
      echo "PR/MR creation cancelled."
      exit 0
      ;;
    *)
      echo "Invalid choice. Please enter: yes, edit title, edit description, or cancel."
      ;;
  esac
done

# ============================================================================
# PHASE 10: Create PR/MR
# ============================================================================
echo ""
echo "Phase 10: Creating PR/MR..."

if [[ "$PLATFORM" == "github" ]]; then
  # GitHub PR creation
  MR_URL=$(gh pr create \
    --title "$FINAL_TITLE" \
    --base "$TARGET_BRANCH" \
    --body "$FINAL_DESCRIPTION")

  if [[ -z "$MR_URL" ]]; then
    echo -e "${RED}Error: Failed to create GitHub PR.${NC}"
    exit 1
  fi
else
  # GitLab MR creation
  MR_URL=$(bash "$SCRIPT_DIR/create_mr.sh" \
    "$GIT_REPO_BASE" "$PROJECT_PATH" \
    "$SOURCE_BRANCH" "$TARGET_BRANCH" \
    "$FINAL_TITLE" "$FINAL_DESCRIPTION" 2>&1)

  if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error creating GitLab MR:${NC}"
    echo "$MR_URL"
    exit 1
  fi

  if [[ -z "$MR_URL" ]]; then
    echo -e "${RED}Error: Failed to create GitLab MR (empty response).${NC}"
    exit 1
  fi
fi

echo -e "${GREEN}PR/MR created: $MR_URL${NC}"
