"""
MCP server API router — CRUD + 连接管理 typed API endpoints。
"""

import logging
import re
from collections.abc import Iterator
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from typing import Literal

from src.business.mcp.mcp_json_import import McpJsonParseError, parse_mcp_json
from src.business.mcp.mcp_server_service import McpServerService
from src.business.mcp.mcp_errors import (
    McpCircuitBreakerOpenError,
    McpServerDisconnectedError,
    McpToolTimeoutError,
)

logger = logging.getLogger(__name__)

# API 错误信息脱敏（防止泄漏密钥到前端响应）
_API_REDACT_PATTERNS = [
    re.compile(r"(ghp_[a-zA-Z0-9]{30,})", re.IGNORECASE),
    re.compile(r"(gho_[a-zA-Z0-9]{30,})", re.IGNORECASE),
    re.compile(r"(sk-[a-zA-Z0-9\-]{20,})", re.IGNORECASE),
    re.compile(r"(bearer\s+[a-zA-Z0-9\-._~+/]+=*)", re.IGNORECASE),
    re.compile(r"(https?://[^:/\s]+:[^:/\s]+@)", re.IGNORECASE),
]


def _sanitize_api_error(text: str) -> str:
    """脱敏 API 错误信息中的密钥模式。"""
    for pattern in _API_REDACT_PATTERNS:
        text = pattern.sub("***", text)
    return text[:500]


router = APIRouter(prefix="/api/mcp-servers", tags=["mcp-servers"])


# ─── Pydantic Schemas ───


class McpServerCreateRequest(BaseModel):
    name: str
    transport: Literal["stdio", "http"] = "stdio"
    command: Optional[str] = None
    args: Optional[list[str]] = None
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    secretHeaderKeys: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    secretEnvKeys: Optional[list[str]] = None
    presetSlug: Optional[str] = None


class McpServerUpdateRequest(BaseModel):
    # name 不可改：slug 由 name 派生，改名会导致 mcp__<slug>__<tool> 全名变化（P3-R4）
    command: Optional[str] = None
    args: Optional[list[str]] = None
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    secretHeaderKeys: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    secretEnvKeys: Optional[list[str]] = None


class McpServerJsonImportRequest(BaseModel):
    jsonText: str


class McpServerResponse(BaseModel):
    serverId: str
    name: str
    transport: str
    command: Optional[str] = None
    args: Optional[list[str]] = None
    url: Optional[str] = None
    envKeys: list[str] = []
    envMissingKeys: list[str] = []
    envPresence: dict[str, str] = {}
    headerKeys: list[str] = []
    headerMissingKeys: list[str] = []
    headerPresence: dict[str, str] = {}
    enabled: bool = True
    status: Optional[str] = None
    toolCount: Optional[int] = None
    presetSlug: Optional[str] = None
    lastError: Optional[str] = None
    suggestion: Optional[str] = None
    circuitBreakerOpen: bool = False
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class McpServerTestConnectionResponse(BaseModel):
    success: bool
    toolCount: int = 0
    tools: list[dict] = []
    error: Optional[str] = None


class McpServerParsedPreview(BaseModel):
    name: str
    transport: str
    command: Optional[str] = None
    args: Optional[list[str]] = None
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    env: Optional[dict[str, str]] = None
    detectedSecretKeys: list[str] = []
    placeholderKeys: list[str] = []


class McpServerJsonImportResponse(BaseModel):
    servers: list[McpServerParsedPreview]


# ─── Dependency Injection ───


def get_mcp_service() -> Iterator[McpServerService]:
    from src.business.mcp import get_mcp_server_service

    service = get_mcp_server_service()
    yield service


# ─── Endpoints ───


@router.get("", response_model=list[McpServerResponse])
def list_mcp_servers(
    service: McpServerService = Depends(get_mcp_service),
) -> list[McpServerResponse]:
    """列出所有 MCP server。"""
    servers = service.list_servers()
    return [McpServerResponse(**s) for s in servers]


