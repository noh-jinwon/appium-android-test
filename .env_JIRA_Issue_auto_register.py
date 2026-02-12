#Jira 접속정보
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_DEPLOYMENT=cloud

JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=여기에_토큰

JIRA_PROJECT_KEY=QA
JIRA_ISSUE_TYPE=Bug

JIRA_CREATE_ON_FAIL=1
JIRA_DUPLICATE_STRATEGY=reuse_open

JIRA_LABELS=ui-test,appium,pytest,android
JIRA_COMPONENTS=Mobile,Android
JIRA_PRIORITY=High

APPIUM_LOG_PATH=artifacts/appium_server.log
INSTALL_LOG_PATH=artifacts/install.log


#Jira 자동 등록 코드
# utils/jira_reporter.py
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from jira import JIRA

load_dotenv()

ARTIFACT_DIR = Path(os.getenv("ARTIFACT_DIR", "artifacts"))


@dataclass
class JiraConfig:
    base_url: str
    deployment: str  # cloud | dc | auto
    project_key: str
    issue_type: str

    # cloud
    email: Optional[str] = None
    api_token: Optional[str] = None

    # dc
    pat: Optional[str] = None

    components: list[str] = None
    priority: Optional[str] = None
    labels: list[str] = None
    duplicate_strategy: str = "reuse_open"  # reuse_open | always_new
    create_on_fail: bool = True

    appium_log_path: Optional[str] = None
    install_log_path: Optional[str] = None

    def __post_init__(self):
        self.components = self.components or []
        self.labels = self.labels or []
        self.deployment = (self.deployment or "auto").lower().strip()


def load_config() -> JiraConfig:
    base_url = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("JIRA_BASE_URL is required")

    deployment = os.getenv("JIRA_DEPLOYMENT", "auto").strip()
    project_key = os.getenv("JIRA_PROJECT_KEY", "").strip()
    issue_type = os.getenv("JIRA_ISSUE_TYPE", "Bug").strip()

    if not project_key:
        raise RuntimeError("JIRA_PROJECT_KEY is required")

    email = os.getenv("JIRA_EMAIL")
    api_token = os.getenv("JIRA_API_TOKEN")
    pat = os.getenv("JIRA_PAT")

    components = [x.strip() for x in os.getenv("JIRA_COMPONENTS", "").split(",") if x.strip()]
    labels = [x.strip() for x in os.getenv("JIRA_LABELS", "").split(",") if x.strip()]
    priority = os.getenv("JIRA_PRIORITY")

    duplicate_strategy = os.getenv("JIRA_DUPLICATE_STRATEGY", "reuse_open").strip()
    create_on_fail = os.getenv("JIRA_CREATE_ON_FAIL", "1").strip().lower() in ("1", "true", "yes", "y")

    appium_log_path = os.getenv("APPIUM_LOG_PATH")
    install_log_path = os.getenv("INSTALL_LOG_PATH")

    # auto-detect
    if deployment.lower() == "auto":
        deployment = "cloud" if "atlassian.net" in base_url else "dc"

    return JiraConfig(
        base_url=base_url,
        deployment=deployment,
        project_key=project_key,
        issue_type=issue_type,
        email=email,
        api_token=api_token,
        pat=pat,
        components=components,
        priority=priority,
        labels=labels,
        duplicate_strategy=duplicate_strategy,
        create_on_fail=create_on_fail,
        appium_log_path=appium_log_path,
        install_log_path=install_log_path,
    )


def _jira_client(cfg: JiraConfig) -> JIRA:
    if cfg.deployment == "cloud":
        if not (cfg.email and cfg.api_token):
            raise RuntimeError("Cloud requires JIRA_EMAIL and JIRA_API_TOKEN")
        return JIRA(server=cfg.base_url, basic_auth=(cfg.email, cfg.api_token))

    # Data Center
    if not cfg.pat:
        raise RuntimeError("Data Center requires JIRA_PAT")
    # token_auth는 Bearer 토큰 방식(PAT)에 많이 쓰임
    return JIRA(server=cfg.base_url, token_auth=cfg.pat)


