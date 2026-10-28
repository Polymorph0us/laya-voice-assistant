"""
GitHub management tools: list_github_repos, create_github_repo, delete_github_repo, cleanup_forked_repos.

Enables Laya to inspect, create, and safely clean up repositories on behalf of the user.
Deleting repositories requires explicit confirmation to prevent accidental loss of code.
"""

from __future__ import annotations
import os
import httpx
from typing import Any
from pathlib import Path

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.github")


def _get_github_auth() -> tuple[str, str]:
    """Retrieve GitHub token and username from environment or settings.yaml."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    username = os.environ.get("GITHUB_USERNAME", "").strip()

    if not token or not username:
        try:
            import yaml
            cfg_path = Path("config/settings.yaml")
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                gh = cfg.get("github", {})
                if not token:
                    token = gh.get("token", "").strip()
                if not username:
                    username = gh.get("username", "").strip()
        except Exception:
            pass

    return token, username


def _get_github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@register(
    name="list_github_repos",
    description="List your personal GitHub repositories, optionally filtering by forks or original projects",
    permission=PermissionLevel.SAFE,
    category="developer",
    parameters=[
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum number of repositories to list (default 15)",
            required=False,
            default=15,
        ),
        ToolParameter(
            name="filter_type",
            type="string",
            description="Filter repositories: 'all', 'forks', or 'original'",
            required=False,
            default="all",
        ),
    ],
)
def list_github_repos(limit: int = 15, filter_type: str = "all") -> ToolResult:
    """List authenticated user's repositories from GitHub."""
    token, username = _get_github_auth()

    if not token:
        return ToolResult(
            success=False,
            error="Missing GITHUB_TOKEN",
            message="To view your GitHub repositories, please add your GitHub Personal Access Token to config/settings.yaml under 'github.token'.",
        )

    headers = _get_github_headers(token)

    try:
        # Fetch up to 100 repositories to get a full view
        resp = httpx.get(
            "https://api.github.com/user/repos?sort=updated&per_page=100&affiliation=owner",
            headers=headers,
            timeout=15.0,
        )

        if resp.status_code == 401:
            return ToolResult(
                success=False,
                error="Invalid GitHub token",
                message="Your GitHub token is invalid or expired. Please check config/settings.yaml.",
            )

        if resp.status_code != 200:
            return ToolResult(
                success=False,
                error=f"GitHub API error {resp.status_code}",
                message=f"Failed to fetch repositories (HTTP {resp.status_code}).",
            )

        repos = resp.json()
        filter_lower = filter_type.strip().lower()
        if filter_lower == "forks":
            filtered = [r for r in repos if r.get("fork")]
        elif filter_lower in ("original", "originals", "non-forks", "non-fork"):
            filtered = [r for r in repos if not r.get("fork")]
        else:
            filtered = repos

        total_forks = sum(1 for r in repos if r.get("fork"))
        total_originals = len(repos) - total_forks

        if not filtered:
            return ToolResult(
                success=True,
                message=f"No repositories matched filter '{filter_type}'. Total repos: {len(repos)} ({total_originals} original, {total_forks} forks).",
                data={"repos": [], "total": len(repos), "forks": total_forks, "originals": total_originals},
            )

        items = []
        for r in filtered[:limit]:
            kind = "fork" if r.get("fork") else "original"
            vis = "private" if r.get("private") else "public"
            items.append(f"{r['name']} ({kind}, {vis})")

        summary = (
            f"You have {len(repos)} repositories total ({total_originals} original, {total_forks} forks). "
            f"Showing {min(limit, len(filtered))} {filter_lower} repos: " + ", ".join(items)
        )

        return ToolResult(
            success=True,
            message=summary,
            data={
                "repos": [{"name": r["name"], "fork": r.get("fork"), "private": r.get("private")} for r in filtered[:limit]],
                "total": len(repos),
                "forks_count": total_forks,
                "originals_count": total_originals,
            },
        )

    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Failed to connect to GitHub: {e}")


