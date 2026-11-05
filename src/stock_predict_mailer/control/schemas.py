"""Closed configuration schemas. Capabilities are explicit, not guessed from names."""
from __future__ import annotations

import math
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROLES = ("main", "prediction", "risk", "advice")
PARAMETERS = {"temperature", "top_p", "max_tokens", "max_completion_tokens", "response_format", "seed",
              "presence_penalty", "frequency_penalty"}


def endpoint(value):
    try:
        p = urlsplit(value)
        if p.username or p.password or p.query or p.fragment or not p.hostname:
            raise ValueError()
        if p.scheme != "https" and not (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1")):
            raise ValueError()
        _ = p.port
    except ValueError:
        raise ValueError("地址须为 HTTPS 或本机 HTTP，且不能内嵌凭据/query/fragment") from None
    return value.rstrip("/")


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, str_strip_whitespace=True)


class ModelProfile(Closed):
    name: str = Field(min_length=1, max_length=100)
    provider: Literal["mock", "openai_compatible"] = "mock"
    base_url: str = "https://api.openai.com/v1"
    model: str = Field(default="mock-analysis", min_length=1, max_length=200)
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    retries: int = Field(default=1, ge=0, le=3)
    supported_parameters: list[str] = Field(default_factory=lambda: ["temperature", "max_tokens", "response_format"])
    temperature_min: float = Field(default=0.0, ge=0, le=2)
    temperature_max: float = Field(default=2.0, ge=0, le=2)
    parameters: dict = Field(default_factory=lambda: {"max_tokens": 512})
    input_usd_per_million: float | None = Field(default=None, ge=0, le=100000)
    output_usd_per_million: float | None = Field(default=None, ge=0, le=100000)
    enabled: bool = True

    @model_validator(mode="after")
    def compatible(self):
        self.base_url = endpoint(self.base_url)
        if set(self.supported_parameters) - PARAMETERS or set(self.parameters) - set(self.supported_parameters):
            raise ValueError("生成参数不在模型声明的支持范围内")
        if self.temperature_min > self.temperature_max:
            raise ValueError("温度范围无效")
        if "max_tokens" in self.parameters and "max_completion_tokens" in self.parameters:
            raise ValueError("不能同时设置两种 token 上限")
        if not any(k in self.parameters for k in ("max_tokens", "max_completion_tokens")):
            raise ValueError("必须设置模型支持的输出 token 上限")
        for k, v in self.parameters.items():
            if k == "response_format":
                if v not in ({"type": "json_object"},):
                    raise ValueError("仅支持 json_object 响应格式")
            elif k in ("max_tokens", "max_completion_tokens", "seed"):
                if type(v) is not int or not 0 <= v <= 32768 or (k != "seed" and v == 0):
                    raise ValueError("无效整数生成参数")
            elif type(v) not in (int, float) or not math.isfinite(v):
                raise ValueError("生成参数必须为有限数值")
            elif k == "temperature" and not self.temperature_min <= v <= self.temperature_max:
                raise ValueError("temperature 超出声明范围")
            elif k == "top_p" and not 0 <= v <= 1:
                raise ValueError("top_p 必须在 0..1")
            elif k in ("presence_penalty", "frequency_penalty") and not -2 <= v <= 2:
                raise ValueError("penalty 必须在 -2..2")
        return self


class MCPProfile(Closed):
    name: str = Field(min_length=1, max_length=100)
    transport: Literal["stdio", "streamable_http"] = "streamable_http"
    url: str = "http://127.0.0.1:8766/mcp"
    command: str = ""
    args: list[str] = Field(default_factory=list, max_length=30)
    enabled: bool = True
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)
    allowed_resources: list[str] = Field(default_factory=list, max_length=50)
    effects: dict[str, Literal["read", "email", "deny"]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def connection(self):
        if self.transport == "streamable_http":
            self.url = endpoint(self.url)
        elif not self.command.strip() or any(c in self.command for c in "\r\n"):
            raise ValueError("stdio 必须配置启动命令，不使用 shell")
        if any(not isinstance(v, str) or len(v) > 2000 for v in self.args):
            raise ValueError("无效启动参数")
        return self


class AgentEndpoint(Closed):
    name: str = Field(min_length=1, max_length=100)
    url: str
    enabled: bool = True
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    cost_ceiling_usd: float = Field(default=0.01, ge=0, le=100)

    @model_validator(mode="after")
    def address(self):
        self.url = endpoint(self.url)
        return self


class RoleConfig(Closed):
    model_id: str | None = None
    endpoint_id: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    tools: list[str] = Field(default_factory=list)


class Limits(Closed):
    max_subagents: int = Field(default=3, ge=0, le=3)
    max_depth: int = Field(default=1, ge=0, le=3)
    max_calls: int = Field(default=8, ge=1, le=50)
    timeout_seconds: int = Field(default=90, ge=1, le=600)
    child_timeout_seconds: int = Field(default=20, ge=1, le=120)
    budget_usd: float = Field(default=0.1, ge=0, le=100)


class MailPolicy(Closed):
    transport: Literal["file", "smtp", "mcp"] = "file"
    sender: str = "research@example.invalid"
    recipient_allowlist: list[str] = Field(default_factory=list)
    allow_synthetic: bool = False
    mcp_server_id: str | None = None
    mcp_tool: str | None = None
    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    tls: Literal["starttls", "ssl"] = "starttls"
    user_env: str = "SMTP_USER"
    password_env: str = "SMTP_PASSWORD"


class Settings(Closed):
    default_model_id: str | None = None
    global_temperature: float = Field(default=0.2, ge=0, le=2)
    agents: dict[str, RoleConfig] = Field(default_factory=lambda: {r: RoleConfig() for r in ROLES})
    limits: Limits = Field(default_factory=Limits)
    mail: MailPolicy = Field(default_factory=MailPolicy)

    @model_validator(mode="after")
    def roles(self):
        if set(self.agents) != set(ROLES):
            raise ValueError("必须配置 main/prediction/risk/advice 四个角色")
        return self