@router.get("/{server_id}", response_model=McpServerResponse)
def get_mcp_server(
    server_id: str,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerResponse:
    """获取单个 MCP server。"""
    result = service.get_server(server_id)
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return McpServerResponse(**result)


@router.post("", response_model=McpServerResponse, status_code=201)
def create_mcp_server(
    body: McpServerCreateRequest,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerResponse:
    """添加 MCP server。"""
    try:
        result = service.add_server(
            name=body.name,
            transport=body.transport,
            command=body.command,
            args=body.args,
            url=body.url,
            headers=body.headers,
            secret_header_keys=body.secretHeaderKeys,
            env=body.env,
            secret_env_keys=body.secretEnvKeys,
            preset_slug=body.presetSlug,
        )
        return McpServerResponse(**result)
    except ValueError as exc:
        if "已存在" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if "占位符" in str(exc) or "HTTP" in str(exc):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/import-json", response_model=McpServerJsonImportResponse)
def import_mcp_json(
    body: McpServerJsonImportRequest,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerJsonImportResponse:
    """从 JSON 粘贴导入 MCP server 配置（预览，不落库）。"""
    try:
        previews = parse_mcp_json(body.jsonText)
        return McpServerJsonImportResponse(
            servers=[McpServerParsedPreview(**p.to_dict()) for p in previews]
        )
    except McpJsonParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{server_id}/test-connection", response_model=McpServerTestConnectionResponse)
def test_mcp_server_connection(
    server_id: str,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerTestConnectionResponse:
    """测试 MCP server 连接。"""
    if not service.sdk_available:
        return McpServerTestConnectionResponse(
            success=False,
            error="MCP SDK 不可用，无法测试连接",
        )

    try:
        service.get_server_detail(server_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    tools, error = service.test_connection(server_id)
    if error:
        return McpServerTestConnectionResponse(
            success=False,
            error=error,
        )
    return McpServerTestConnectionResponse(
        success=True,
        toolCount=len(tools),
        tools=[t.to_dict() for t in tools],
    )


@router.patch("/{server_id}", response_model=McpServerResponse)
def update_mcp_server(
    server_id: str,
    body: McpServerUpdateRequest,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerResponse:
    """更新 MCP server 配置。"""
    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        # camelCase → snake_case 映射（与 create_mcp_server 保持一致）
        if "secretEnvKeys" in fields:
            fields["secret_env_keys"] = fields.pop("secretEnvKeys")
        if "secretHeaderKeys" in fields:
            fields["secret_header_keys"] = fields.pop("secretHeaderKeys")
        result = service.update_server(server_id, **fields)
        return McpServerResponse(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{server_id}/enable", response_model=McpServerResponse)
def enable_mcp_server(
    server_id: str,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerResponse:
    """启用 MCP server。"""
    try:
        result = service.enable_server(server_id)
        return McpServerResponse(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (McpServerDisconnectedError, McpToolTimeoutError) as exc:
        raise HTTPException(status_code=503, detail=_sanitize_api_error(str(exc))) from exc
    except McpCircuitBreakerOpenError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeError as exc:
        # MCP SDK 不可用等
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{server_id}/disable", response_model=McpServerResponse)
def disable_mcp_server(
    server_id: str,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerResponse:
    """禁用 MCP server。"""
    try:
        result = service.disable_server(server_id)
        return McpServerResponse(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{server_id}/reconnect", response_model=McpServerResponse)
def reconnect_mcp_server(
    server_id: str,
    service: McpServerService = Depends(get_mcp_service),
) -> McpServerResponse:
    """重连 MCP server。"""
    try:
        result = service.reconnect_server(server_id)
        return McpServerResponse(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (McpServerDisconnectedError, McpToolTimeoutError) as exc:
        raise HTTPException(status_code=503, detail=_sanitize_api_error(str(exc))) from exc
    except McpCircuitBreakerOpenError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/{server_id}", status_code=204)
def delete_mcp_server(
    server_id: str,
    service: McpServerService = Depends(get_mcp_service),
) -> Response:
    """删除 MCP server。"""
    success = service.delete_server(server_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return Response(status_code=204)