@register(
    name="create_github_repo",
    description="Create a new repository on your GitHub account",
    permission=PermissionLevel.SAFE,
    category="developer",
    parameters=[
        ToolParameter(
            name="repo_name",
            type="string",
            description="The name of the repository to create",
        ),
        ToolParameter(
            name="private",
            type="boolean",
            description="Whether the repository should be private (default True)",
            required=False,
            default=True,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Optional short description for the repository",
            required=False,
            default="",
        ),
    ],
)
def create_github_repo(repo_name: str, private: bool = True, description: str = "") -> ToolResult:
    """Create a new GitHub repository."""
    token, _ = _get_github_auth()

    if not token:
        return ToolResult(
            success=False,
            error="Missing GITHUB_TOKEN",
            message="To create a repository, please add your GitHub token to config/settings.yaml.",
        )

    headers = _get_github_headers(token)
    payload = {
        "name": repo_name.strip(),
        "description": description.strip(),
        "private": bool(private),
        "auto_init": True,
    }

    try:
        resp = httpx.post("https://api.github.com/user/repos", headers=headers, json=payload, timeout=15.0)

        if resp.status_code == 201:
            data = resp.json()
            url = data.get("html_url", "")
            vis = "private" if private else "public"
            return ToolResult(
                success=True,
                message=f"Created {vis} repository '{repo_name}' on GitHub: {url}",
                data={"name": repo_name, "url": url, "private": private},
            )
        elif resp.status_code == 422:
            return ToolResult(
                success=False,
                error="Repository already exists or name invalid",
                message=f"Repository '{repo_name}' already exists or has an invalid name.",
            )
        else:
            return ToolResult(
                success=False,
                error=f"HTTP {resp.status_code}",
                message=f"Failed to create repository: {resp.text[:120]}",
            )
    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Failed to create repository '{repo_name}': {e}")


@register(
    name="cleanup_forked_repos",
    description="Batch delete forked repositories on GitHub with exclusion support. Safeguarded with preview/confirmation.",
    permission=PermissionLevel.DANGEROUS,
    category="developer",
    parameters=[
        ToolParameter(
            name="exclude_repos",
            type="string",
            description="Comma-separated repository names to keep (exclude from deletion)",
            required=False,
            default="",
        ),
        ToolParameter(
            name="confirm",
            type="boolean",
            description="Set to True to actually perform the deletions. If False, only previews what will be deleted.",
            required=False,
            default=False,
        ),
    ],
)
def cleanup_forked_repos(exclude_repos: str = "", confirm: bool = False) -> ToolResult:
    """Preview or batch delete all forked repositories, excluding specified ones."""
    token, username = _get_github_auth()

    if not token:
        return ToolResult(
            success=False,
            error="Missing GITHUB_TOKEN",
            message="To clean up forked repositories, please add your GitHub token to config/settings.yaml.",
        )

    headers = _get_github_headers(token)

    try:
        # 1. Fetch user's repositories
        resp = httpx.get(
            "https://api.github.com/user/repos?sort=updated&per_page=100&affiliation=owner",
            headers=headers,
            timeout=15.0,
        )
        if resp.status_code != 200:
            return ToolResult(success=False, error=f"HTTP {resp.status_code}", message="Failed to fetch repositories.")

        all_repos = resp.json()
        forked = [r for r in all_repos if r.get("fork")]

        # 2. Parse exclusion list (split by comma, space, and 'and')
        import re
        tokens = re.split(r"[,|\s]+", exclude_repos)
        excluded_names = {t.strip().lower() for t in tokens if t.strip() and t.strip().lower() not in ("and", "or", "&")}

        # 3. Filter targets
        targets = [r for r in forked if r["name"].lower() not in excluded_names]
        excluded_found = [r["name"] for r in forked if r["name"].lower() in excluded_names]

        if not targets:
            return ToolResult(
                success=True,
                message=f"No forked repositories found to delete (Total forks: {len(forked)}, Excluded: {excluded_found}).",
                data={"total_forks": len(forked), "deleted": []},
            )

        # 4. Preview (Dry Run) if confirm is False
        target_names = [r["name"] for r in targets]
        if not confirm:
            sample = ", ".join(target_names[:6])
            etc = f" and {len(target_names)-6} more" if len(target_names) > 6 else ""
            return ToolResult(
                success=True,
                message=(
                    f"[CONFIRMATION REQUIRED] Found {len(targets)} forked repositories to delete ({sample}{etc}). "
                    f"Excluded: {excluded_found or 'None'}. "
                    f"To permanently delete these {len(targets)} forked repos, please reply: 'confirm delete forked repos'."
                ),
                data={"targets": target_names, "excluded": excluded_found, "count": len(targets), "dry_run": True},
            )

        # 5. Perform deletions if confirm is True
        owner = username
        if not owner:
            user_resp = httpx.get("https://api.github.com/user", headers=headers, timeout=10.0)
            if user_resp.status_code == 200:
                owner = user_resp.json().get("login", "")

        deleted = []
        errors = []
        for r in targets:
            del_url = f"https://api.github.com/repos/{owner}/{r['name']}"
            del_resp = httpx.delete(del_url, headers=headers, timeout=10.0)
            if del_resp.status_code == 204:
                deleted.append(r["name"])
            else:
                errors.append(f"{r['name']} ({del_resp.status_code})")

        msg = f"Successfully deleted {len(deleted)} forked repositories."
        if excluded_found:
            msg += f" Kept: {', '.join(excluded_found)}."
        if errors:
            msg += f" Failed on {len(errors)}: {', '.join(errors[:3])}."

        return ToolResult(
            success=True,
            message=msg,
            data={"deleted": deleted, "errors": errors, "excluded": excluded_found},
        )

    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Error during forked repo cleanup: {e}")


