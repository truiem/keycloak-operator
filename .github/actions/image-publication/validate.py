"""Resolve a completed build to a current same-repository PR or an exact release tag.

Runs only from the trusted publisher workflow. Never check out PR code or accept
registry destinations, tags, or credentials from an artifact.
"""
import json
import os
import re
import urllib.parse
import urllib.request


class API:
    def __init__(self, repo):
        self.repo = repo

    def get(self, path):
        url = f"https://api.github.com/repos/{self.repo}/{path}"
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)


def resolve(api, event, registry, workflow, artifact):
    """Fail closed for untrusted sources; skip main pushes and stale/closed PRs."""
    if registry not in {"ghcr", "ecr"}:
        raise ValueError("Unsupported registry")
    source = event["workflow_run"]
    run = api.get(f"actions/runs/{source['id']}")
    repo = event["repository"]
    if (run["repository"]["id"] != repo["id"] or
            run["head_repository"]["id"] != repo["id"]):
        raise ValueError("Only same-repository builds may publish")
    if run["status"] != "completed" or run["conclusion"] != "success":
        return {}
    if run["path"] != workflow or run["head_sha"] != source["head_sha"]:
        raise ValueError("Unexpected build workflow or SHA")
    # Do not promote artifacts from an earlier attempt after a rerun has begun.
    if run["run_attempt"] != source["run_attempt"]:
        return {}
    sha = run["head_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid build SHA")
    if run["event"] in {"pull_request", "workflow_dispatch"}:
        # workflow_dispatch is the protected Dependabot build path. It must still
        # match exactly one open PR; arbitrary manually dispatched refs do not qualify.
        head = urllib.parse.quote(f"{repo['owner']['login']}:{run['head_branch']}", safe="")
        pulls = api.get(f"pulls?state=open&head={head}&per_page=100")
        pulls = [p for p in pulls if p["head"]["sha"] == sha and
                 p["head"]["repo"]["id"] == repo["id"] and
                 p["base"]["repo"]["id"] == repo["id"] and
                 p["base"]["ref"] == repo["default_branch"]]
        if len(pulls) != 1:
            return {}
        environment = "publish-ghcr" if registry == "ghcr" else "publish-ecr-dev"
        tag = "sha-" + sha[:7]
    elif run["event"] == "push":
        # Tags publish to production ECR only. Main pushes never publish images.
        branch = run["head_branch"]
        if registry != "ecr" or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.-]+)?", branch):
            return {}
        obj = api.get("git/ref/tags/" + urllib.parse.quote(branch, safe=""))["object"]
        for _ in range(5):
            if obj["type"] != "tag":
                break
            obj = api.get("git/tags/" + obj["sha"])["object"]
        if obj["type"] != "commit" or obj["sha"] != sha:
            raise ValueError("Release tag does not identify the built commit")
        environment, tag = "publish-ecr-prod", branch[1:]
    else:
        return {}
    # Resolve one exact artifact from this run, not the latest artifact on a branch.
    artifacts = []
    page = 1
    while True:
        batch = api.get(f"actions/runs/{run['id']}/artifacts?per_page=100&page={page}")["artifacts"]
        artifacts.extend(a for a in batch if a["name"] == artifact and not a["expired"])
        if len(batch) < 100:
            break
        page += 1
    if len(artifacts) != 1:
        raise ValueError("Expected one unexpired image artifact from the validated build")
    return {"ready": "true", "environment": environment, "tag": tag,
            "run-id": str(run["id"]), "artifact-id": str(artifacts[0]["id"]), "sha": sha}


def main():
    with open(os.environ["GITHUB_EVENT_PATH"]) as handle:
        event = json.load(handle)
    if os.environ["GITHUB_EVENT_NAME"] != "workflow_run":
        raise ValueError("Image publisher must run from the trusted workflow_run event")
    result = resolve(API(os.environ["GITHUB_REPOSITORY"]), event,
                     os.environ["REGISTRY_KIND"], os.environ["BUILD_WORKFLOW"],
                     os.environ["IMAGE_ARTIFACT"])
    with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
        handle.write("ready=false\n" if not result else "".join(f"{k}={v}\n" for k, v in result.items()))
    print("Validated publication" if result else "No current PR or release image to publish")


if __name__ == "__main__":
    main()
