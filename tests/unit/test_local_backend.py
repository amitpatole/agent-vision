from agentvision.backends.base import AnalysisRequest
from agentvision.backends.local_backend import LocalBackend
from agentvision.backends.registry import select_backend
from agentvision.config import load_settings
from agentvision.models.report import Issue, IssueKind, Severity, Verdict


async def test_local_backend_packages_grounded_issues():
    backend = LocalBackend()
    assert backend.available()
    hints = [Issue.make(IssueKind.OVERFLOW, Severity.ERROR, "overflow")]
    report = await backend.analyze(AnalysisRequest(image_path="x.png", dom_hints=hints))
    assert report.backend == "local"
    assert report.verdict == Verdict.FAIL
    assert len(report.issues) == 1
    # local declares only its structural capabilities
    assert IssueKind.OVERFLOW in report.capabilities
    assert IssueKind.MISSING_ELEMENT not in report.capabilities


async def test_local_backend_pass_when_clean():
    report = await LocalBackend().analyze(AnalysisRequest(image_path="x.png", dom_hints=[]))
    assert report.verdict == Verdict.PASS


def test_registry_falls_back_to_local_without_keys():
    settings = load_settings(anthropic_api_key=None, openai_api_key=None, google_api_key=None)
    backend, warning = select_backend(settings, requested="anthropic")
    assert backend.name == "local"
    assert warning is not None and "anthropic" in warning


def test_registry_auto_picks_local_when_no_keys():
    settings = load_settings(anthropic_api_key=None, openai_api_key=None, google_api_key=None)
    backend, warning = select_backend(settings)
    assert backend.name == "local"
    assert warning is None