@register(
    name="delete_github_repo",
    description="Permanently delete a single GitHub repository by name. DANGEROUS action that removes the repo and all code.",
    permission=PermissionLevel.DANGEROUS,
    category="developer",
    parameters=[
        ToolParameter(
            name="repo_name",
            type="string",
            description="The exact name of the repository to delete (e.g. 'old-test-repo')",
        ),
    ],
)
def delete_github_repo(repo_name: str) -> ToolResult:
    """Permanently delete a single repository on GitHub."""
    token, username = _get_github_auth()

    if not token:
        return ToolResult(
            success=False,
            error="Missing GITHUB_TOKEN",
            message="To delete GitHub repositories, please add your GitHub token to config/settings.yaml under 'github.token'.",
        )

    headers = _get_github_headers(token)

    repo_clean = repo_name.strip()
    if "/" in repo_clean:
        owner, repo_clean = repo_clean.split("/", 1)
    else:
        owner = username

    if not owner:
        try:
            user_resp = httpx.get("https://api.github.com/user", headers=headers, timeout=10.0)
            if user_resp.status_code == 200:
                owner = user_resp.json().get("login", "")
            else:
                return ToolResult(
                    success=False,
                    error="Cannot determine GitHub username",
                    message="Could not retrieve your GitHub username. Please check your token.",
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"Failed to authenticate with GitHub: {e}")

    try:
        delete_url = f"https://api.github.com/repos/{owner}/{repo_clean}"
        resp = httpx.delete(delete_url, headers=headers, timeout=15.0)

        if resp.status_code == 204:
            return ToolResult(
                success=True,
                message=f"Repository '{owner}/{repo_clean}' has been permanently deleted from your GitHub.",
                data={"repo": repo_clean, "owner": owner},
            )
        elif resp.status_code == 404:
            return ToolResult(
                success=False,
                error="Repository not found",
                message=f"Repository '{repo_clean}' was not found under account '{owner}'.",
            )
        elif resp.status_code == 403:
            return ToolResult(
                success=False,
                error="Permission denied",
                message="GitHub returned 403 Forbidden. Your token might be missing the 'delete_repo' scope.",
            )
        else:
            return ToolResult(
                success=False,
                error=f"HTTP {resp.status_code}",
                message=f"Failed to delete repository (HTTP {resp.status_code}): {resp.text[:150]}",
            )

    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message=f"Error deleting GitHub repository '{repo_clean}': {e}",
        )


