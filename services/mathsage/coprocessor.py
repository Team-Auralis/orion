import json
import os
import re
import time

import httpx

DEFAULT_MODEL = "mathstral:7b"
DEFAULT_TIMEOUT = 90.0
DEFAULT_TEMPERATURE = 0.1
DEFAULT_KEEP_ALIVE = "10m"

TRUTHY = ("1", "true", "yes", "on")


def env_flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in TRUTHY


class MathCoprocessor:
    """Advisory math coprocessor for the FORGE scientific engine.

    A specialist (Mathstral-7B) second opinion on quantitative experiments.
    Never blocks, never raises, never silently passes: every attempt returns
    explicit telemetry about which model ran and why it did not.
    """

    def __init__(self, ollama_url=None, model=None, timeout=None,
                 temperature=None, keep_alive=None):
        self.ollama_url = ollama_url or os.environ.get(
            "OLLAMA_URL", "http://localhost:11434")
        self.model = model or os.environ.get("ORION_MATH_MODEL", DEFAULT_MODEL)
        self.timeout = float(timeout if timeout is not None
                             else os.environ.get("ORION_MATH_TIMEOUT",
                                                 DEFAULT_TIMEOUT))
        self.temperature = float(temperature if temperature is not None
                                 else os.environ.get(
                                     "ORION_MATH_TEMPERATURE",
                                     DEFAULT_TEMPERATURE))
        self.keep_alive = keep_alive or os.environ.get(
            "ORION_MATH_KEEP_ALIVE", DEFAULT_KEEP_ALIVE)
        self._availability = None

    @staticmethod
    def enabled() -> bool:
        """Master switch for the whole coprocessor (env-gated)."""
        return env_flag("ORION_MATH_ENABLED", "1")

    def disable_cache(self):
        self._availability = None

    def check_availability(self, force: bool = False) -> dict:
        if self._availability is not None and not force:
            return self._availability

        status = {
            "reachable": False,
            "model_found": False,
            "available_models": [],
            "status": "UNKNOWN",
        }
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{self.ollama_url}/api/tags")
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                status["reachable"] = True
                status["model_found"] = any(self.model in m for m in models)
                status["available_models"] = models
                status["status"] = (
                    "AVAILABLE" if status["model_found"] else "MODEL_NOT_FOUND"
                )
            else:
                status["status"] = f"HTTP_{resp.status_code}"
        except Exception as e:
            status["status"] = f"UNREACHABLE ({type(e).__name__})"

        self._availability = status
        return status

    def reason(self, question: str, context: str) -> dict:
        """Ask the coprocessor a quantitative question, returning telemetry."""
        base = {
            "model_used": self.model,
            "model_role": "MATH_COPROCESSOR",
            "coprocessor_active": False,
            "fallback_reason": None,
            "request_time_ms": None,
            "verdict": "UNAVAILABLE",
            "confidence": None,
            "reasoning": None,
        }

        availability = self.check_availability()
        if not (availability.get("reachable") and availability.get("model_found")):
            base["fallback_reason"] = f"Model unavailable: {availability['status']}"
            return base

        prompt = (
            "You are the ORION math coprocessor, a quantitative verification "
            "assistant for the FORGE scientific engine.\n"
            f"QUESTION: {question}\n"
            f"CONTEXT (JSON): {context}\n"
            "Verify the numbers in the context are mathematically coherent "
            "and the claimed conclusion is justified.\n"
            'Respond STRICTLY with a single JSON object of the form: '
            '{"verdict": "SUPPORTED" | "CHALLENGED" | "INCONCLUSIVE", '
            '"confidence": 0.0-1.0, "reasoning": "one or two sentences"}'
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": 220,
                "temperature": self.temperature,
                "top_p": 0.9,
            },
        }

        try:
            started = time.perf_counter()
            with httpx.Client(timeout=httpx.Timeout(2.0, read=self.timeout)) as client:
                resp = client.post(
                    f"{self.ollama_url}/api/generate", json=payload)
            base["request_time_ms"] = int((time.perf_counter() - started) * 1000)

            if resp.status_code != 200:
                base["fallback_reason"] = f"HTTP {resp.status_code}: {resp.text[:100]}"
                return base

            raw = resp.json().get("response", "")
            verdict = self._parse_verdict(raw)
            if verdict is None:
                base["coprocessor_active"] = True
                base["verdict"] = "INCONCLUSIVE"
                base["fallback_reason"] = "Model output was not parseable JSON"
                base["reasoning"] = raw[:500]
                return base

            verdict["coprocessor_active"] = True
            verdict["model_used"] = self.model
            verdict["model_role"] = "MATH_COPROCESSOR"
            verdict["fallback_reason"] = None
            verdict["request_time_ms"] = base["request_time_ms"]
            return verdict

        except httpx.TimeoutException:
            base["fallback_reason"] = (
                f"Math coprocessor timed out (>{self.timeout:.0f}s)")
        except Exception as e:
            base["fallback_reason"] = (
                f"Connection error: {type(e).__name__} ({str(e)})")

        return base

    @staticmethod
    def _parse_verdict(raw: str):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        verdict = data.get("verdict")
        if verdict not in ("SUPPORTED", "CHALLENGED", "INCONCLUSIVE"):
            verdict = "INCONCLUSIVE"
        return {
            "verdict": verdict,
            "confidence": _clamp_float(data.get("confidence"), None),
            "reasoning": data.get("reasoning"),
        }

    def review_experiment(self, hypothesis: str, design: dict,
                          result: dict, evaluation_score: float) -> dict:
        """Convenience wrapper producing a FORGE experiment review record."""
        context = json.dumps({
            "hypothesis": hypothesis,
            "design": design,
            "result": result,
            "evaluation_score": evaluation_score,
        })
        return self.reason(
            "Does this experiment's numeric result justify its evaluation "
            "score, and are the numbers internally coherent?",
            context,
        )


def _clamp_float(value, default=None):
    try:
        f = float(value)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return default