def _requests_auth_headers(cfg: JiraConfig):
    headers = {"Accept": "application/json", "X-Atlassian-Token": "no-check"}
    if cfg.deployment == "cloud":
        return (cfg.email, cfg.api_token), headers
    headers["Authorization"] = f"Bearer {cfg.pat}"
    return None, headers


def safe_filename(s: str, limit: int = 180) -> str:
    s = s.strip()
    out = "".join(c if c.isalnum() or c in "._-[]() " else "_" for c in s)
    return out[:limit]


def collect_logcat(out_path: Path, tail_lines: int = 2000) -> None:
    try:
        cmd = ["adb", "logcat", "-d", "-t", str(tail_lines)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25, check=False)
        if r.returncode != 0 or not r.stdout.strip():
            r = subprocess.run(["adb", "logcat", "-d"], capture_output=True, text=True, timeout=25, check=False)

        out_path.write_text(
            r.stdout + "\n\n[stderr]\n" + r.stderr,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        out_path.write_text(f"failed to collect logcat: {e}", encoding="utf-8", errors="ignore")


def try_copy(src: Optional[str], dest: Path) -> Optional[Path]:
    if not src:
        return None
    p = Path(src)
    if not p.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(p, dest)
        return dest
    except Exception:
        return None


def make_fingerprint_label(test_nodeid: str, extra: str = "") -> str:
    raw = (test_nodeid + "|" + extra).encode("utf-8", errors="ignore")
    h = hashlib.sha1(raw).hexdigest()[:10]
    return f"autofail-{h}"


def _find_open_issue_by_label(jira: JIRA, cfg: JiraConfig, label: str):
    jql = (
        f'project = {cfg.project_key} AND labels = "{label}" '
        f"AND statusCategory != Done ORDER BY created DESC"
    )
    issues = jira.search_issues(jql, maxResults=1)
    return issues[0] if issues else None


def _attach_files(cfg: JiraConfig, issue_key: str, artifacts: list[Path]):
    # attachments는 requests로 올리는 게 가장 예측 가능해서 이 방식 사용
    auth, headers = _requests_auth_headers(cfg)

    for p in artifacts:
        if not p or not p.exists():
            continue

        url = f"{cfg.base_url}/rest/api/2/issue/{issue_key}/attachments"
        try:
            with p.open("rb") as f:
                files = {"file": (p.name, f)}
                r = requests.post(url, headers=headers, auth=auth, files=files, timeout=60)
                r.raise_for_status()
        except Exception:
            # 첨부 실패해도 진행
            pass


def create_or_update_issue(
    *,
    cfg: JiraConfig,
    test_nodeid: str,
    test_name: str,
    when: str,
    error_text: str,
    env_text: str,
    artifacts: list[Path],
) -> str:
    jira = _jira_client(cfg)

    fingerprint = make_fingerprint_label(test_nodeid)
    labels = list({*cfg.labels, "auto-test", "android", "appium", "pytest", fingerprint})

    summary = f"[AUTO][Android] {test_name} 실패 ({when})"
    description = (
        "자동화 테스트 실패로 생성됨\n\n"
        f"Test: {test_nodeid}\n"
        f"Phase: {when}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "Environment:\n"
        f"{env_text}\n\n"
        "Error:\n"
        f"{error_text[:30000]}\n"
    )

    fields = {
        "project": {"key": cfg.project_key},
        "summary": summary,
        "description": description,
        "issuetype": {"name": cfg.issue_type},
        "labels": labels,
    }

    if cfg.components:
        fields["components"] = [{"name": c} for c in cfg.components]

    if cfg.priority:
        fields["priority"] = {"name": cfg.priority}

    issue = None
    if cfg.duplicate_strategy == "reuse_open":
        issue = _find_open_issue_by_label(jira, cfg, fingerprint)

    if issue:
        jira.add_comment(issue, f"동일 테스트가 다시 실패했습니다. ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        issue_key = issue.key
    else:
        issue = jira.create_issue(fields=fields)
        issue_key = issue.key

    _attach_files(cfg, issue_key, artifacts)
    return issue_key