@register(
    name="git_push_project",
    description="Initialize git, commit all project files, and push the local workspace directly to a GitHub repository",
    permission=PermissionLevel.SAFE,
    category="developer",
    parameters=[
        ToolParameter(
            name="repo_name",
            type="string",
            description="The GitHub repository name (e.g. 'laya-voice-assistant')",
        ),
        ToolParameter(
            name="commit_message",
            type="string",
            description="Git commit message describing this version",
            required=False,
            default="Initial release of Laya Voice Assistant",
        ),
        ToolParameter(
            name="branch",
            type="string",
            description="Target git branch (default 'main')",
            required=False,
            default="main",
        ),
        ToolParameter(
            name="private",
            type="boolean",
            description="Whether the GitHub repository should be private if it needs to be created (default False)",
            required=False,
            default=False,
        ),
    ],
)
def git_push_project(
    repo_name: str,
    commit_message: str = "Initial release of Laya Voice Assistant",
    branch: str = "main",
    private: bool = False,
    **kwargs: Any,
) -> ToolResult:
    """Initialize local git repository, commit files, and push to GitHub."""
    import subprocess
    token, username = _get_github_auth()

    if not token:
        return ToolResult(
            success=False,
            error="Missing GITHUB_TOKEN",
            message="To push to GitHub, please configure your GitHub token in config/settings.yaml.",
        )

    headers = _get_github_headers(token)
    repo_clean = repo_name.strip()

    # Determine username
    owner = username
    if not owner:
        try:
            u_resp = httpx.get("https://api.github.com/user", headers=headers, timeout=10.0)
            if u_resp.status_code == 200:
                owner = u_resp.json().get("login", "")
        except Exception:
            pass

    if not owner:
        return ToolResult(success=False, error="Cannot resolve GitHub username", message="Could not determine GitHub username.")

    # 1. Ensure remote repository exists on GitHub
    repo_url = f"https://github.com/{owner}/{repo_clean}"
    try:
        check_resp = httpx.get(f"https://api.github.com/repos/{owner}/{repo_clean}", headers=headers, timeout=10.0)
        if check_resp.status_code == 404:
            # Create the repository on GitHub
            create_payload = {
                "name": repo_clean,
                "description": "Laya — Desktop AI Voice Assistant with System 1/2 Architecture",
                "private": bool(private),
                "auto_init": False,
            }
            create_resp = httpx.post("https://api.github.com/user/repos", headers=headers, json=create_payload, timeout=15.0)
            if create_resp.status_code not in (200, 201):
                logger.warning(f"Could not auto-create remote repo: {create_resp.text}")
    except Exception as e:
        logger.warning(f"Error checking/creating remote repo: {e}")

    # 2. Local git initialization and commits
    try:
        cwd = Path.cwd()

        # Check if git initialized
        git_dir = cwd / ".git"
        if not git_dir.exists():
            subprocess.run(["git", "init"], cwd=str(cwd), check=True, capture_output=True, text=True)
            subprocess.run(["git", "branch", "-M", branch], cwd=str(cwd), check=True, capture_output=True, text=True)

        # Ensure branch is set
        subprocess.run(["git", "branch", "-M", branch], cwd=str(cwd), capture_output=True, text=True)

        # Set remote origin
        remotes_out = subprocess.run(["git", "remote"], cwd=str(cwd), capture_output=True, text=True).stdout
        if "origin" in remotes_out:
            subprocess.run(["git", "remote", "set-url", "origin", repo_url], cwd=str(cwd), check=True, capture_output=True)
        else:
            subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=str(cwd), check=True, capture_output=True)

        # Stage files (strictly obeying .gitignore)
        subprocess.run(["git", "add", "."], cwd=str(cwd), check=True, capture_output=True, text=True)

        # Commit changes if dirty
        status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(cwd), capture_output=True, text=True)
        if status_proc.stdout.strip():
            msg = commit_message or "Update Laya Assistant codebase"
            commit_proc = subprocess.run(["git", "commit", "-m", msg], cwd=str(cwd), capture_output=True, text=True)
            if commit_proc.returncode != 0:
                logger.warning(f"Git commit returned code {commit_proc.returncode}: {commit_proc.stderr}")

        # Push to GitHub authenticated with token
        auth_push_url = f"https://{token}@github.com/{owner}/{repo_clean}.git"
        push_proc = subprocess.run(
            ["git", "push", "-u", auth_push_url, branch],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if push_proc.returncode == 0:
            return ToolResult(
                success=True,
                message=f"Successfully pushed project to GitHub repository: {repo_url} on branch '{branch}'.",
                data={"repo_name": repo_clean, "repo_url": repo_url, "branch": branch, "owner": owner},
            )
        else:
            err = (push_proc.stderr or push_proc.stdout).strip()
            # If rejected because remote has existing commits, try pull/rebase or force push if initial
            logger.warning(f"Git push failed: {err}")
            return ToolResult(
                success=False,
                error=err,
                message=f"Git push returned error: {err[:200]}",
            )

    except subprocess.TimeoutExpired:
        return ToolResult(success=False, error="Timeout", message="Git push timed out after 60 seconds.")
    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Failed to push project to GitHub: {e}")

