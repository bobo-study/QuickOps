from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agno.tools import Toolkit

from quickops.domain import PermissionMode


def _ensure_readonly_query(query: str) -> None:
    normalized = query.lstrip().lower()
    allowed = ("select", "show", "describe", "desc", "explain", "with", "match", "call db.")
    if not normalized.startswith(allowed):
        raise PermissionError("当前为只读模式，只允许查询、描述和执行计划语句")


class SessionDatabaseTools(Toolkit):
    """Thin session-only connection layer backed by Agno's official database toolkits."""

    def __init__(
        self,
        database_kind: str,
        permission_mode: PermissionMode,
        session_config: dict[str, Any],
    ):
        self.database_kind = database_kind
        self.readonly = permission_mode == PermissionMode.READONLY
        self.session_config = session_config
        method_name = f"query_{database_kind}"
        method = getattr(self, method_name)
        confirmations = (
            [method_name]
            if permission_mode
            in {PermissionMode.APPROVAL, PermissionMode.DELEGATED_APPROVAL}
            else []
        )
        super().__init__(
            name=f"session_{database_kind}_tools",
            tools=[method],
            instructions=(
                "数据库连接参数只缓存在当前 QuickOps 会话中，不保存为长期设置。"
                "如果当前会话尚未提供必需参数，先明确向用户索取；已有参数应直接复用，"
                "不要重复询问，也不要猜测主机、账号、口令、数据库名、项目或数据集。"
            ),
            add_instructions=True,
            requires_confirmation_tools=confirmations,
        )

    def _connection(self, **provided: Any) -> dict[str, Any]:
        self.session_config.update(
            {key: value for key, value in provided.items() if value not in (None, "")}
        )
        return self.session_config

    @staticmethod
    def _require(config: dict[str, Any], *keys: str) -> None:
        missing = [key for key in keys if not config.get(key)]
        if missing:
            raise ValueError(
                "当前会话缺少数据库连接参数："
                + "、".join(missing)
                + "。请先向用户询问这些参数。"
            )

    def query_sql(
        self, query: str, db_url: str | None = None, limit: int = 100
    ) -> str:
        """Run SQL; db_url is requested once and then reused in this session."""
        if self.readonly:
            _ensure_readonly_query(query)
        from agno.tools.sql import SQLTools

        config = self._connection(db_url=db_url)
        self._require(config, "db_url")
        return SQLTools(db_url=config["db_url"]).run_sql_query(query=query, limit=limit)

    def query_postgres(
        self,
        query: str,
        host: str | None = None,
        db_name: str | None = None,
        user: str | None = None,
        password: str | None = None,
        port: int | None = None,
    ) -> str:
        """Connect to PostgreSQL for this call and run a query without saving credentials."""
        if self.readonly:
            _ensure_readonly_query(query)
        from agno.tools.postgres import PostgresTools

        config = self._connection(
            host=host, db_name=db_name, user=user, password=password, port=port
        )
        self._require(config, "host", "db_name", "user", "password")
        return PostgresTools(
            host=config["host"],
            db_name=config["db_name"],
            user=config["user"],
            password=config["password"],
            port=config.get("port", 5432),
        ).run_query(query)

    def query_neo4j(
        self,
        query: str,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> list:
        """Connect to Neo4j for this call and run Cypher without saving credentials."""
        if self.readonly:
            _ensure_readonly_query(query)
        from agno.tools.neo4j import Neo4jTools

        config = self._connection(
            uri=uri, user=user, password=password, database=database
        )
        self._require(config, "uri", "user", "password")
        return Neo4jTools(
            uri=config["uri"],
            user=config["user"],
            password=config["password"],
            database=config.get("database", "neo4j"),
        ).run_cypher_query(query)

    def query_redshift(
        self,
        query: str,
        host: str | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        port: int | None = None,
    ) -> str:
        """Connect to Amazon Redshift for this call and run a query."""
        if self.readonly:
            _ensure_readonly_query(query)
        from agno.tools.redshift import RedshiftTools

        config = self._connection(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port,
        )
        self._require(config, "host", "database", "user", "password")
        return RedshiftTools(
            host=config["host"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
            port=config.get("port", 5439),
        ).run_query(query)

    def query_bigquery(
        self,
        query: str,
        project: str | None = None,
        dataset: str | None = None,
        location: str | None = None,
    ) -> str:
        """Use ambient Google credentials for this call and run a BigQuery SQL query."""
        if self.readonly:
            _ensure_readonly_query(query)
        from agno.tools.google.bigquery import GoogleBigQueryTools

        config = self._connection(
            project=project, dataset=dataset, location=location
        )
        self._require(config, "project", "dataset", "location")
        return GoogleBigQueryTools(
            project=config["project"],
            dataset=config["dataset"],
            location=config["location"],
        ).run_sql_query(query)


@dataclass(frozen=True)
class ToolkitSpec:
    id: str
    name: str
    category: str
    description: str
    module: str
    class_name: str
    dependencies: tuple[str, ...] = ()
    config_requirements: tuple[str, ...] = ()
    default_enabled: bool = False


@dataclass(frozen=True)
class ToolkitLoadReport:
    id: str
    enabled: bool
    available: bool
    reason: str | None = None


@dataclass
class ToolkitBuildResult:
    tools: list[Toolkit]
    reports: list[ToolkitLoadReport]


# This is deliberately explicit. Importing every agno.tools module eagerly would make one
# optional vendor dependency capable of preventing QuickOps from starting.
TOOLKIT_SPECS: tuple[ToolkitSpec, ...] = (
    ToolkitSpec(
        "coding",
        "编码工具",
        "development",
        "Agno 文件编辑、代码检索与受控 Shell 工具。",
        "agno.tools.coding",
        "CodingTools",
    ),
    ToolkitSpec(
        "docker",
        "Docker 工具",
        "infrastructure",
        "Agno Docker 容器、镜像、卷与网络管理工具。",
        "agno.tools.docker",
        "DockerTools",
        dependencies=("docker",),
    ),
    ToolkitSpec(
        "file",
        "文件工具",
        "filesystem",
        "Agno 大文件分块读取、搜索、保存与替换工具。",
        "agno.tools.file",
        "FileTools",
    ),
    ToolkitSpec(
        "filesystem",
        "本地文件系统",
        "filesystem",
        "Agno LocalFileSystemTools，工作区内文件读写。",
        "agno.tools.local_file_system",
        "LocalFileSystemTools",
    ),
    ToolkitSpec(
        "python",
        "Python 工具",
        "development",
        "Agno Python 代码、脚本和依赖安装工具。",
        "agno.tools.python",
        "PythonTools",
    ),
    ToolkitSpec(
        "workspace",
        "Workspace 工具",
        "filesystem",
        "Agno Workspace 统一的读写、搜索、移动与命令执行工具。",
        "agno.tools.workspace",
        "Workspace",
    ),
    ToolkitSpec(
        "web_search",
        "网页搜索",
        "web",
        "Agno WebSearchTools，支持网页与新闻搜索。",
        "agno.tools.websearch",
        "WebSearchTools",
        dependencies=("ddgs",),
    ),
    ToolkitSpec(
        "database.sql",
        "SQL 数据库",
        "database",
        "Agno SQLAlchemy 通用数据库工具。",
        "agno.tools.sql",
        "SQLTools",
        config_requirements=("db_url",),
    ),
    ToolkitSpec(
        "database.postgres",
        "PostgreSQL",
        "database",
        "Agno PostgreSQL 架构、查询、汇总和导出工具（连接为只读）。",
        "agno.tools.postgres",
        "PostgresTools",
        dependencies=("psycopg",),
        config_requirements=("db_name", "host", "user", "password"),
    ),
    ToolkitSpec(
        "database.duckdb",
        "DuckDB",
        "database",
        "Agno DuckDB 查询、文件导入导出和全文检索工具。",
        "agno.tools.duckdb",
        "DuckDbTools",
        dependencies=("duckdb",),
    ),
    ToolkitSpec(
        "database.neo4j",
        "Neo4j",
        "database",
        "Agno Neo4j 图数据库架构与 Cypher 工具。",
        "agno.tools.neo4j",
        "Neo4jTools",
        dependencies=("neo4j",),
        config_requirements=("uri", "user", "password"),
    ),
    ToolkitSpec(
        "database.redshift",
        "Amazon Redshift",
        "database",
        "Agno Redshift 查询、架构、汇总与导出工具。",
        "agno.tools.redshift",
        "RedshiftTools",
        dependencies=("redshift_connector",),
        config_requirements=("host", "database"),
    ),
    ToolkitSpec(
        "database.bigquery",
        "Google BigQuery",
        "database",
        "Agno Google BigQuery 数据集架构与 SQL 工具。",
        "agno.tools.google.bigquery",
        "GoogleBigQueryTools",
        dependencies=("google.cloud.bigquery",),
        config_requirements=("dataset", "project", "location"),
    ),
)


def _dependency_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _missing(
    spec: ToolkitSpec,
    config: dict[str, Any],
    *,
    include_session_config: bool = True,
) -> list[str]:
    missing = [
        f"依赖 {name}"
        for name in spec.dependencies
        if not _dependency_exists(name)
    ]
    if include_session_config:
        missing.extend(
            f"配置 {key}" for key in spec.config_requirements if not config.get(key)
        )
    return missing


def toolkit_catalog(configs: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    configs = configs or {}
    result: list[dict[str, Any]] = []
    for spec in TOOLKIT_SPECS:
        missing = _missing(
            spec,
            configs.get(spec.id, {}),
            include_session_config=False,
        )
        item = asdict(spec)
        item["available"] = not missing
        item["unavailable_reason"] = f"缺少{'\u3001'.join(missing)}" if missing else None
        result.append(item)
    return result


def _confirmation_kwargs(permission_mode: PermissionMode, names: list[str]) -> dict[str, Any]:
    if permission_mode in {PermissionMode.APPROVAL, PermissionMode.DELEGATED_APPROVAL}:
        return {"requires_confirmation_tools": names}
    return {}


def _construct(
    spec: ToolkitSpec,
    config: dict[str, Any],
    workspace_root: Path,
    permission_mode: PermissionMode,
) -> Toolkit:
    module = importlib.import_module(spec.module)
    cls: Callable[..., Toolkit] = getattr(module, spec.class_name)
    readonly = permission_mode == PermissionMode.READONLY
    confirmation: dict[str, Any]

    if spec.id.startswith("database.") and spec.id != "database.duckdb":
        return SessionDatabaseTools(
            spec.id.removeprefix("database."), permission_mode, config
        )

    if spec.id == "coding":
        confirmation = _confirmation_kwargs(
            permission_mode, ["edit_file", "write_file", "run_shell"]
        )
        return cls(
            base_dir=workspace_root,
            restrict_to_base_dir=True,
            enable_edit_file=not readonly,
            enable_write_file=not readonly,
            enable_run_shell=not readonly,
            enable_grep=True,
            enable_find=True,
            enable_ls=True,
            **confirmation,
        )
    if spec.id == "file":
        confirmation = _confirmation_kwargs(
            permission_mode, ["save_file", "replace_file_chunk"]
        )
        return cls(
            base_dir=workspace_root,
            enable_save_file=not readonly,
            enable_replace_file_chunk=not readonly,
            enable_delete_file=False,
            **confirmation,
        )
    if spec.id == "filesystem":
        confirmation = _confirmation_kwargs(permission_mode, ["write_file"])
        return cls(
            target_directory=str(workspace_root),
            restrict_to_base_dir=True,
            enable_write_file=not readonly,
            **confirmation,
        )
    if spec.id == "python":
        if readonly:
            raise PermissionError("只读模式不开放 Python 执行工具")
        confirmation = _confirmation_kwargs(
            permission_mode,
            [
                "save_to_file_and_run",
                "run_python_code",
                "pip_install_package",
                "uv_pip_install_package",
                "run_python_file_return_variable",
            ],
        )
        return cls(base_dir=workspace_root, restrict_to_base_dir=True, **confirmation)
    if spec.id == "workspace":
        allowed = ["read", "list", "search"] if readonly else None
        confirm = (
            ["write", "edit", "move", "delete", "shell"]
            if permission_mode in {PermissionMode.APPROVAL, PermissionMode.DELEGATED_APPROVAL}
            else []
        )
        return cls(root=workspace_root, allowed=allowed, confirm=confirm)
    if spec.id == "web_search":
        return cls(fixed_max_results=8, timeout=15)
    if spec.id == "docker":
        if readonly:
            include = [
                "list_containers",
                "get_container_logs",
                "inspect_container",
                "list_images",
                "inspect_image",
                "list_volumes",
                "inspect_volume",
                "list_networks",
                "inspect_network",
            ]
            return cls(include_tools=include)
        mutating = [
            "start_container",
            "stop_container",
            "remove_container",
            "run_container",
            "exec_in_container",
            "pull_image",
            "remove_image",
            "build_image",
            "tag_image",
            "create_volume",
            "remove_volume",
            "create_network",
            "remove_network",
            "connect_container_to_network",
            "disconnect_container_from_network",
        ]
        return cls(**_confirmation_kwargs(permission_mode, mutating))
    if spec.id == "database.sql":
        return cls(
            db_url=config["db_url"],
            enable_run_sql_query=not readonly,
            **_confirmation_kwargs(permission_mode, ["run_sql_query"]),
        )
    if spec.id == "database.postgres":
        kwargs = dict(config)
        if readonly:
            kwargs["exclude_tools"] = ["export_table_to_path"]
        else:
            kwargs.update(_confirmation_kwargs(permission_mode, ["export_table_to_path"]))
        return cls(**kwargs)
    if spec.id == "database.duckdb":
        read_tools = [
            "show_tables",
            "describe_table",
            "inspect_query",
            "run_query",
            "summarize_table",
            "full_text_search",
        ]
        mutating = [
            "create_table_from_path",
            "export_table_to_path",
            "load_local_path_to_table",
            "load_local_csv_to_table",
            "load_s3_path_to_table",
            "load_s3_csv_to_table",
            "create_fts_index",
        ]
        return cls(
            db_path=config.get("db_path"),
            read_only=readonly,
            include_tools=read_tools if readonly else None,
            **_confirmation_kwargs(permission_mode, mutating),
        )
    if spec.id == "database.neo4j":
        return cls(
            **config,
            enable_run_cypher=not readonly,
            **_confirmation_kwargs(permission_mode, ["run_cypher_query"]),
        )
    if spec.id == "database.redshift":
        kwargs = dict(config)
        if readonly:
            kwargs["exclude_tools"] = ["export_table_to_path"]
        else:
            kwargs.update(_confirmation_kwargs(permission_mode, ["export_table_to_path"]))
        return cls(**kwargs)
    if spec.id == "database.bigquery":
        return cls(
            **config,
            run_sql_query=not readonly,
            **_confirmation_kwargs(permission_mode, ["run_sql_query"]),
        )
    raise KeyError(spec.id)


def build_enabled_toolkits(
    enabled_ids: tuple[str, ...] | list[str] | set[str],
    *,
    configs: dict[str, dict[str, Any]] | None,
    workspace_root: Path,
    permission_mode: PermissionMode,
) -> ToolkitBuildResult:
    """Build selected official Agno toolkits without making optional failures fatal."""

    configs = configs or {}
    selected = set(enabled_ids)
    tools: list[Toolkit] = []
    reports: list[ToolkitLoadReport] = []
    for spec in TOOLKIT_SPECS:
        enabled = spec.id in selected
        if not enabled:
            reports.append(
                ToolkitLoadReport(
                    spec.id,
                    False,
                    not _missing(
                        spec,
                        configs.get(spec.id, {}),
                        include_session_config=False,
                    ),
                )
            )
            continue
        missing = _missing(
            spec,
            configs.get(spec.id, {}),
            include_session_config=False,
        )
        if missing:
            reports.append(
                ToolkitLoadReport(spec.id, True, False, f"缺少{'\u3001'.join(missing)}")
            )
            continue
        try:
            tools.append(
                _construct(
                    spec,
                    configs.get(spec.id, {}),
                    workspace_root.resolve(),
                    permission_mode,
                )
            )
            reports.append(ToolkitLoadReport(spec.id, True, True))
        except Exception as error:  # optional services/dependencies must not stop AgentOS
            reports.append(ToolkitLoadReport(spec.id, True, False, str(error)[:500]))
    unknown = selected.difference(spec.id for spec in TOOLKIT_SPECS)
    reports.extend(
        ToolkitLoadReport(item, True, False, "未知工具箱") for item in sorted(unknown)
    )
    return ToolkitBuildResult(tools=tools, reports=reports)
