import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ActivityIcon as Activity,
  CaretDown,
  CaretRight,
  Check,
  CheckCircle,
  Copy,
  Cpu,
  DownloadSimple,
  Eye,
  FileText,
  ImageSquare,
  Gear,
  GitBranch,
  HardDrives,
  Info,
  LockSimple,
  Moon,
  ArrowClockwise,
  PaperPlaneTilt,
  Paperclip,
  PencilSimple,
  Plus,
  Robot,
  ShieldCheck,
  SignOut,
  Stop,
  Sun,
  TerminalWindow,
  Wrench,
  Trash,
  UserCircle,
  Warning,
  WifiHigh,
  X,
} from "@phosphor-icons/react";

const permissionCatalog = [
  {
    id: "readonly",
    apiId: "readonly",
    label: "只读模式",
    note: "仅查看、分析和诊断",
    icon: LockSimple,
  },
  {
    id: "approval",
    apiId: "approval",
    label: "审批执行",
    note: "编辑文件或修改系统前均需审批",
    icon: FileText,
  },
  {
    id: "assisted",
    apiId: "delegated_approval",
    label: "替我审批",
    note: "自动执行可恢复变更，仅高危操作请你审批",
    icon: ShieldCheck,
  },
  {
    id: "full",
    apiId: "full_access",
    label: "完全访问",
    note: "小维可不受限制地操作当前电脑",
    icon: TerminalWindow,
  },
];

const fallbackModel = {
  id: "deepseek-v4-flash",
  name: "DeepSeek-V4-Flash",
  provider: "SiliconFlow",
  model_id: "deepseek-ai/DeepSeek-V4-Flash",
  max_context_k: 128,
  supports_vision: false,
  is_default: true,
};
const runStatusLabels = {
  "RunStatus.completed": "已完成",
  completed: "已完成",
  "RunStatus.failed": "失败",
  failed: "失败",
  "RunStatus.cancelled": "已取消",
  cancelled: "已取消",
};

const englishUi = {
  "刚刚": "Just now",
  "只读模式": "Read only",
  "仅查看、分析和诊断": "Observe, analyze, and diagnose only",
  "审批执行": "Approval required",
  "编辑文件或修改系统前均需审批": "Approval is required before files or systems are changed",
  "替我审批": "Risk-based approval",
  "自动执行可恢复变更，仅高危操作请你审批": "Run recoverable changes automatically; ask only for high-risk operations",
  "完全访问": "Full access",
  "小维可不受限制地操作当前电脑": "Xiaowei may operate this computer without restrictions",
  "执行中": "Running",
  "已执行": "Executed",
  "受控": "Controlled",
  "复制消息": "Copy message",
  "从此处分支": "Branch from here",
  "编辑并重新发送": "Edit and resend",
  "执行审批": "Execution approval",
  "需要你的批准": "Your approval is required",
  "小维申请执行以下操作": "Xiaowei requests permission to perform the following operation",
  "需确认": "Confirmation required",
  "拒绝": "Reject",
  "批准并继续": "Approve and continue",
  "审批操作已处理": "Approval request processed",
  "正在思考": "Thinking",
  "等待执行审批": "Waiting for execution approval",
  "运行失败": "Run failed",
  "回复已由操作员中止。": "The response was stopped by the operator.",
  "已完成": "Completed",
  "正在分析工具结果": "Analyzing tool results",
  "正在压缩会话上下文": "Compressing conversation context",
  "上下文压缩完成": "Context compression completed",
  "上下文压缩失败，正在保留原上下文继续": "Context compression failed; continuing with the original context",
  "正在生成回复": "Generating response",
  "执行中…": "Running…",
  "低风险": "Low risk",
  "中风险": "Medium risk",
  "高风险": "High risk",
  "严重风险": "Critical risk",
  "登录状态已失效，请重新登录。": "Your session has expired. Please sign in again.",
  "目标主机信息尚未就绪": "Target host information is not ready",
  "新会话": "New session",
  "已创建新会话": "New session created",
  "其他工具": "Other tools",
  "当前服务环境缺少所需依赖": "Required dependencies are missing from the service environment",
  "已中止当前回复": "The current response was stopped",
  "已批准，小维将继续执行": "Approved. Xiaowei will continue",
  "已拒绝，小维将调整方案": "Rejected. Xiaowei will adjust the plan",
  "请选择下一步": "Choose the next step",
  "需要你的选择": "Your choice is needed",
  "继续": "Continue",
  "开发与编码": "Development and coding",
  "基础设施": "Infrastructure",
  "文件与工作区": "Files and workspace",
  "网页与检索": "Web and search",
  "数据分析": "Data analysis",
  "数据库": "Databases",
  "重命名会话": "Rename session",
  "会话已重命名": "Session renamed",
  "会话已删除": "Session deleted",
  "终端会话已重启": "Terminal session restarted",
  "模型配置已保存": "Model configuration saved",
  "消息已复制": "Message copied",
  "会话 ID 已复制": "Session ID copied",
  "复制会话 ID": "Copy session ID",
  "复制失败，请检查浏览器权限": "Copy failed. Check browser permissions",
  "已从该消息创建分支会话": "A branch session was created from this message",
  "设置已保存": "Settings saved",
  "诊断报告已导出": "Diagnostic report exported",
  "正在验证 QuickOps 登录状态…": "Verifying QuickOps sign-in status…",
  "登录运维工作台": "Sign in to the operations workspace",
  "验证身份后才能访问主机、终端和会话数据。": "Verify your identity to access hosts, terminals, and session data.",
  "服务端尚未配置登录凭据。请设置": "Server sign-in credentials are not configured. Set",
  "后重启服务。": "and restart the service.",
  "账号": "Username",
  "密码": "Password",
  "正在登录…": "Signing in…",
  "登录": "Sign in",
  "新建会话": "New session",
  "最近会话": "Recent sessions",
  "任务执行中": "Task running",
  "任务已完成": "Task completed",
  "删除会话": "Delete session",
  "暂无会话": "No sessions yet",
  "运维工程师": "Operations engineer",
  "退出登录": "Sign out",
  "打开设置": "Open settings",
  "未创建": "Not created",
  "会话 ID：": "Session ID: ",
  "导出报告": "Export report",
  "从一个运维目标开始": "Start with an operations objective",
  "描述排查目标，或切换到手动命令直接使用目标主机的终端。": "Describe what you want to investigate, or switch to Manual command to use the target host terminal directly.",
  "编辑后发送将覆盖当前会话，并在报告中保留修订前记录": "Sending the edit replaces the active turn while preserving the original in reports",
  "取消编辑": "Cancel edit",
  "AI 会话": "AI session",
  "手动命令": "Manual command",
  "重启终端（重置当前路径和临时环境）": "Restart terminal (reset the current path and temporary environment)",
  "重启终端": "Restart terminal",
  "选择模型": "Select model",
  "默认": "Default",
  "配置自定义模型": "Configure custom model",
  "前往设置中心": "Open Settings",
  "服务端尚未启用": "Not enabled on the server",
  "单个附件不能超过 25 MB": "An attachment cannot exceed 25 MB",
  "正在获取当前路径": "Getting the current path",
  "正在获取": "Loading",
  "正在获取路径…": "Getting path…",
  "移除附件": "Remove attachment",
  "当前模型未启用图像理解能力": "Image understanding is not enabled for the current model",
  "输入你的运维问题或下一步指令…": "Describe an operations issue or enter the next instruction…",
  "在当前终端会话中输入 Shell 命令…": "Enter a shell command in the current terminal session…",
  "中止回复": "Stop response",
  "发送消息": "Send message",
  "目标主机": "Target host",
  "未连接": "Not connected",
  "本机": "Local",
  "环境": "Environment",
  "本地测试": "Local test",
  "平台": "Platform",
  "标签": "Tags",
  "主机信号（实时）": "Host signals (live)",
  "CPU 使用率": "CPU usage",
  "负载（1m）": "Load (1m)",
  "内存使用率": "Memory usage",
  "磁盘使用率": "Disk usage",
  "网络（出/入）": "Network (out/in)",
  "设置中心": "Settings",
  "设置": "Settings",
  "QuickOps 控制中心": "QuickOps control center",
  "通用": "General",
  "模型": "Models",
  "工具箱": "Toolbox",
  "设置 / ": "Settings / ",
  "通用设置": "General settings",
  "模型管理": "Model management",
  "关闭设置": "Close settings",
  "界面语言": "Interface language",
  "界面配色": "Color theme",
  "夜间": "Dark",
  "日间": "Light",
  "简体中文": "Simplified Chinese",
  "新会话默认权限": "Default permission for new sessions",
  "主机信号刷新间隔（秒）": "Host signal refresh interval (seconds)",
  "保存通用设置": "Save general settings",
  "已配置模型": "Configured models",
  "新增": "Add",
  "设为默认": "Set as default",
  "编辑模型": "Edit model",
  "新增模型": "Add model",
  "模型名称": "Model name",
  "显示名称": "Display name",
  "服务商": "Provider",
  "模型 ID": "Model ID",
  "接口地址": "Base URL",
  "接口协议": "API protocol",
  "访问密钥": "API key",
  "思考模式": "Thinking mode",
  "最大上下文（k tokens）": "Maximum context (k tokens)",
  "图像理解（多模态）": "Image understanding (multimodal)",
  "启用此模型": "Enable this model",
  "设为默认模型": "Make default",
  "留空表示保留现有密钥": "Leave blank to keep the existing key",
  "输入访问密钥": "Enter access key",
  "自动（遵循模型默认）": "Automatic (use model default)",
  "开启": "On",
  "关闭": "Off",
  "保存配置": "Save configuration",
  "密钥仅提交并保存在服务端受限存储中；已配置模型可修改或停用，不可删除。": "Keys are submitted to and stored only in restricted server-side storage. Configured models may be edited or disabled, but not deleted.",
  "清空": "Clear",
  "按需启用小维能力": "Enable Xiaowei capabilities as needed",
  "扩展工具默认关闭。启用后会在下一次 AI 运行时加入小维的工具箱，并继续受当前权限模式与审批策略约束。": "Optional tools are disabled by default. Enabled tools join Xiaowei's toolbox on the next AI run and remain governed by the current permission and approval policy.",
  "正在读取工具目录…": "Loading tool catalog…",
  "为小维提供对应的专业操作能力。": "Provides Xiaowei with the corresponding specialist capability.",
  "停用": "Disable",
  "启用": "Enable",
  "服务端尚未提供可用的扩展工具。": "The server has not provided any optional tools.",
  "主机资产": "Host assets",
  "管理服务": "Manage services",
  "添加服务": "Add service",
  "暂无服务资产": "No service assets yet",
  "状态": "Status",
  "事件": "Events",
  "文档": "Documents",
  "正常": "Healthy",
  "异常": "Degraded",
  "不可用": "Down",
  "待探测": "Pending",
  "已挂载": "Mounted",
  "挂载到会话": "Mount in session",
  "取消挂载": "Unmount",
  "服务名称": "Service name",
  "服务说明": "Service description",
  "探测方式": "Probe type",
  "探测目标": "Probe target",
  "探测间隔（秒）": "Probe interval (seconds)",
  "进程名称": "Process name",
  "系统服务": "System service",
  "HTTP 地址": "HTTP URL",
  "TCP 地址": "TCP address",
  "启用自动监控": "Enable automatic monitoring",
  "保存服务": "Save service",
  "立即探测": "Check now",
  "删除服务": "Delete service",
  "新增运维事件": "Add operations event",
  "事件标题": "Event title",
  "事件详情": "Event details",
  "严重级别": "Severity",
  "保存事件": "Save event",
  "上传文档": "Upload document",
  "下载文档": "Download document",
  "预览文档": "Preview document",
  "文档预览": "Document preview",
  "暂无可预览的文本内容": "No previewable text is available",
  "重命名文档": "Rename document",
  "删除文档": "Delete document",
  "删除运维事件": "Delete operations event",
  "该服务尚无运维事件": "No operations events for this service",
  "该服务尚无文档": "No documents for this service",
  "服务资产已保存": "Service asset saved",
  "服务资产已删除": "Service asset deleted",
  "探测已完成": "Health check completed",
  "运维事件已保存": "Operations event saved",
  "文档已上传": "Document uploaded",
  "已挂载服务资产": "Service asset mounted",
  "已取消挂载": "Service asset unmounted",
  "创建排查会话": "Create investigation session",
  "已从运维事件创建排查会话": "Investigation session created from the event",
  "请先创建会话": "Create a session first",
  "上传文件将同时归档到已挂载服务的文档库": "Uploaded files are also archived to the mounted service library",
  "推荐": "Recommended",
  "功能重叠": "Overlapping",
  "可替代": "Alternative",
  "专用": "Specialized",
};

function translate(locale, key, variables = {}) {
  const template = locale === "en-US" ? englishUi[key] || key : key;
  return String(template).replace(/\{(\w+)\}/g, (_, name) => variables[name] ?? "");
}

const authStorageKey = "quickops_session_token";
let sessionAccessToken =
  typeof window === "undefined"
    ? ""
    : window.sessionStorage.getItem(authStorageKey) || "";

function saveSessionAccessToken(token) {
  sessionAccessToken = token || "";
  if (typeof window === "undefined") return;
  if (sessionAccessToken)
    window.sessionStorage.setItem(authStorageKey, sessionAccessToken);
  else window.sessionStorage.removeItem(authStorageKey);
}

async function api(path, options = {}) {
  const authorization = sessionAccessToken
    ? { Authorization: `Bearer ${sessionAccessToken}` }
    : {};
  const formData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(formData ? {} : { "Content-Type": "application/json" }),
      ...authorization,
      ...(options.headers || {}),
    },
  });
  const data =
    response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    if (
      response.status === 401 &&
      !path.endsWith("/auth/login") &&
      !path.endsWith("/auth/status")
    ) {
      saveSessionAccessToken("");
      window.dispatchEvent(new CustomEvent("quickops:unauthorized"));
    }
    const detail = data?.detail || data?.message;
    const error = new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ||
          (detail ? JSON.stringify(detail) : `请求失败（${response.status}）`),
    );
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

async function downloadAuthenticatedFile(path, filename) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: sessionAccessToken
      ? { Authorization: `Bearer ${sessionAccessToken}` }
      : {},
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data?.detail || `下载失败（${response.status}）`);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename || "download";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function fetchAuthenticatedBlob(path) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: sessionAccessToken
      ? { Authorization: `Bearer ${sessionAccessToken}` }
      : {},
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data?.detail || `请求失败（${response.status}）`);
  }
  return response.blob();
}

function authenticatedEventStream(url) {
  if (!sessionAccessToken) return new EventSource(url);

  const controller = new AbortController();
  const listeners = new Map();
  const source = {
    readyState: EventSource.CONNECTING,
    onerror: null,
    addEventListener(name, listener) {
      listeners.set(name, [...(listeners.get(name) || []), listener]);
    },
    close() {
      source.readyState = EventSource.CLOSED;
      controller.abort();
    },
  };
  const dispatch = (type, data) => {
    const event = { type, data };
    for (const listener of listeners.get(type) || []) listener(event);
  };

  Promise.resolve().then(async () => {
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: {
          Accept: "text/event-stream",
          Authorization: `Bearer ${sessionAccessToken}`,
        },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        if (response.status === 401) {
          saveSessionAccessToken("");
          window.dispatchEvent(new CustomEvent("quickops:unauthorized"));
        }
        throw new Error(`事件流连接失败（${response.status}）`);
      }
      source.readyState = EventSource.OPEN;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (source.readyState !== EventSource.CLOSED) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          let type = "message";
          const data = [];
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) type = line.slice(6).trim() || "message";
            if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
          }
          if (data.length) dispatch(type, data.join("\n"));
        }
      }
      source.readyState = EventSource.CLOSED;
    } catch (error) {
      if (error.name === "AbortError") return;
      source.readyState = EventSource.CLOSED;
      source.onerror?.(error);
    }
  });
  return source;
}

const listFrom = (data, key) =>
  Array.isArray(data) ? data : Array.isArray(data?.[key]) ? data[key] : [];
const serverDate = (value) =>
  new Date(
    typeof value === "string" && !/(?:Z|[+-]\d\d:\d\d)$/.test(value)
      ? `${value}Z`
      : value,
  );
const timeOf = (value, locale = "zh-CN") =>
  value
    ? serverDate(value).toLocaleString(locale, {
        hour12: false,
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : translate(locale, "刚刚");
const clockOf = (value, locale = "zh-CN") =>
  value
    ? serverDate(value).toLocaleTimeString(locale, { hour12: false })
    : new Date().toLocaleTimeString(locale, { hour12: false });

function ToolTrace({ name, duration, status = "completed", children, t }) {
  const [open, setOpen] = useState(status === "running");
  const previousStatus = useRef(status);
  useEffect(() => {
    if (status === "running") setOpen(true);
    else if (previousStatus.current === "running") setOpen(false);
    previousStatus.current = status;
  }, [status]);
  return (
    <section className="tool-trace">
      <button
        className="tool-head"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open ? <CaretDown size={14} /> : <CaretRight size={14} />}
        {status === "running" ? (
          <Activity size={16} className="tool-running-icon" />
        ) : (
          <CheckCircle size={16} weight="fill" className="success-icon" />
        )}
        <span>{status === "running" ? t("执行中") : t("已执行")}</span>
        <code>{name}</code>
        <span className="readonly-chip">{t("受控")}</span>
        <span className="tool-duration">{duration}</span>
      </button>
      {open && <div className="tool-output">{children}</div>}
    </section>
  );
}

function MessageFooter({
  message,
  onCopy,
  onBranch,
  onEdit,
  canBranch,
  canEdit,
  t,
}) {
  return (
    <div className="message-footer">
      <button
        onClick={() => onCopy(message)}
        title={t("复制消息")}
        aria-label={t("复制消息")}
      >
        <Copy size={13} />
      </button>
      {canBranch && (
        <button
          onClick={() => onBranch(message)}
          title={t("从此处分支")}
          aria-label={t("从此处分支")}
        >
          <GitBranch size={13} />
        </button>
      )}
      {canEdit && (
        <button
          onClick={() => onEdit(message)}
          title={t("编辑并重新发送")}
          aria-label={t("编辑并重新发送")}
        >
          <PencilSimple size={13} />
        </button>
      )}
      <time>{message.time}</time>
    </div>
  );
}

function ApprovalPrompt({ approval, onDecision, pending, t }) {
  return (
    <div className="approval-prompt" role="alertdialog" aria-label={t("执行审批")}>
      <div className="approval-prompt-head">
        <ShieldCheck size={18} weight="fill" />
        <div>
          <strong>{t("需要你的批准")}</strong>
          <span>{t("小维申请执行以下操作")}</span>
        </div>
        <span className={`risk-chip ${approval.risk || "medium"}`}>
          {t(approval.risk_label || approval.risk || "需确认")}
        </span>
      </div>
      <div className="approval-operation-list">
        {approval.operations.map((operation) => (
          <div className="approval-operation" key={operation.id}>
            <code>{operation.toolName}</code>
            <strong>{operation.title}</strong>
            {operation.detail && <pre>{operation.detail}</pre>}
          </div>
        ))}
      </div>
      <div className="approval-actions">
        <button disabled={pending} onClick={() => onDecision(approval, "reject")}>
          {t("拒绝")}
        </button>
        <button
          className="primary"
          disabled={pending}
          onClick={() => onDecision(approval, "approve")}
        >
          <Check size={15} />
          {t("批准并继续")}
        </button>
      </div>
    </div>
  );
}

function UserChoicePrompt({ feedback, onSubmit, pending, t }) {
  const [answers, setAnswers] = useState({});
  const [customText, setCustomText] = useState({});
  useEffect(() => {
    setAnswers({});
    setCustomText({});
  }, [feedback.id]);

  const isCustomOption = (option) =>
    option.allow_text === true ||
    /其他|其它|自定义|other|custom/i.test(option.label || "");

  const choose = (question, option) => {
    const current = answers[question.question] || [];
    const custom = isCustomOption(option);
    const nextValues = question.multi_select
      ? current.includes(option.label)
        ? current.filter((item) => item !== option.label)
        : [...current, option.label]
      : [option.label];
    const next = { ...answers, [question.question]: nextValues };
    setAnswers(next);
    if (!custom && !question.multi_select && feedback.questions.length === 1)
      onSubmit(feedback, next);
  };
  const complete = feedback.questions.every(
    (question) => (answers[question.question] || []).length > 0,
  );
  return (
    <div className="choice-prompt" role="dialog" aria-label={t("请选择下一步")}>
      {feedback.questions.map((question, questionIndex) => (
        <section key={`${question.question}-${questionIndex}`}>
          <small>{question.header || t("需要你的选择")}</small>
          <strong>{question.question}</strong>
          <div className="choice-options">
            {(question.options || []).map((option, optionIndex) => {
              const selected = (answers[question.question] || []).includes(option.label);
              const custom = isCustomOption(option);
              return (
                <div className={`choice-option-wrap ${selected ? "selected" : ""}`} key={`${option.label}-${optionIndex}`}>
                  <button
                    className={selected ? "selected" : ""}
                    disabled={pending}
                    onClick={() => choose(question, option)}
                  >
                    <b>{optionIndex + 1}</b>
                    <span>
                      <strong>{option.label}</strong>
                      {option.description && <small>{option.description}</small>}
                    </span>
                    {selected && <Check size={15} />}
                  </button>
                  {custom && selected && (
                    <textarea
                      autoFocus
                      value={customText[question.question] || ""}
                      placeholder={t("直接输入你的具体需求")}
                      onChange={(event) => setCustomText((all) => ({...all, [question.question]: event.target.value}))}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                          event.preventDefault();
                          const value = (customText[question.question] || "").trim();
                          if (value) onSubmit(feedback, {...answers, [question.question]: [value]});
                        }
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}
      {(feedback.questions.length > 1 || feedback.questions.some((q) => q.multi_select || (answers[q.question] || []).some((label) => /其他|其它|自定义|other|custom/i.test(label)))) && (
        <div className="choice-actions">
          <button disabled={!complete || pending || feedback.questions.some((q) => (answers[q.question] || []).some((label) => /其他|其它|自定义|other|custom/i.test(label)) && !(customText[q.question] || "").trim())} onClick={() => onSubmit(feedback, Object.fromEntries(Object.entries(answers).map(([question, values]) => [question, values.some((label) => /其他|其它|自定义|other|custom/i.test(label)) ? [(customText[question] || "").trim()] : values])))}>
            {t("继续")}
          </button>
        </div>
      )}
    </div>
  );
}

function ApprovalEvent({ message, t }) {
  return (
    <div className={`approval-event ${message.metadata?.decision || ""}`}>
      <ShieldCheck size={13} weight="fill" />
      <span>{message.content || t("审批操作已处理")}</span>
      <time>{message.time}</time>
    </div>
  );
}

function ApprovalSegment({ segment, t }) {
  return (
    <div className={`approval-segment ${segment.decision || ""}`}>
      <ShieldCheck size={13} weight="fill" />
      <span>{segment.content || t("审批操作已处理")}</span>
    </div>
  );
}

function FeedbackSegment({ segment, t }) {
  return (
    <div className="approval-segment feedback-segment">
      <Check size={13} weight="bold" />
      <span>{segment.content || t("用户已提交选择")}</span>
    </div>
  );
}

function ComposerAttachment({ file, onRemove, t }) {
  const isImage = file?.type?.startsWith("image/");
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    if (!isImage || !file) {
      setPreviewUrl("");
      return undefined;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file, isImage]);

  return (
    <div
      className={`composer-attachment ${isImage ? "image-attachment" : ""}`}
      title={file.name}
    >
      {isImage && previewUrl ? (
        <img src={previewUrl} alt={file.name} />
      ) : (
        <FileText size={14} />
      )}
      {!isImage && <span>{file.name}</span>}
      <button
        type="button"
        onClick={onRemove}
        title={t("移除附件")}
        aria-label={`${t("移除附件")} ${file.name}`}
      >
        <X size={12} />
      </button>
    </div>
  );
}

function ConversationMessage({
  message,
  onDecision,
  approvalPending,
  onCopy,
  onBranch,
  onEdit,
  canEdit,
  t,
}) {
  if (
    message.kind === "approval_event" ||
    message.kind === "approval" ||
    message.approval_id
  )
    return <ApprovalEvent message={message} t={t} />;
  if (message.role === "user")
    return (
      <div className="message-row user-row">
        <div className="message-stack user-stack">
          <div className="user-bubble">
            <p>{message.content}</p>
            {!!message.metadata?.attachments?.length && (
              <div className="message-attachments">
                {message.metadata.attachments.map((file) => (
                  file.mime_type?.startsWith("image/") && message.session_id && file.id ? (
                    <span className="message-image-attachment" key={file.id} title={file.name}>
                      <img
                        src={`/api/quickops/sessions/${encodeURIComponent(message.session_id)}/attachments/${encodeURIComponent(file.id)}/preview`}
                        alt={file.name}
                      />
                    </span>
                  ) : (
                    <span key={file.id || file.name}>
                      <FileText size={14} />
                      {file.name}
                    </span>
                  )
                ))}
              </div>
            )}
          </div>
          <MessageFooter
            message={message}
            onCopy={onCopy}
            onEdit={onEdit}
            canEdit={canEdit}
            canBranch={false}
            t={t}
          />
        </div>
        <UserCircle size={34} weight="fill" className="user-avatar" />
      </div>
    );
  if (message.kind === "manual")
    return (
      <div className="message-row ai-row">
        <TerminalWindow size={34} weight="fill" className="manual-avatar" />
        <div className="message-stack">
          <div className="assistant-card manual-result">
            <pre>{message.content}</pre>
          </div>
          <MessageFooter
            message={message}
            onCopy={onCopy}
            onBranch={onBranch}
            canBranch
            t={t}
          />
        </div>
      </div>
    );
  const isLive =
    message.status === "running" ||
    message.status === "thinking" ||
    message.status === "compacting";
  const timeline = message.segments?.length
    ? message.segments
    : [
        ...(message.content
          ? [{ type: "text", content: message.content }]
          : []),
        ...(message.tools || []).map((tool) => ({
          type: "tool",
          status: "completed",
          tool,
        })),
      ];
  return (
    <div className="message-row ai-row">
      <Robot size={34} weight="fill" className="ai-avatar" />
      <div className="message-stack">
        <div
          className={`assistant-card result-card ${isLive ? "streaming" : ""}`}
        >
          <div className="runtime-timeline">
            {timeline.map((segment, index) =>
              segment.type === "tool" ? (
                <ToolTrace
                  key={`${segment.tool?.tool_call_id || segment.tool?.id || segment.tool?.tool_name || segment.tool?.name || "tool"}-${index}`}
                  name={segment.tool?.tool_name || segment.tool?.name || "tool"}
                  status={segment.status}
                  t={t}
                  duration={
                    segment.tool?.duration ||
                    (segment.tool?.metrics?.duration
                      ? `${Math.round(segment.tool.metrics.duration * 1000)}ms`
                      : "")
                  }
                >
                  <pre>
                    {typeof segment.tool?.result === "string"
                      ? segment.tool.result
                      : JSON.stringify(
                          segment.tool?.result ??
                            segment.tool?.output ??
                            t("执行中…"),
                          null,
                          2,
                        )}
                  </pre>
                </ToolTrace>
              ) : segment.type === "approval" ? (
                <ApprovalSegment
                  key={`approval-${segment.content || index}-${index}`}
                  segment={segment}
                  t={t}
                />
              ) : segment.type === "feedback" ? (
                <FeedbackSegment
                  key={`feedback-${segment.content || index}-${index}`}
                  segment={segment}
                  t={t}
                />
              ) : (
                <div className="runtime-content" key={`text-${index}`}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {segment.content || ""}
                  </ReactMarkdown>
                </div>
              ),
            )}
          </div>
          {isLive && (
            <div className="thinking-line thinking-line-bottom">
              <span className="thinking-pulse" />
              {t(message.phase || "正在思考")}
            </div>
          )}
        </div>
        <MessageFooter
          message={message}
          onCopy={onCopy}
          onBranch={onBranch}
          canBranch
          t={t}
        />
      </div>
    </div>
  );
}

function Signal({ icon: Icon, label, value, tone = "teal", width }) {
  return (
    <div className="signal-row">
      <Icon size={15} />
      <span>{label}</span>
      <b>{value}</b>
      <span className="signal-track">
        <span className={`signal-fill ${tone}`} style={{ width }} />
      </span>
    </div>
  );
}

const assetStatusText = {
  healthy: "正常",
  degraded: "异常",
  down: "不可用",
  unknown: "待探测",
};

function AssetCenter({
  assets,
  initialService,
  initialTab,
  activeSession,
  onClose,
  onRefresh,
  onMount,
  onCreateInvestigationSession,
  notify,
  t,
}) {
  const [selectedId, setSelectedId] = useState(initialService?.id || assets[0]?.id || "new");
  const [tab, setTab] = useState(initialTab || "status");
  const [events, setEvents] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState(null);
  const documentInput = useRef(null);
  const selected = assets.find((item) => item.id === selectedId) || null;

  useEffect(
    () => () => {
      if (preview?.objectUrl) URL.revokeObjectURL(preview.objectUrl);
    },
    [preview?.objectUrl],
  );
  const [serviceForm, setServiceForm] = useState({
    name: "",
    description: "",
    probe_type: "process",
    probe_target: "",
    interval_seconds: 60,
    enabled: true,
    guard_mode: "diagnose",
    guard_policy: "",
  });
  const [eventForm, setEventForm] = useState({
    title: "",
    content: "",
    severity: "info",
    category: "maintenance",
  });

  useEffect(() => {
    setServiceForm(
      selected
        ? {
            name: selected.name,
            description: selected.description || "",
            probe_type: selected.probe_type,
            probe_target: selected.probe_target,
            interval_seconds: selected.interval_seconds,
            enabled: selected.enabled,
            guard_mode: selected.guard_mode || "diagnose",
            guard_policy: selected.guard_policy || "",
          }
        : {
            name: "",
            description: "",
            probe_type: "process",
            probe_target: "",
            interval_seconds: 60,
            enabled: true,
            guard_mode: "diagnose",
            guard_policy: "",
          },
    );
  }, [selectedId, selected?.updated_at]);

  const refreshDetail = useCallback(async () => {
    if (!selectedId || selectedId === "new") {
      setEvents([]);
      setDocuments([]);
      return;
    }
    const [eventData, documentData] = await Promise.all([
      api(`/api/quickops/assets/services/${selectedId}/events`),
      api(`/api/quickops/assets/services/${selectedId}/documents`),
    ]);
    setEvents(listFrom(eventData, "events"));
    setDocuments(listFrom(documentData, "documents"));
  }, [selectedId]);

  useEffect(() => {
    refreshDetail().catch((error) => notify(error.message));
  }, [refreshDetail, notify]);

  useEffect(() => {
    if (tab !== "events" || !selectedId || selectedId === "new") return undefined;
    const timer = window.setInterval(() => refreshDetail().catch(() => {}), 5000);
    return () => window.clearInterval(timer);
  }, [refreshDetail, selectedId, tab]);

  const saveService = async (event) => {
    event.preventDefault();
    setBusy("service");
    try {
      const path = selected
        ? `/api/quickops/assets/services/${selected.id}`
        : "/api/quickops/assets/services";
      const data = await api(path, {
        method: selected ? "PATCH" : "POST",
        body: JSON.stringify(serviceForm),
      });
      const items = await onRefresh();
      setSelectedId(data.service?.id || items[0]?.id || "new");
      notify(t("服务资产已保存"));
    } catch (error) {
      notify(error.message);
    } finally {
      setBusy("");
    }
  };

  const checkNow = async () => {
    if (!selected) return;
    setBusy("check");
    try {
      await api(`/api/quickops/assets/services/${selected.id}/check`, { method: "POST" });
      await Promise.all([onRefresh(), refreshDetail()]);
      notify(t("探测已完成"));
    } catch (error) {
      notify(error.message);
    } finally {
      setBusy("");
    }
  };

  const removeService = async () => {
    if (!selected || !window.confirm(`${t("删除服务")} “${selected.name}”？`)) return;
    if (activeSession?.asset_service?.id === selected.id) await onMount(null);
    await api(`/api/quickops/assets/services/${selected.id}`, { method: "DELETE" });
    const items = await onRefresh();
    setSelectedId(items[0]?.id || "new");
    notify(t("服务资产已删除"));
  };

  const addEvent = async (event) => {
    event.preventDefault();
    if (!selected) return;
    setBusy("event");
    try {
      await api(`/api/quickops/assets/services/${selected.id}/events`, {
        method: "POST",
        body: JSON.stringify(eventForm),
      });
      setEventForm({ title: "", content: "", severity: "info", category: "maintenance" });
      await refreshDetail();
      notify(t("运维事件已保存"));
    } catch (error) {
      notify(error.message);
    } finally {
      setBusy("");
    }
  };

  const editEvent = async (item) => {
    const title = window.prompt(t("事件标题"), item.title);
    if (title == null) return;
    const content = window.prompt(t("事件详情"), item.content);
    if (content == null) return;
    await api(`/api/quickops/assets/events/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title, content }),
    });
    await refreshDetail();
  };

  const removeEvent = async (item) => {
    if (!window.confirm(`${t("删除运维事件")} “${item.title}”？`)) return;
    await api(`/api/quickops/assets/events/${item.id}`, { method: "DELETE" });
    await refreshDetail();
  };

  const uploadDocument = async (file) => {
    if (!selected || !file) return;
    const form = new FormData();
    form.append("upload", file, file.name);
    setBusy("document");
    try {
      await api(`/api/quickops/assets/services/${selected.id}/documents`, {
        method: "POST",
        body: form,
      });
      await refreshDetail();
      notify(t("文档已上传"));
    } catch (error) {
      notify(error.message);
    } finally {
      setBusy("");
    }
  };

  const renameDocument = async (item) => {
    const name = window.prompt(t("重命名文档"), item.name);
    if (!name) return;
    await api(`/api/quickops/assets/documents/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    await refreshDetail();
  };

  const removeDocument = async (item) => {
    if (!window.confirm(`${t("删除文档")} “${item.name}”？`)) return;
    await api(`/api/quickops/assets/documents/${item.id}`, { method: "DELETE" });
    await refreshDetail();
  };

  const downloadDocument = async (item) => {
    try {
      await downloadAuthenticatedFile(
        `/api/quickops/assets/documents/${item.id}/download`,
        item.name,
      );
    } catch (error) {
      notify(error.message);
    }
  };

  const previewDocument = async (item) => {
    setBusy("preview");
    try {
      const data = await api(`/api/quickops/assets/documents/${item.id}/preview`);
      const details = data.preview;
      let objectUrl = "";
      if (details.kind === "image" || details.kind === "pdf") {
        objectUrl = URL.createObjectURL(
          await fetchAuthenticatedBlob(
            `/api/quickops/assets/documents/${item.id}/download`,
          ),
        );
      }
      setPreview({ ...details, objectUrl });
    } catch (error) {
      notify(error.message);
    } finally {
      setBusy("");
    }
  };

  const closePreview = () => {
    if (preview?.objectUrl) URL.revokeObjectURL(preview.objectUrl);
    setPreview(null);
  };

  return (
    <div className="modal-backdrop asset-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="asset-center" role="dialog" aria-modal="true" aria-label={t("主机资产")}>
        <aside className="asset-sidebar">
          <div className="asset-sidebar-head">
            <div><span>QuickOps</span><h2>{t("主机资产")}</h2></div>
            <button onClick={() => setSelectedId("new")}><Plus size={15} />{t("添加服务")}</button>
          </div>
          <div className="asset-service-list">
            {assets.map((service) => (
              <button key={service.id} className={selectedId === service.id ? "active" : ""} onClick={() => setSelectedId(service.id)}>
                <span className={`asset-status-dot ${service.status}`} />
                <span><strong>{service.name}</strong><small>{service.probe_target}</small></span>
                <em>{t(assetStatusText[service.status] || "待探测")}</em>
              </button>
            ))}
            {!assets.length && <p>{t("暂无服务资产")}</p>}
          </div>
        </aside>
        <div className="asset-main">
          <header className="asset-main-head">
            <div><span>{t("目标主机")}</span><h2>{selected?.name || t("添加服务")}</h2></div>
            <button onClick={onClose} aria-label={t("关闭设置")}><X size={18} /></button>
          </header>
          {selected && (
            <nav className="asset-tabs">
              {["status", "events", "documents"].map((item) => (
                <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>
                  {t(item === "status" ? "状态" : item === "events" ? "事件" : "文档")}
                </button>
              ))}
            </nav>
          )}
          <div className="asset-content">
            {(!selected || tab === "status") && (
              <form className="asset-form" onSubmit={saveService}>
                {selected && (
                  <div className={`asset-health ${selected.status}`}>
                    <span className={`asset-status-dot ${selected.status}`} />
                    <div><strong>{t(assetStatusText[selected.status] || "待探测")}</strong><p>{selected.status_detail || t("待探测")}</p></div>
                    <button type="button" onClick={checkNow} disabled={busy === "check"}><ArrowClockwise size={14} />{t("立即探测")}</button>
                  </div>
                )}
                <div className="asset-form-grid">
                  <label>{t("服务名称")}<input value={serviceForm.name} onChange={(e) => setServiceForm({...serviceForm, name:e.target.value})} required /></label>
                  <label>{t("探测方式")}<select value={serviceForm.probe_type} onChange={(e) => setServiceForm({...serviceForm, probe_type:e.target.value})}><option value="process">{t("进程名称")}</option><option value="system_service">{t("系统服务")}</option><option value="http">{t("HTTP 地址")}</option><option value="tcp">{t("TCP 地址")}</option></select></label>
                  <label className="wide">{t("探测目标")}<input value={serviceForm.probe_target} onChange={(e) => setServiceForm({...serviceForm, probe_target:e.target.value})} placeholder={serviceForm.probe_type === "tcp" ? "127.0.0.1:5432" : serviceForm.probe_type === "http" ? "http://127.0.0.1:8080/health" : "nginx"} required /></label>
                  <label>{t("探测间隔（秒）")}<input type="number" min="15" value={serviceForm.interval_seconds} onChange={(e) => setServiceForm({...serviceForm, interval_seconds:Number(e.target.value)})} /></label>
                  <label className="asset-check"><input type="checkbox" checked={serviceForm.enabled} onChange={(e) => setServiceForm({...serviceForm, enabled:e.target.checked})} />{t("启用自动监控")}</label>
                  <label>{t("异常守护模式")}<select value={serviceForm.guard_mode} onChange={(e) => setServiceForm({...serviceForm, guard_mode:e.target.value})}><option value="diagnose">{t("只排查，不修复")}</option><option value="safe_repair">{t("按策略执行安全修复")}</option></select></label>
                  <label className="wide">{t("守护策略")}<textarea value={serviceForm.guard_policy} onChange={(e) => setServiceForm({...serviceForm, guard_policy:e.target.value})} placeholder={t("说明异常时的排查重点、允许采取的安全措施和必须保留给人工决策的边界")} /><small>{serviceForm.guard_mode === "diagnose" ? t("异常时仅进行只读取证并生成事件。") : t("仅允许服务端判定为非高风险的最小修复；高风险操作仍转正式会话。")}</small></label>
                  <label className="wide">{t("服务说明")}<textarea value={serviceForm.description} onChange={(e) => setServiceForm({...serviceForm, description:e.target.value})} /></label>
                </div>
                <div className="asset-actions">
                  {selected && <button type="button" className="danger" onClick={removeService}><Trash size={14} />{t("删除服务")}</button>}
                  {selected && activeSession && <button type="button" onClick={() => onMount(activeSession.asset_service?.id === selected.id ? null : selected)}>{activeSession.asset_service?.id === selected.id ? t("取消挂载") : t("挂载到会话")}</button>}
                  <button className="primary" disabled={busy === "service"}>{t("保存服务")}</button>
                </div>
              </form>
            )}
            {selected && tab === "events" && (
              <div className="asset-records"><form onSubmit={addEvent} className="asset-inline-form"><input placeholder={t("事件标题")} value={eventForm.title} onChange={(e) => setEventForm({...eventForm,title:e.target.value})} required /><select value={eventForm.severity} onChange={(e) => setEventForm({...eventForm,severity:e.target.value})}><option value="info">info</option><option value="warning">warning</option><option value="critical">critical</option></select><textarea placeholder={t("事件详情")} value={eventForm.content} onChange={(e) => setEventForm({...eventForm,content:e.target.value})} required /><button className="primary" disabled={busy === "event"}>{t("保存事件")}</button></form><div className="asset-record-list">{events.map((item) => <article key={item.id}><span className={`event-severity ${item.severity}`} /> <div><strong>{item.title}</strong><small>{item.source} · {timeOf(item.created_at)}</small><p>{item.content}</p></div><div>{(item.metadata?.follow_up_available || item.category?.startsWith("automatic_")) && <button className="asset-investigate" onClick={() => onCreateInvestigationSession(item)} title={t("创建排查会话")}><GitBranch size={13}/><span>{t("创建排查会话")}</span></button>}<button onClick={() => editEvent(item)}><PencilSimple size={13}/></button><button onClick={() => removeEvent(item)}><Trash size={13}/></button></div></article>)}{!events.length && <p className="asset-empty">{t("该服务尚无运维事件")}</p>}</div></div>
            )}
            {selected && tab === "documents" && (
              <div className="asset-records"><div className="asset-upload"><div><strong>{t("文档")}</strong><p>Markdown、日志、配置、Office 与 PDF；文本会进入该服务的隔离关键词索引。</p></div><button className="primary" onClick={() => documentInput.current?.click()}><Paperclip size={14}/>{t("上传文档")}</button><input ref={documentInput} hidden type="file" onChange={(e) => { uploadDocument(e.target.files?.[0]); e.target.value=""; }} /></div><div className="asset-document-list">{documents.map((item) => <article key={item.id}><FileText size={20}/><div><strong>{item.name}</strong><small>{Math.ceil(item.size/1024)} KB · {timeOf(item.created_at)}</small></div><button onClick={() => previewDocument(item)} title={t("预览文档")} disabled={busy === "preview"}><Eye size={14}/></button><button onClick={() => downloadDocument(item)} title={t("下载文档")}><DownloadSimple size={14}/></button><button onClick={() => renameDocument(item)}><PencilSimple size={13}/></button><button onClick={() => removeDocument(item)}><Trash size={13}/></button></article>)}{!documents.length && <p className="asset-empty">{t("该服务尚无文档")}</p>}</div></div>
            )}
          </div>
        </div>
      </section>
      {preview && (
        <div className="document-preview-backdrop" onMouseDown={(event) => event.target === event.currentTarget && closePreview()}>
          <section className="document-preview" role="dialog" aria-modal="true" aria-label={t("文档预览")}>
            <header><div><span>{t("文档预览")}</span><strong>{preview.name}</strong></div><button onClick={closePreview} aria-label={t("关闭设置")}><X size={17}/></button></header>
            <div className="document-preview-content">
              {preview.kind === "image" ? <img src={preview.objectUrl} alt={preview.name}/> : preview.kind === "pdf" ? <iframe src={preview.objectUrl} title={preview.name}/> : <pre>{preview.content || t("暂无可预览的文本内容")}</pre>}
            </div>
            <footer><button onClick={() => downloadDocument(preview)}><DownloadSimple size={14}/>{t("下载文档")}</button></footer>
          </section>
        </div>
      )}
    </div>
  );
}

const uiMode = (mode) =>
  mode === "delegated_approval"
    ? "assisted"
    : mode === "full_access"
      ? "full"
      : mode;
function normalizeSession(s) {
  return {
    ...s,
    id: s.id || s.session_id,
    title: s.title || s.name || "新会话",
    updated_at: s.updated_at || s.created_at,
    permission_mode: uiMode(s.permission_mode || s.permission || "approval"),
  };
}

function reconcileMessageSegments(segments, content) {
  const next = Array.isArray(segments)
    ? segments.map((segment) => ({ ...segment }))
    : [];
  if (!content) return next;
  const streamedText = next
    .filter((segment) => segment.type === "text")
    .map((segment) => segment.content || "")
    .join("");
  if (!content.startsWith(streamedText) || content.length === streamedText.length)
    return next;
  const suffix = content.slice(streamedText.length);
  if (next.at(-1)?.type === "text")
    next[next.length - 1] = {
      ...next.at(-1),
      content: `${next.at(-1).content || ""}${suffix}`,
    };
  else next.push({ type: "text", content: suffix });
  return next;
}

function normalizeMessage(m, index) {
  const approval = m.approval || m.approval_request;
  if (approval)
    return {
      ...approval,
      id: m.id || approval.id || `approval-${index}`,
      approval_id: approval.approval_id || approval.id,
      kind: "approval",
      time: clockOf(m.created_at),
      status: approval.status,
    };
  const rawContent = m.content || m.message || m.output || "";
  const content = (m.role === "user" && m.metadata?.source === "ai_composer")
    ? String(rawContent).trim()
    : rawContent;
  return {
    ...m,
    id: m.id || m.message_id || `message-${index}`,
    role: m.role || "assistant",
    kind:
      m.kind ||
      m.metadata?.kind ||
      (m.role === "user" ? "user" : "runtime"),
    content,
    segments: reconcileMessageSegments(
      m.segments || m.metadata?.segments || [],
      content,
    ),
    time: m.time || clockOf(m.created_at),
  };
}

function mergeDurableWithLiveMessages(durable, current) {
  const currentById = new Map(current.map((message) => [message.id, message]));
  const mergedDurable = durable.map((message) => {
    const live = currentById.get(message.id);
    if (!live) return message;
    const liveIsActive =
      live.kind === "stream" ||
      ["running", "thinking", "compacting", "finalizing", "paused"].includes(live.status);
    const liveSegments = live.segments?.length || 0;
    const durableSegments = message.segments?.length || 0;
    const liveContent = String(live.content || "");
    const durableContent = String(message.content || "");
    if (
      !liveIsActive &&
      liveSegments <= durableSegments &&
      liveContent.length <= durableContent.length
    )
      return message;
    return {
      ...message,
      ...live,
      id: message.id,
      content:
        liveContent.length >= durableContent.length ? liveContent : durableContent,
      segments:
        liveSegments >= durableSegments ? live.segments : message.segments,
      metadata: { ...(message.metadata || {}), ...(live.metadata || {}) },
    };
  });
  const durableIds = new Set(durable.map((message) => message.id));
  const durableUserCounts = new Map();
  durable.forEach((message) => {
    if (message.role !== "user") return;
    const key = optimisticUserKey(message);
    durableUserCounts.set(key, (durableUserCounts.get(key) || 0) + 1);
  });
  const live = current.filter(
    (message) => {
      if (durableIds.has(message.id)) return false;
      if (String(message.id || "").startsWith("u-")) {
        const key = optimisticUserKey(message);
        const durableCount = durableUserCounts.get(key) || 0;
        if (durableCount > 0) {
          durableUserCounts.set(key, durableCount - 1);
          return false;
        }
        return true;
      }
      return (
        message.kind === "stream" ||
        ["running", "thinking", "compacting", "finalizing", "paused"].includes(message.status)
      );
    },
  );
  return [...mergedDurable, ...live];
}

function optimisticUserKey(message) {
  return JSON.stringify([
    message.role || "user",
    message.metadata?.source || "",
    message.content || "",
  ]);
}

function reconcileOptimisticUserMessage(items, temporaryId, durableId) {
  if (!durableId) return items;
  const durableAlreadyLoaded = items.some(
    (item) => item.id === durableId && item.id !== temporaryId,
  );
  if (durableAlreadyLoaded)
    return items.filter((item) => item.id !== temporaryId);
  return items.map((item) =>
    item.id === temporaryId
      ? { ...item, id: durableId, message_id: durableId }
      : item,
  );
}

async function writeClipboardText(text) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.setAttribute("aria-hidden", "true");
  Object.assign(textarea.style, {
    position: "fixed",
    inset: "0 auto auto -9999px",
    opacity: "0",
    pointerEvents: "none",
  });
  document.body.appendChild(textarea);
  textarea.focus({ preventScroll: true });
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    textarea.remove();
  }
  if (!copied) throw new Error("当前浏览器不允许写入剪贴板");
}

function approvalSegment(event) {
  return {
    type: "approval",
    decision: event.decision || event.metadata?.decision,
    content: event.content || "审批操作已处理",
  };
}

function insertApprovalSegment(segments, event) {
  const next = [...(segments || [])];
  if (
    next.some(
      (segment) =>
        segment.type === "approval" && segment.content === event.content,
    )
  )
    return next;
  next.push(approvalSegment(event));
  return next;
}

function insertToolBeforePendingDecision(segments, toolSegment) {
  return [...(segments || []), toolSegment];
}

function embedLegacyApprovalEvents(messages) {
  const result = [];
  messages.forEach((message) => {
    if (message.kind !== "approval_event") {
      result.push(message);
      return;
    }
    const runId = message.metadata?.run_id;
    const target = [...result]
      .reverse()
      .find(
        (candidate) =>
          candidate.role === "assistant" &&
          (!runId || candidate.metadata?.run_id === runId),
      );
    if (!target) {
      result.push(message);
      return;
    }
    target.segments = insertApprovalSegment(target.segments, message);
  });
  return result;
}

function approvalOperation(requirement, index) {
  const execution = requirement.tool_execution || requirement.tool || {};
  const args = execution.tool_args || execution.arguments || {};
  const toolName = execution.tool_name || execution.name || "受控工具";
  const argv = Array.isArray(args.args) ? args.args.map(String) : null;
  const query = args.query || args.sql;
  const path = args.path || args.file_path || args.target_path;
  let title = `调用 ${toolName}`;
  let detail = JSON.stringify(args, null, 2);
  if (argv?.length) {
    title = `执行命令：${argv.join(" ")}`;
    detail = argv.join(" ");
  } else if (query) {
    title = `执行数据库查询`;
    detail = String(query);
  } else if (path) {
    title = `操作路径：${path}`;
  }
  return {
    id: requirement.id || `${toolName}-${index}`,
    toolName,
    title,
    detail: detail === "{}" ? "" : detail,
  };
}

function normalizeApproval(data, envelope, runId, messageId) {
  const requirements = data.requirements?.length
    ? data.requirements
    : [data.requirement || {}];
  const latestRequirement = requirements.at(-1) || {};
  const operation = approvalOperation(latestRequirement, requirements.length - 1);
  const risk = ["low", "medium", "high", "critical"].includes(
    latestRequirement.risk,
  )
    ? latestRequirement.risk
    : "medium";
  const riskLabels = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
    critical: "严重风险",
  };
  return {
    id: `${runId}-${envelope.sequence || "paused"}`,
    run_id: runId,
    requirement_id: latestRequirement.id || null,
    stream_message_id: data.message_id || messageId,
    sequence: envelope.sequence,
    risk,
    risk_label: riskLabels[risk],
    operations: [operation],
  };
}

function normalizeFeedback(data, envelope, runId, messageId) {
  const requirements = data.requirements?.length
    ? data.requirements
    : [data.requirement || {}];
  const latest = [...requirements]
    .reverse()
    .find(
      (item) =>
        item.user_feedback_schema?.length && item.needs_user_feedback !== false,
    );
  if (!latest) return null;
  const questions = latest.user_feedback_schema.map((question) => {
    const options = [...(question.options || [])];
    const customIndex = options.findIndex(
      (option) =>
        option.allow_text === true ||
        /其他|其它|自定义|other|custom/i.test(option.label || ""),
    );
    const custom = customIndex >= 0 ? options.splice(customIndex, 1)[0] : {};
    return {
      ...question,
      options: [
        ...options.slice(0, 3),
        {
          ...custom,
          label: "其他",
          description: custom.description || "手动输入其他需求",
          allow_text: true,
        },
      ],
    };
  });
  return {
    id: `${runId}-${latest.id || envelope.sequence || "feedback"}`,
    run_id: runId,
    requirement_id: latest.id || null,
    stream_message_id: data.message_id || messageId,
    sequence: envelope.sequence,
    questions,
  };
}

export function App() {
  const [auth, setAuth] = useState({
    checking: true,
    configured: false,
    authenticated: false,
    username: "",
  });
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [loginError, setLoginError] = useState("");
  const [loginPending, setLoginPending] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [messagesBySession, setMessagesBySession] = useState({});
  const [inputMode, setInputMode] = useState("ai");
  const [permission, setPermission] = useState(permissionCatalog[1]);
  const [permissionOpen, setPermissionOpen] = useState(false);
  const [enabledModes, setEnabledModes] = useState([
    "readonly",
    "approval",
    "assisted",
    "full",
  ]);
  const [models, setModels] = useState([fallbackModel]);
  const [selectedModel, setSelectedModel] = useState(fallbackModel);
  const [modelOpen, setModelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsPage, setSettingsPage] = useState("general");
  const [generalSettings, setGeneralSettings] = useState({
    language: "zh-CN",
    theme: "dark",
    default_permission: "approval",
    host_refresh_interval: 5,
  });
  const locale = generalSettings.language === "en-US" ? "en-US" : "zh-CN";
  const t = useCallback(
    (key, variables) => translate(locale, key, variables),
    [locale],
  );
  const [editingModel, setEditingModel] = useState(null);
  const [modelForm, setModelForm] = useState({
    name: "",
    provider: "SiliconFlow",
    model_id: "",
    base_url: "",
    api_key: "",
    thinking_mode: "auto",
    max_context_k: 128,
    supports_vision: false,
    is_default: false,
  });
  const [input, setInput] = useState("");
  const [pendingAttachmentBySession, setPendingAttachmentBySession] = useState({});
  const [toast, setToast] = useState("");
  const [runtime, setRuntime] = useState({
    connected: false,
    configured: false,
    hosts: [],
    hostId: "",
  });
  const [runningBySession, setRunningBySession] = useState({});
  const [activeRunBySession, setActiveRunBySession] = useState({});
  const [completedNoticeBySession, setCompletedNoticeBySession] = useState({});
  const [terminalBySession, setTerminalBySession] = useState({});
  const [editingMessage, setEditingMessage] = useState(null);
  const [toolbox, setToolbox] = useState([]);
  const [toolboxLoading, setToolboxLoading] = useState(false);
  const [toolboxSaving, setToolboxSaving] = useState("");
  const [assetServices, setAssetServices] = useState([]);
  const [assetCenter, setAssetCenter] = useState(null);
  const [expandedAssetRailId, setExpandedAssetRailId] = useState(null);
  const [approvalBySession, setApprovalBySession] = useState({});
  const [approvalPending, setApprovalPending] = useState(null);
  const [feedbackBySession, setFeedbackBySession] = useState({});
  const [feedbackPending, setFeedbackPending] = useState(null);
  const fileRef = useRef(null);
  const textareaRef = useRef(null);
  const conversationRef = useRef(null);
  const shouldFollowOutputRef = useRef(true);
  const commandHistoryRef = useRef({});
  const streamsRef = useRef(new Map());
  const activeSessionIdRef = useRef(null);
  const modelControlRef = useRef(null);
  const permissionControlRef = useRef(null);
  const isComposingRef = useRef(false);
  const feedbackSubmittingRef = useRef(new Set());

  useEffect(() => {
    const theme = generalSettings.theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }, [generalSettings.theme]);
  const messages = activeSession?.id
    ? messagesBySession[activeSession.id] || []
    : [];
  const requestPending = !!(
    activeSession?.id && runningBySession[activeSession.id]
  );
  const activeRunId = activeSession?.id
    ? activeRunBySession[activeSession.id]
    : null;
  const activeApproval = activeSession?.id
    ? approvalBySession[activeSession.id]
    : null;
  const activeFeedback = activeSession?.id
    ? feedbackBySession[activeSession.id]
    : null;
  const attachmentSessionKey = activeSession?.id || "__new_session__";
  const attachment = pendingAttachmentBySession[attachmentSessionKey] || null;
  const setSessionAttachment = useCallback(
    (file, sessionKey = attachmentSessionKey) => {
      setPendingAttachmentBySession((all) => {
        const next = { ...all };
        if (file) next[sessionKey] = file;
        else delete next[sessionKey];
        return next;
      });
    },
    [attachmentSessionKey],
  );
  const lastAgentUserMessageId = useMemo(
    () =>
      [...messages]
        .reverse()
        .find(
          (message) =>
            message.role === "user" &&
            (message.metadata?.source === "ai_composer" ||
              message.source === "ai_composer" ||
              (message.message_type === "user" && !message.metadata?.source)),
        )?.id,
    [messages],
  );
  const toolboxGroups = useMemo(
    () =>
      Object.entries(
        toolbox.reduce(
          (groups, tool) => {
            const labels = {
              development: t("开发与编码"),
              infrastructure: t("基础设施"),
              filesystem: t("文件与工作区"),
              web: t("网页与检索"),
              data: t("数据分析"),
              database: t("数据库"),
            };
            const category = labels[tool.category] || tool.category || t("其他工具");
            return { ...groups, [category]: [...(groups[category] || []), tool] };
          },
          {},
        ),
      ),
    [t, toolbox],
  );

  const refreshAssets = useCallback(async () => {
    const suffix = runtime.hostId ? `?host_id=${encodeURIComponent(runtime.hostId)}` : "";
    const data = await api(`/api/quickops/assets/services${suffix}`);
    const items = listFrom(data, "services");
    setAssetServices(items);
    setAssetCenter((current) =>
      current?.service
        ? { ...current, service: items.find((item) => item.id === current.service.id) || null }
        : current,
    );
    return items;
  }, [runtime.hostId]);

  useEffect(() => {
    let cancelled = false;
    api("/api/quickops/auth/status")
      .then((status) => {
        if (!cancelled)
          setAuth({
            checking: false,
            configured: !!status.configured,
            authenticated: !!status.authenticated,
            username: status.username || "",
          });
      })
      .catch((error) => {
        if (!cancelled) {
          setAuth((current) => ({ ...current, checking: false }));
          setLoginError(error.message);
        }
      });
    const handleUnauthorized = () => {
      setLoginError("登录状态已失效，请重新登录。");
      setAuth((current) => ({ ...current, checking: false, authenticated: false }));
    };
    window.addEventListener("quickops:unauthorized", handleUnauthorized);
    return () => {
      cancelled = true;
      window.removeEventListener("quickops:unauthorized", handleUnauthorized);
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    activeSessionIdRef.current = activeSession?.id || null;
  }, [activeSession?.id]);

  useLayoutEffect(() => {
    const conversation = conversationRef.current;
    if (!conversation || !shouldFollowOutputRef.current) return;
    conversation.scrollTop = conversation.scrollHeight;
  }, [activeSession?.id, messages]);

  useEffect(() => {
    shouldFollowOutputRef.current = true;
    const frame = window.requestAnimationFrame(() => {
      const conversation = conversationRef.current;
      if (conversation) conversation.scrollTop = conversation.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeSession?.id]);

  const updateSessionMessages = useCallback((sessionId, updater) => {
    if (!sessionId) return;
    setMessagesBySession((all) => {
      const current = all[sessionId] || [];
      return {
        ...all,
        [sessionId]: typeof updater === "function" ? updater(current) : updater,
      };
    });
  }, []);

  const notify = useCallback((text) => {
    setToast(text);
    window.setTimeout(() => setToast(""), 2000);
  }, []);
  const refreshSessions = useCallback(async () => {
    const data = await api("/api/quickops/sessions");
    const items = listFrom(data, "sessions").map(normalizeSession);
    setSessions(items);
    return items;
  }, []);
  const refreshModels = useCallback(async () => {
    const data = await api("/api/quickops/models");
    const items = listFrom(data, "models");
    setModels(items);
    setSelectedModel(
      (current) =>
        items.find((m) => m.id === current?.id) ||
        items.find((m) => m.is_default) ||
        items[0] ||
        fallbackModel,
    );
    return items;
  }, []);
  const refreshBootstrap = useCallback(async () => {
    const data = await api("/api/quickops/bootstrap");
    const hosts = data.hosts || (data.host ? [data.host] : []);
    setRuntime({
      connected: true,
      configured: data.model_configured ?? data.configured ?? false,
      hosts,
      hostId: data.active_host_id || hosts[0]?.id || hosts[0]?.host_id || "",
    });
    const modes = data.modes_enabled || data.permission_modes_enabled;
    if (Array.isArray(modes)) setEnabledModes(modes.map(uiMode));
    return data;
  }, []);
  const refreshSettings = useCallback(async () => {
    const data = await api("/api/quickops/settings");
    const raw = data?.settings || data || {};
    const values = Array.isArray(raw)
      ? Object.fromEntries(raw.map((item) => [item.key, item.value]))
      : raw;
    setGeneralSettings((current) => ({ ...current, ...values }));
    return values;
  }, []);
  const refreshToolbox = useCallback(async () => {
    setToolboxLoading(true);
    try {
      const data = await api("/api/quickops/toolbox");
      const catalog = listFrom(data, "tools").length
        ? listFrom(data, "tools")
        : listFrom(data, "catalog");
      setToolbox(
        catalog.map((tool) => ({
          ...tool,
          id: tool.id || tool.tool_id || tool.name,
          name: tool.label || tool.display_name || tool.name || tool.id,
          category: tool.category || tool.group || "其他工具",
          available: tool.available !== false,
          enabled: !!tool.enabled,
          unavailable_reason:
            tool.unavailable_reason ||
            tool.reason ||
            "当前服务环境缺少所需依赖",
        })),
      );
    } catch (error) {
      notify(error.message);
    } finally {
      setToolboxLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    if (!auth.authenticated) return undefined;
    Promise.allSettled([
      refreshBootstrap(),
      refreshSessions(),
      refreshModels(),
      refreshSettings(),
    ]);
    const timer = window.setInterval(
      () =>
        Promise.allSettled([refreshBootstrap(), refreshSessions()]).then(
          (results) => {
            if (results[0].status === "rejected")
              setRuntime((r) => ({ ...r, connected: false }));
          },
        ),
      5000,
    );
    return () => {
      window.clearInterval(timer);
      streamsRef.current.forEach((source) => source.close());
      streamsRef.current.clear();
    };
  }, [auth.authenticated, refreshBootstrap, refreshModels, refreshSessions, refreshSettings]);
  useEffect(() => {
    if (!auth.authenticated) return undefined;
    refreshAssets().catch(() => {});
    const timer = window.setInterval(() => refreshAssets().catch(() => {}), 15000);
    return () => window.clearInterval(timer);
  }, [auth.authenticated, refreshAssets]);
  useEffect(() => {
    if (auth.authenticated && settingsOpen) refreshSettings().catch(() => {});
  }, [auth.authenticated, refreshSettings, settingsOpen]);
  useEffect(() => {
    if (auth.authenticated && settingsOpen && settingsPage === "toolbox") refreshToolbox();
  }, [auth.authenticated, refreshToolbox, settingsOpen, settingsPage]);
  useEffect(() => {
    if (!modelOpen && !permissionOpen && !settingsOpen) return undefined;
    const closeOnOutsidePointer = (event) => {
      if (modelOpen && !modelControlRef.current?.contains(event.target))
        setModelOpen(false);
      if (
        permissionOpen &&
        !permissionControlRef.current?.contains(event.target)
      )
        setPermissionOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key !== "Escape") return;
      if (modelOpen || permissionOpen) {
        setModelOpen(false);
        setPermissionOpen(false);
      } else if (settingsOpen) setSettingsOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [modelOpen, permissionOpen, settingsOpen]);

  const loadSession = async (session) => {
    activeSessionIdRef.current = session.id;
    setActiveSession(session);
    setCompletedNoticeBySession((notices) => ({
      ...notices,
      [session.id]: false,
    }));
    setPermission(
      permissionCatalog.find((p) => p.id === session.permission_mode) ||
        permissionCatalog[1],
    );
    if (session.terminal_status || session.terminal)
      setTerminalBySession((all) => ({
        ...all,
        [session.id]: {
          ...(session.terminal || {}),
          status: session.terminal_status || session.terminal?.status,
        },
      }));
    setSelectedModel(
      models.find((model) => model.id === session.model_config_id) ||
        models.find((model) => model.is_default) ||
        fallbackModel,
    );
    // Cards are derived state of the currently active run. Clear stale in-memory state first;
    // the active-runs replay below will restore only the latest unresolved requirement.
    setApprovalBySession((all) => ({ ...all, [session.id]: null }));
    setFeedbackBySession((all) => ({ ...all, [session.id]: null }));
    try {
      const data = await api(
        `/api/quickops/sessions/${encodeURIComponent(session.id)}/messages`,
      );
      const durableMessages = embedLegacyApprovalEvents(
        listFrom(data, "messages").map(normalizeMessage),
      );
      updateSessionMessages(session.id, (current) =>
        mergeDurableWithLiveMessages(durableMessages, current),
      );
      const activeData = await api(
        `/api/quickops/sessions/${encodeURIComponent(session.id)}/active-runs`,
      );
      const activeRun = listFrom(activeData, "runs")[0];
      if (activeRun && !streamsRef.current.has(activeRun.id)) {
        const liveMessageId =
          activeRun.stream_message_id || `restored-stream-${activeRun.id}-${Date.now()}`;
        setRunningBySession((running) => ({ ...running, [session.id]: true }));
        setActiveRunBySession((runs) => ({ ...runs, [session.id]: activeRun.id }));
        updateSessionMessages(session.id, (items) => {
          const existing = items.find((item) => item.id === liveMessageId);
          if (existing)
            return items.map((item) =>
              item.id === liveMessageId
                ? { ...item, status: "thinking", phase: "正在恢复运行状态" }
                : item,
            );
          return [
            ...items.filter(
              (item) =>
                !(
                  item.run_id === activeRun.id &&
                  (item.kind === "stream" || ["running", "thinking", "finalizing"].includes(item.status))
                ),
            ),
            {
            id: liveMessageId,
            run_id: activeRun.id,
            role: "assistant",
            kind: "stream",
            time: clockOf(activeRun.created_at),
            status: "thinking",
            phase: "正在恢复运行状态",
            content: "",
            tools: [],
            segments: [],
            },
          ];
        });
        connectRunStream(
          session.id,
          activeRun.id,
          liveMessageId,
          activeRun.resume_after_sequence || undefined,
        );
      }
    } catch (error) {
      notify(error.message);
    }
    api(`/api/quickops/sessions/${encodeURIComponent(session.id)}/terminal`)
      .then((terminal) =>
        setTerminalBySession((all) => ({
          ...all,
          [session.id]: {
            ...terminal,
            status:
              terminal?.terminal_alive || terminal?.status === "active"
                ? "connected"
                : "closed",
          },
        })),
      )
      .catch(() => {});
  };

  const mountAsset = async (service) => {
    if (!activeSession?.id) {
      notify(t("请先创建会话"));
      return;
    }
    try {
      const data = await api(
        `/api/quickops/sessions/${encodeURIComponent(activeSession.id)}/asset`,
        {
          method: "PUT",
          body: JSON.stringify({ service_id: service?.id || null }),
        },
      );
      const updated = normalizeSession(data.session);
      setActiveSession(updated);
      setSessions((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
      notify(t(service ? "已挂载服务资产" : "已取消挂载"));
    } catch (error) {
      notify(error.message);
    }
  };

  const createInvestigationSession = async (event) => {
    try {
      const data = await api(
        `/api/quickops/assets/events/${encodeURIComponent(event.id)}/session`,
        { method: "POST" },
      );
      const session = normalizeSession(data.session || data);
      setSessions((items) => [
        session,
        ...items.filter((item) => item.id !== session.id),
      ]);
      setAssetCenter(null);
      await loadSession(session);
      notify(t("已从运维事件创建排查会话"));
    } catch (error) {
      notify(error.message);
    }
  };

  const newSession = async () => {
    if (!runtime.hostId) {
      notify(t("目标主机信息尚未就绪"));
      return;
    }
    try {
      const defaultMode = generalSettings.default_permission || "approval";
      const data = await api("/api/quickops/sessions", {
        method: "POST",
        body: JSON.stringify({
          title: "新会话",
          permission_mode: defaultMode,
          host_id: runtime.hostId || undefined,
        }),
      });
      const session = normalizeSession(data.session || data);
      activeSessionIdRef.current = session.id;
      setSessions((items) => [
        session,
        ...items.filter((item) => item.id !== session.id),
      ]);
      setActiveSession(session);
      if (session.terminal)
        setTerminalBySession((all) => ({
          ...all,
          [session.id]: {
            ...session.terminal,
            status: "connected",
          },
        }));
      setPermission(
        permissionCatalog.find((item) => item.apiId === defaultMode) ||
          permissionCatalog[1],
      );
      updateSessionMessages(session.id, []);
      notify(t("已创建新会话"));
    } catch (error) {
      notify(error.message);
    }
  };

  const ensureSession = async () => {
    if (activeSession) return activeSession;
    if (!runtime.hostId) throw new Error("目标主机信息尚未就绪");
    const data = await api("/api/quickops/sessions", {
      method: "POST",
      body: JSON.stringify({
        title: "新会话",
        permission_mode: generalSettings.default_permission || "approval",
        host_id: runtime.hostId || undefined,
      }),
    });
    const session = normalizeSession(data.session || data);
    activeSessionIdRef.current = session.id;
    setActiveSession(session);
    setSessions((items) => [session, ...items]);
    if (session.terminal)
      setTerminalBySession((all) => ({
        ...all,
        [session.id]: {
          ...session.terminal,
          status: "connected",
        },
      }));
    return session;
  };

  const resizeTextarea = (element) => {
    element.style.height = "24px";
    element.style.height = `${Math.min(element.scrollHeight, 120)}px`;
    element.style.overflowY = element.scrollHeight > 120 ? "auto" : "hidden";
  };
  useLayoutEffect(() => {
    if (textareaRef.current) resizeTextarea(textareaRef.current);
  }, [input, inputMode, attachment]);
  const resetCommandHistoryCursor = (sessionId = activeSession?.id) => {
    if (!sessionId) return;
    commandHistoryRef.current[sessionId] = { index: null, draft: "" };
  };
  const navigateCommandHistory = (direction) => {
    const sessionId = activeSession?.id;
    if (!sessionId) return;
    const history = messages
      .filter(
        (message) =>
          message.role === "user" &&
          (message.metadata?.source === "manual_composer" ||
            message.message_type === "manual_command"),
      )
      .map((message) => message.content)
      .filter(Boolean);
    if (!history.length) return;
    const state = commandHistoryRef.current[sessionId] || {
      index: null,
      draft: "",
    };
    let nextIndex;
    if (direction < 0) {
      if (state.index === null) {
        state.draft = input;
        nextIndex = history.length - 1;
      } else nextIndex = Math.max(0, state.index - 1);
    } else {
      if (state.index === null) return;
      nextIndex = state.index + 1;
      if (nextIndex >= history.length) {
        state.index = null;
        commandHistoryRef.current[sessionId] = state;
        setInput(state.draft);
        window.requestAnimationFrame(() => {
          if (textareaRef.current) resizeTextarea(textareaRef.current);
        });
        return;
      }
    }
    state.index = nextIndex;
    commandHistoryRef.current[sessionId] = state;
    setInput(history[nextIndex]);
    window.requestAnimationFrame(() => {
      if (textareaRef.current) {
        resizeTextarea(textareaRef.current);
        const end = history[nextIndex].length;
        textareaRef.current.setSelectionRange(end, end);
      }
    });
  };
  const appendApproval = (sessionId, data) => {
    const a = data.approval || data.approval_request || data;
    const requirement = {
      id: a.approval_id || a.id,
      risk: a.risk || a.risk_level,
      tool_execution: {
        tool_name: a.tool_name || "受控操作",
        tool_args: a.arguments || { command: a.command },
      },
    };
    setApprovalBySession((all) => ({
      ...all,
      [sessionId]: normalizeApproval(
        { requirements: [requirement] },
        { sequence: a.sequence },
        a.run_id,
        a.stream_message_id,
      ),
    }));
  };

  const finishRun = useCallback(
    (sessionId, runId, outcome = "finished") => {
      setRunningBySession((running) => ({ ...running, [sessionId]: false }));
      setActiveRunBySession((runs) =>
        runs[sessionId] === runId ? { ...runs, [sessionId]: null } : runs,
      );
      setApprovalBySession((all) =>
        all[sessionId]?.run_id === runId
          ? { ...all, [sessionId]: null }
          : all,
      );
      setFeedbackBySession((all) =>
        all[sessionId]?.run_id === runId
          ? { ...all, [sessionId]: null }
          : all,
      );
      const source = streamsRef.current.get(runId);
      if (source) source.close();
      streamsRef.current.delete(runId);
      if (outcome === "completed" && activeSessionIdRef.current !== sessionId)
        setCompletedNoticeBySession((notices) => ({
          ...notices,
          [sessionId]: true,
        }));
      Promise.allSettled([refreshSessions(), refreshBootstrap()]);
    },
    [refreshBootstrap, refreshSessions],
  );

  const connectRunStream = useCallback(
    (sessionId, runId, messageId, afterSequence) => {
      const suffix =
        afterSequence != null
          ? `?after=${encodeURIComponent(afterSequence)}`
          : "";
      const source = authenticatedEventStream(
        `/api/quickops/runs/${encodeURIComponent(runId)}/events${suffix}`,
      );
      streamsRef.current.set(runId, source);
      const consume = (event) => {
        let envelope = {};
        try {
          envelope = JSON.parse(event.data || "{}");
        } catch {
          envelope = { content: event.data || "" };
        }
        const data = { ...envelope, ...(envelope.payload || {}) };
        const type = String(
          envelope.event || data.type || event.type || "message",
        )
          .replace(/([a-z])([A-Z])/g, "$1_$2")
          .toLowerCase()
          .replaceAll(".", "_");
        const isRunComplete =
          type.endsWith("run_completed") ||
          type.endsWith("run_finished") ||
          type === "runcompleted" ||
          type === "completed";
        const isRunFailed =
          type.endsWith("run_failed") ||
          type.endsWith("run_error") ||
          type === "runfailed" ||
          type === "failed";
        const isRunCancelled =
          type.endsWith("run_cancelled") ||
          type === "runcancelled" ||
          type === "cancelled";
        const isReasoningComplete =
          type === "reasoning_completed" || type === "thinking_completed";
        const isModelStarted = type === "model_started";
        const isModelCompleted = type === "model_completed";
        const isCompactionStarted = type === "context_compaction_started";
        const isCompactionCompleted = type === "context_compaction_completed";
        const isCompactionFailed = type === "context_compaction_failed";
        if (type.includes("paused")) {
          const feedback = normalizeFeedback(data, envelope, runId, messageId);
          if (feedback) {
            setFeedbackBySession((all) => ({ ...all, [sessionId]: feedback }));
            setApprovalBySession((all) => ({ ...all, [sessionId]: null }));
          } else {
            setApprovalBySession((all) => ({
              ...all,
              [sessionId]: normalizeApproval(data, envelope, runId, messageId),
            }));
            setFeedbackBySession((all) => ({ ...all, [sessionId]: null }));
          }
          updateSessionMessages(sessionId, (items) =>
            (() => {
              const target = items.find((item) => item.id === messageId);
              if (!target) return items;
              const next = data.message_id
                ? {
                    ...target,
                    id: data.message_id,
                    kind: "runtime",
                    status: "paused",
                    phase: feedback ? "等待你的选择" : "等待执行审批",
                    content: data.content ?? target.content,
                    tools: data.tools || target.tools,
                    segments: reconcileMessageSegments(
                      data.segments || target.segments,
                      data.content ?? target.content,
                    ),
                    time: data.created_at ? clockOf(data.created_at) : target.time,
                  }
                : {
                    ...target,
                    status: "paused",
                    phase: feedback ? "等待你的选择" : "等待执行审批",
                  };
              const durableIndex = data.message_id
                ? items.findIndex(
                    (item) => item.id === data.message_id && item.id !== messageId,
                  )
                : -1;
              if (durableIndex < 0)
                return items.map((item) => (item.id === messageId ? next : item));
              return items
                .filter((item) => item.id !== messageId)
                .map((item) =>
                  item.id === data.message_id
                    ? { ...item, ...next, id: data.message_id }
                    : item,
                );
            })(),
          );
          source.close();
          streamsRef.current.delete(runId);
          return;
        }
        updateSessionMessages(sessionId, (items) =>
          items.map((item) => {
            if (item.id !== messageId) return item;
            if (isRunComplete)
              return (() => {
                const content = data.content ?? item.content;
                return {
                ...item,
                id: data.message_id || item.id,
                kind: "runtime",
                status: "completed",
                phase: "",
                content,
                time: data.created_at ? clockOf(data.created_at) : item.time,
                tools: data.tools || item.tools,
                segments: reconcileMessageSegments(
                  data.segments || item.segments,
                  content,
                ),
              };
              })();
            if (isRunFailed)
              return {
                ...item,
                id: data.message_id || item.id,
                kind: "runtime",
                status: "failed",
                phase: "",
                content: data.content || data.error || data.message || item.content || "运行失败",
                time: data.created_at ? clockOf(data.created_at) : item.time,
                segments: data.segments || item.segments,
              };
            if (isRunCancelled)
              return {
                ...item,
                kind: "runtime",
                status: "cancelled",
                phase: "",
                content:
                  item.content || data.message || "回复已由操作员中止。",
              };
            if (isCompactionStarted)
              return {
                ...item,
                status: "compacting",
                phase: data.label || "正在压缩会话上下文",
              };
            if (isCompactionCompleted)
              return {
                ...item,
                status: "running",
                phase: data.label || "上下文压缩完成",
              };
            if (isCompactionFailed)
              return {
                ...item,
                status: "running",
                phase:
                  data.label || "上下文压缩失败，正在保留原上下文继续",
              };
            if (type === "approval.resolved")
              return {
                ...item,
                segments: insertApprovalSegment(item.segments, data),
              };
            if (
              type.includes("tool") &&
              (type.includes("start") || type.includes("call"))
            ) {
              const toolData = data.tool || data;
              const startedTool = {
                id: toolData.tool_call_id || toolData.id || `${Date.now()}`,
                name: toolData.tool_name || toolData.name || "tool",
                ...toolData,
              };
              return {
                ...item,
                status: "running",
                phase: `正在调用 ${toolData.tool_name || toolData.name || "工具"}`,
                tools: [
                  ...(item.tools || []),
                  {
                    ...startedTool,
                    result: "执行中…",
                  },
                ],
                segments: insertToolBeforePendingDecision(item.segments, {
                  type: "tool",
                  status: "running",
                  tool: startedTool,
                }),
              };
            }
            if (
              type.includes("tool") &&
              (type.includes("complete") ||
                type.includes("result") ||
                type.includes("end"))
            ) {
              const toolData = data.tool || data;
              const toolId = toolData.tool_call_id || toolData.id;
              const currentTools = item.tools || [];
              const hasStartedTool =
                currentTools.some((tool) => tool.id === toolId) ||
                (!toolId && currentTools.length > 0);
              const completedTool = {
                id: toolId || `${Date.now()}`,
                name: toolData.tool_name || toolData.name || "tool",
                result:
                  toolData.result ??
                  toolData.output ??
                  data.content ??
                  "已完成",
                duration: toolData.duration || "",
              };
              return {
                ...item,
                status: "running",
                phase: "正在分析工具结果",
                tools: hasStartedTool
                  ? currentTools.map((tool, index, all) =>
                      tool.id === toolId ||
                      (!toolId && index === all.length - 1)
                        ? { ...tool, ...completedTool, id: tool.id }
                        : tool,
                    )
                  : [...currentTools, completedTool],
                segments: (() => {
                  const segments = [...(item.segments || [])];
                  const segmentIndex = segments.findLastIndex(
                    (segment) =>
                      segment.type === "tool" &&
                      (toolId
                        ? (segment.tool?.tool_call_id || segment.tool?.id) ===
                          toolId
                        : segment.status === "running"),
                  );
                  const completedSegment = {
                    type: "tool",
                    status: "completed",
                    tool: completedTool,
                  };
                  if (segmentIndex < 0) {
                    segments.push(completedSegment);
                  }
                  else
                    segments[segmentIndex] = {
                      ...segments[segmentIndex],
                      ...completedSegment,
                      tool: {
                        ...(segments[segmentIndex].tool || {}),
                        ...completedTool,
                      },
                    };
                  return segments;
                })(),
              };
            }
            if (isReasoningComplete)
              return { ...item, status: "running", phase: "正在生成回复" };
            if (isModelCompleted)
              return { ...item, status: "finalizing", phase: "" };
            if (type === "feedback_resolved")
              return {
                ...item,
                status: "thinking",
                phase: "正在思考",
                segments: [
                  ...(item.segments || []),
                  ...((item.segments || []).some(
                    (segment) =>
                      segment.type === "feedback" &&
                      segment.content === data.content,
                  )
                    ? []
                    : [{ type: "feedback", content: data.content || "用户已提交选择" }]),
                ],
              };
            if (type.includes("reasoning") || type.includes("thinking"))
              return {
                ...item,
                status: "thinking",
                phase: data.label || data.message || "正在思考",
              };
            if (isModelStarted)
              return { ...item, status: "running", phase: "正在生成回复" };
            if (
              type.includes("content") ||
              type.includes("delta") ||
              type === "message"
            )
              return (() => {
                const delta = data.delta ?? data.content ?? data.text ?? "";
                const segments = [...(item.segments || [])];
                if (segments.at(-1)?.type === "text")
                  segments[segments.length - 1] = {
                    ...segments.at(-1),
                    content: `${segments.at(-1).content || ""}${delta}`,
                  };
                else segments.push({ type: "text", content: delta });
                return {
                  ...item,
                  content: `${item.content || ""}${delta}`,
                  segments,
                  phase: "正在生成回复",
                };
              })();
            if (type.includes("started"))
              return {
                ...item,
                status: "thinking",
                phase: data.label || data.message || "正在思考",
              };
            return item;
          }),
        );
        if (isRunComplete || isRunFailed || isRunCancelled)
          finishRun(
            sessionId,
            runId,
            isRunComplete ? "completed" : isRunCancelled ? "cancelled" : "failed",
          );
      };
      [
        "message",
        "run.started",
        "thinking",
        "reasoning",
        "reasoning.started",
        "reasoning.delta",
        "reasoning.completed",
        "model.started",
        "model.completed",
        "context.compaction.started",
        "context.compaction.completed",
        "context.compaction.failed",
        "content.delta",
        "content",
        "tool.started",
        "tool.completed",
        "approval.resolved",
        "feedback.resolved",
        "run.paused",
        "run.completed",
        "run.failed",
        "run.cancelled",
      ].forEach((name) => source.addEventListener(name, consume));
      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED)
          finishRun(sessionId, runId);
      };
    },
    [finishRun, updateSessionMessages],
  );

  const submit = async () => {
    const value = input.trim();
    const pendingAttachment = inputMode === "ai" ? attachment : null;
    let pendingAttachmentSessionKey = attachmentSessionKey;
    if ((!value && !pendingAttachment) || requestPending) return;
    const messageValue = value || "请查看并分析我上传的附件。";
    const now = clockOf();
    shouldFollowOutputRef.current = true;
    if (inputMode === "manual") resetCommandHistoryCursor();
    setInput("");
    if (textareaRef.current) resizeTextarea(textareaRef.current);
    let targetSessionId = activeSession?.id;
    try {
      let session;
      if (editingMessage && inputMode === "ai") {
        const revised = await api(
          `/api/quickops/sessions/${encodeURIComponent(editingMessage.sessionId)}/revise`,
          {
            method: "POST",
            body: JSON.stringify({ message_id: editingMessage.messageId }),
          },
        );
        session = normalizeSession(
          revised.session || revised.new_session || revised,
        );
        setSessions((items) => [
          session,
          ...items.filter((item) => item.id !== session.id),
        ]);
        await loadSession(session);
        setEditingMessage(null);
      } else session = await ensureSession();
      targetSessionId = session.id;
      if (
        pendingAttachment &&
        pendingAttachmentSessionKey !== session.id
      ) {
        setPendingAttachmentBySession((all) => {
          const next = { ...all, [session.id]: pendingAttachment };
          delete next[pendingAttachmentSessionKey];
          return next;
        });
        pendingAttachmentSessionKey = session.id;
      }
      setRunningBySession((running) => ({ ...running, [session.id]: true }));
      let uploadedAttachment = null;
      let uploadedAssetDocument = null;
      if (pendingAttachment) {
        const form = new FormData();
        form.append("upload", pendingAttachment, pendingAttachment.name);
        const uploaded = await api(
          `/api/quickops/sessions/${encodeURIComponent(session.id)}/attachments`,
          { method: "POST", body: form },
        );
        uploadedAttachment = uploaded.attachment;
        uploadedAssetDocument = uploaded.asset_document || null;
        setSessionAttachment(null, pendingAttachmentSessionKey);
      }
      const temporaryUserId = `u-${Date.now()}`;
      updateSessionMessages(session.id, (items) => [
        ...items,
        {
          id: temporaryUserId,
          role: "user",
          kind: "user",
          message_type: inputMode === "manual" ? "manual_command" : "user",
          time: now,
          content: messageValue,
          metadata: {
            source:
              inputMode === "manual" ? "manual_composer" : "ai_composer",
            attachments: uploadedAttachment ? [uploadedAttachment] : [],
            asset_document: uploadedAssetDocument,
          },
        },
      ]);
      const endpoint =
        inputMode === "manual"
          ? "/api/quickops/manual-commands"
          : "/api/quickops/runs";
      const payload =
        inputMode === "manual"
          ? { host_id: runtime.hostId, command: messageValue, session_id: session.id }
          : {
              host_id: runtime.hostId,
              message: messageValue,
              session_id: session.id,
              user_id: "operator",
              model_id: selectedModel.id,
              model_config_id: selectedModel.id,
              permission_mode: permission.apiId,
              attachment_ids: uploadedAttachment ? [uploadedAttachment.id] : [],
            };
      let response;
      try {
        response = await api(endpoint, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      } catch (error) {
        if (error.status === 202 || error.data?.approval_required)
          response = error.data;
        else throw error;
      }
      if (response?.user_message_id)
        updateSessionMessages(session.id, (items) =>
          reconcileOptimisticUserMessage(
            items,
            temporaryUserId,
            response.user_message_id,
          ),
        );
      if (
        response?.approval_required ||
        response?.approval ||
        response?.approval_request
      ) {
        appendApproval(session.id, response, now);
        finishRun(session.id, response.run_id || "approval");
      } else if (inputMode === "manual") {
        setTerminalBySession((all) => ({
          ...all,
          [session.id]: {
            status: response.terminal_alive === false ? "closed" : "connected",
            terminalId: response.terminal_id || all[session.id]?.terminalId,
            shell: response.shell,
            cwd: response.cwd,
          },
        }));
        updateSessionMessages(session.id, (items) => [
          ...items,
          {
            id: response.message_id || `m-${Date.now()}`,
            role: "assistant",
            kind: "manual",
            time: clockOf(response.created_at),
            content: `$ ${response.command || messageValue}\n${response.output || ""}\n\n[exit ${response.exit_code ?? 0}]`,
          },
        ]);
        finishRun(session.id, response.run_id || "manual");
      } else if (response?.run_id && !response?.content) {
        const messageId = response.message_id || `stream-${response.run_id}`;
        setActiveRunBySession((runs) => ({
          ...runs,
          [session.id]: response.run_id,
        }));
        updateSessionMessages(session.id, (items) => [
          ...items,
          {
            id: messageId,
            run_id: response.run_id,
            role: "assistant",
            kind: "stream",
            time: now,
            status: "thinking",
            phase: "正在思考",
            content: "",
            tools: [],
            segments: [],
          },
        ]);
        connectRunStream(session.id, response.run_id, messageId);
      } else {
        updateSessionMessages(session.id, (items) => [
          ...items,
          {
            id: response.message_id || `a-${Date.now()}`,
            role: "assistant",
            kind: "runtime",
            time: now,
            status: response.status,
            content: response.content,
            tools: response.tools || [],
          },
        ]);
        finishRun(session.id, response.run_id || "inline");
      }
      const [sessionResult] = await Promise.allSettled([
        refreshSessions(),
        refreshBootstrap(),
      ]);
      if (sessionResult.status === "fulfilled") {
        const current = sessionResult.value.find((s) => s.id === session.id);
        if (current) setActiveSession(current);
      }
    } catch (error) {
      if (targetSessionId) {
        updateSessionMessages(targetSessionId, (items) => [
          ...items,
          {
            id: `error-${Date.now()}`,
            role: "assistant",
            kind: "runtime",
            time: now,
            status: "failed",
            content: error.message,
          },
        ]);
        setRunningBySession((running) => ({
          ...running,
          [targetSessionId]: false,
        }));
      } else notify(error.message);
    } finally {
      window.requestAnimationFrame(() => {
        const conversation = conversationRef.current;
        if (conversation) conversation.scrollTop = conversation.scrollHeight;
      });
    }
  };

  const cancelRun = async () => {
    if (!activeSession?.id || !activeRunId) return;
    const sessionId = activeSession.id;
    const runId = activeRunId;
    try {
      await api(`/api/quickops/runs/${encodeURIComponent(runId)}/cancel`, {
        method: "POST",
      });
      updateSessionMessages(sessionId, (items) =>
        items.map((item) =>
          item.run_id === runId &&
          (item.kind === "stream" ||
            item.status === "running" ||
            item.status === "thinking")
            ? {
                ...item,
                kind: "runtime",
                status: "cancelled",
                phase: "",
                content: item.content || "回复已由操作员中止。",
              }
            : item,
        ),
      );
      finishRun(sessionId, runId);
      notify(t("已中止当前回复"));
    } catch (error) {
      notify(error.message);
    }
  };

  const editAndResend = (message) => {
    if (!activeSession?.id || !message.id || requestPending) return;
    setInputMode("ai");
    setInput(message.content || "");
    setEditingMessage({
      sessionId: activeSession.id,
      messageId: message.id,
      content: message.content || "",
    });
    window.requestAnimationFrame(() => {
      if (textareaRef.current) {
        resizeTextarea(textareaRef.current);
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(
          textareaRef.current.value.length,
          textareaRef.current.value.length,
        );
      }
    });
  };

  const cancelEditing = () => {
    setEditingMessage(null);
    setInput("");
    if (textareaRef.current) resizeTextarea(textareaRef.current);
  };

  const toggleTool = async (tool) => {
    if (!tool.available || toolboxSaving) return;
    const enabledIds = toolbox
      .filter(
        (item) =>
          item.available &&
          (item.id === tool.id ? !item.enabled : item.enabled),
      )
      .map((item) => item.id);
    setToolboxSaving(tool.id);
    setToolbox((items) =>
      items.map((item) =>
        item.id === tool.id ? { ...item, enabled: !item.enabled } : item,
      ),
    );
    try {
      await api("/api/quickops/settings/agent_toolbox_enabled", {
        method: "PUT",
        body: JSON.stringify({ value: enabledIds }),
      });
      notify(tool.enabled ? `已停用 ${tool.name}` : `已启用 ${tool.name}`);
    } catch (error) {
      setToolbox((items) =>
        items.map((item) =>
          item.id === tool.id ? { ...item, enabled: tool.enabled } : item,
        ),
      );
      notify(error.message);
    } finally {
      setToolboxSaving("");
    }
  };

  const decideApproval = async (approval, action) => {
    setApprovalPending(approval.id);
    try {
      const sessionId = activeSession?.id;
      let data;
      if (approval.run_id) {
        data = await api(
          `/api/quickops/runs/${encodeURIComponent(approval.run_id)}/confirm`,
          {
            method: "POST",
            body: JSON.stringify({
              approved: action === "approve",
              note: action === "approve" ? "用户已批准" : "用户已拒绝",
              requirement_id: approval.requirement_id,
            }),
          },
        );
      } else {
        data = await api(
          `/api/quickops/approvals/${encodeURIComponent(approval.approval_id)}/${action}`,
          { method: "POST", body: JSON.stringify({ session_id: sessionId }) },
        );
      }
      setApprovalBySession((all) => ({ ...all, [sessionId]: null }));
      const operationText = approval.operations
        .map((operation) => operation.title.replace(/[：:]$/, ""))
        .join("、");
      const approvalEvent = data?.run?.approval_event || {
        decision: action === "approve" ? "approved" : "rejected",
        content: `用户${action === "approve" ? "批准" : "拒绝"}了${operationText}`,
      };
      updateSessionMessages(sessionId, (items) =>
        items.map((item) =>
          item.id === approval.stream_message_id
            ? {
                ...item,
                segments: insertApprovalSegment(item.segments, approvalEvent),
              }
            : item,
        ),
      );
      if (action === "approve" && data?.output != null)
        updateSessionMessages(sessionId, (items) => [
          ...items,
          {
            id: `m-${Date.now()}`,
            role: "assistant",
            kind: "manual",
            time: clockOf(),
            content: `$ ${data.command || operationText}\n${data.output}\n\n[exit ${data.exit_code ?? 0}]`,
          },
        ]);
      if (approval.run_id)
        connectRunStream(
          sessionId,
          approval.run_id,
          approval.stream_message_id,
          approvalEvent.sequence || approval.sequence,
        );
      await Promise.allSettled([refreshSessions(), refreshBootstrap()]);
      notify(action === "approve" ? t("已批准，小维将继续执行") : t("已拒绝，小维将调整方案"));
    } catch (error) {
      notify(error.message);
    } finally {
      setApprovalPending(null);
    }
  };

  const answerFeedback = async (feedback, selections) => {
    if (feedbackSubmittingRef.current.has(feedback.id)) return;
    feedbackSubmittingRef.current.add(feedback.id);
    setFeedbackPending(feedback.id);
    const sessionId = activeSession?.id;
    setFeedbackBySession((all) =>
      all[sessionId]?.id === feedback.id
        ? { ...all, [sessionId]: null }
        : all,
    );
    try {
      updateSessionMessages(sessionId, (items) => [
        ...items.map((item) =>
          item.id === feedback.stream_message_id
            ? { ...item, status: "thinking", phase: "正在思考" }
            : item,
        ),
      ]);
      await api(
        `/api/quickops/runs/${encodeURIComponent(feedback.run_id)}/feedback`,
        {
          method: "POST",
          body: JSON.stringify({
            requirement_id: feedback.requirement_id,
            selections,
          }),
        },
      );
      connectRunStream(
        sessionId,
        feedback.run_id,
        feedback.stream_message_id,
        feedback.sequence,
      );
      notify(t("已选择，小维将继续"));
    } catch (error) {
      updateSessionMessages(sessionId, (items) =>
        items.map((item) =>
          item.id === feedback.stream_message_id
            ? { ...item, status: "paused", phase: "等待你的选择" }
            : item,
        ),
      );
      setFeedbackBySession((all) => ({ ...all, [sessionId]: feedback }));
      notify(error.message);
    } finally {
      feedbackSubmittingRef.current.delete(feedback.id);
      setFeedbackPending(null);
    }
  };

  const selectPermission = async (option) => {
    if (!enabledModes.includes(option.id)) return;
    const previous = permission;
    setPermission(option);
    setPermissionOpen(false);
    if (!activeSession) return;
    try {
      const data = await api(
        `/api/quickops/sessions/${encodeURIComponent(activeSession.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ permission_mode: option.apiId }),
        },
      );
      const updated = normalizeSession(data.session || data);
      setActiveSession((s) => ({ ...s, ...updated }));
      setSessions((items) =>
        items.map((s) =>
          s.id === activeSession.id ? { ...s, ...updated } : s,
        ),
      );
    } catch (error) {
      setPermission(previous);
      notify(error.message);
    }
  };

  const selectModel = async (model) => {
    const previous = selectedModel;
    setSelectedModel(model);
    setModelOpen(false);
    if (!activeSession) return;
    try {
      const data = await api(
        `/api/quickops/sessions/${encodeURIComponent(activeSession.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ model_config_id: model.id }),
        },
      );
      const updated = normalizeSession(data.session || data);
      setActiveSession((s) => ({ ...s, ...updated }));
      setSessions((items) =>
        items.map((s) =>
          s.id === activeSession.id ? { ...s, ...updated } : s,
        ),
      );
    } catch (error) {
      setSelectedModel(previous);
      notify(error.message);
    }
  };

  const renameSession = async (event, session) => {
    event.stopPropagation();
    const nextTitle = window.prompt(t("重命名会话"), session.title)?.trim();
    if (!nextTitle || nextTitle === session.title) return;
    try {
      const data = await api(
        `/api/quickops/sessions/${encodeURIComponent(session.id)}`,
        { method: "PATCH", body: JSON.stringify({ title: nextTitle }) },
      );
      const updated = normalizeSession(data.session || data);
      setSessions((items) =>
        items.map((item) =>
          item.id === session.id ? { ...item, ...updated } : item,
        ),
      );
      setActiveSession((current) =>
        current?.id === session.id ? { ...current, ...updated } : current,
      );
      notify(t("会话已重命名"));
    } catch (error) {
      notify(error.message);
    }
  };

  const deleteSession = async (event, session) => {
    event.stopPropagation();
    if (!window.confirm(`确定删除会话“${session.title}”吗？此操作不可撤销。`))
      return;
    try {
      await api(`/api/quickops/sessions/${encodeURIComponent(session.id)}`, {
        method: "DELETE",
      });
      const remaining = sessions.filter((item) => item.id !== session.id);
      setSessions(remaining);
      setMessagesBySession((all) => {
        const next = { ...all };
        delete next[session.id];
        return next;
      });
      setTerminalBySession((all) => {
        const next = { ...all };
        delete next[session.id];
        return next;
      });
      setPendingAttachmentBySession((all) => {
        const next = { ...all };
        delete next[session.id];
        return next;
      });
      if (activeSession?.id === session.id) {
        setActiveSession(null);
        if (remaining[0]) await loadSession(remaining[0]);
      }
      notify(t("会话已删除"));
    } catch (error) {
      notify(error.message);
    }
  };

  const controlTerminal = async (action) => {
    if (!activeSession?.id) return;
    try {
      const response = await api(
        `/api/quickops/sessions/${encodeURIComponent(activeSession.id)}/terminal/${action}`,
        { method: "POST", body: JSON.stringify({ host_id: runtime.hostId }) },
      );
      setTerminalBySession((all) => ({
        ...all,
        [activeSession.id]: {
          ...all[activeSession.id],
          ...(response || {}),
          status: response?.terminal_alive === false ? "closed" : "connected",
        },
      }));
      notify(t("终端会话已重启"));
    } catch (error) {
      notify(error.message);
    }
  };

  const openSettings = (page = "general") => {
    setSettingsPage(page);
    setSettingsOpen(true);
    setModelOpen(false);
    setPermissionOpen(false);
  };
  const openNewModel = () => {
    setEditingModel(null);
    setModelForm({
      name: "",
      provider: "SiliconFlow",
      model_id: "",
      base_url: "",
      api_key: "",
      thinking_mode: "auto",
      max_context_k: 128,
      supports_vision: false,
      is_default: false,
    });
    setModelOpen(false);
    openSettings("models");
  };
  const editModel = (model) => {
    setEditingModel(model);
    setModelForm({
      name: model.name || "",
      provider: model.provider || "SiliconFlow",
      model_id: model.model_id || "",
      base_url: model.base_url || "",
      api_key: "",
      thinking_mode: model.thinking_mode || "auto",
      max_context_k: model.max_context_k || 128,
      supports_vision: !!model.supports_vision,
      is_default: !!model.is_default,
    });
    openSettings("models");
  };
  const saveModel = async (event) => {
    event.preventDefault();
    try {
      const path = editingModel
        ? `/api/quickops/models/${encodeURIComponent(editingModel.id)}`
        : "/api/quickops/models";
      const saved = await api(path, {
        method: editingModel ? "PATCH" : "POST",
        body: JSON.stringify(modelForm),
      });
      await refreshModels();
      setSelectedModel(saved?.model || saved || selectedModel);
      notify(t("模型配置已保存"));
    } catch (error) {
      notify(error.message);
    }
  };
  const deleteModel = async (model) => {
    if (!window.confirm(`确定删除模型“${model.name}”吗？`)) return;
    try {
      await api(`/api/quickops/models/${encodeURIComponent(model.id)}`, {
        method: "DELETE",
      });
      await refreshModels();
      if (editingModel?.id === model.id) setEditingModel(null);
      notify("模型配置已删除");
    } catch (error) {
      notify(error.message || "该模型当前不可删除");
    }
  };
  const makeDefault = async (model) => {
    try {
      await api(`/api/quickops/models/${encodeURIComponent(model.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ is_default: true }),
      });
      await refreshModels();
      notify(`${model.name} 已设为默认模型`);
    } catch (error) {
      notify(error.message);
    }
  };

  const copyMessage = async (message) => {
    try {
      await writeClipboardText(
        message.content || message.command || message.reason || "",
      );
      notify(t("消息已复制"));
    } catch {
      notify(t("复制失败，请检查浏览器权限"));
    }
  };
  const copySessionId = async () => {
    if (!activeSession?.id) return;
    try {
      await writeClipboardText(activeSession.id);
      notify(t("会话 ID 已复制"));
    } catch {
      notify(t("复制失败，请检查浏览器权限"));
    }
  };
  const branchMessage = async (message) => {
    if (!activeSession?.id || !message.id) return;
    try {
      const data = await api(
        `/api/quickops/sessions/${encodeURIComponent(activeSession.id)}/branch`,
        {
          method: "POST",
          body: JSON.stringify({ through_message_id: message.id }),
        },
      );
      const branch = normalizeSession(data.session || data);
      setSessions((items) => [
        branch,
        ...items.filter((item) => item.id !== branch.id),
      ]);
      await loadSession(branch);
      notify(t("已从该消息创建分支会话"));
    } catch (error) {
      notify(error.message);
    }
  };
  const saveGeneralSettings = async () => {
    try {
      await Promise.all(
        Object.entries(generalSettings).map(([key, value]) =>
          api(`/api/quickops/settings/${key}`, {
            method: "PUT",
            body: JSON.stringify({ value }),
          }),
        ),
      );
      notify(t("设置已保存"));
    } catch (error) {
      notify(error.message);
    }
  };

  const exportReport = async () => {
    if (!activeSession?.id) return;
    let reportMessages = messages;
    try {
      const data = await api(
        `/api/quickops/sessions/${encodeURIComponent(activeSession.id)}/report-messages`,
      );
      reportMessages = listFrom(data, "messages").map(normalizeMessage);
    } catch (error) {
      notify(error.message);
      return;
    }
    const transcript = reportMessages
      .map(
        (m) => {
          const revised = m.metadata?.superseded_by_revision
            ? " · 修订前记录（已从当前会话隐藏）"
            : "";
          return `## ${m.role === "user" ? "操作员" : m.kind === "manual" ? "服务器回显" : "小维"} · ${m.time}${revised}\n\n${m.content || m.command || "（工具执行记录）"}`;
        },
      )
      .join("\n\n");
    const body = `# QuickOps 诊断报告\n\n会话：${activeSession?.title || "新会话"}\n目标主机：${runtime.hostId}\n模型：${selectedModel.name}\n权限：${permission.label}\n\n${transcript}`;
    const url = URL.createObjectURL(
      new Blob([body], { type: "text/markdown" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `quickops-${activeSession?.id?.slice(-8) || "session"}.md`;
    link.click();
    URL.revokeObjectURL(url);
    notify(t("诊断报告已导出"));
  };

  const PermissionIcon = permission.icon;
  const host = useMemo(
    () =>
      runtime.hosts.find((h) => (h.id || h.host_id) === runtime.hostId) ||
      runtime.hosts[0] ||
      {},
    [runtime],
  );
  const metrics = host.metrics || host.signals || {};
  const cpu = Number(
    metrics.cpu_percent ?? metrics.cpu ?? host.cpu_percent ?? 0,
  );
  const memory = Number(
    metrics.memory_percent ?? metrics.memory ?? host.memory_percent ?? 0,
  );
  const disk = Number(
    metrics.disk_percent ?? metrics.disk ?? host.disk_percent ?? 0,
  );
  const load = metrics.load_1m ?? metrics.load ?? host.load_1m ?? "—";
  const network =
    metrics.network ||
    metrics.network_io ||
    (metrics.network_out_kbps != null
      ? `${metrics.network_out_kbps}K / ${metrics.network_in_kbps ?? 0}K`
      : "—");

  const submitLogin = async (event) => {
    event.preventDefault();
    setLoginPending(true);
    setLoginError("");
    try {
      const result = await api("/api/quickops/auth/login", {
        method: "POST",
        body: JSON.stringify(loginForm),
      });
      saveSessionAccessToken(result.access_token || "");
      // Do not render the authenticated workspace until the browser proves that it
      // accepted and can return the HttpOnly cookie. This avoids a one-frame login
      // followed by an initialization 401 that looks like a "login flash".
      const verified = await api("/api/quickops/auth/status");
      if (!verified.authenticated) {
        saveSessionAccessToken("");
        throw new Error(
          "浏览器未能保存登录状态，请确认使用当前 HTTP 地址并允许此站点使用 Cookie。",
        );
      }
      setLoginForm((current) => ({ ...current, password: "" }));
      setAuth({
        checking: false,
        configured: true,
        authenticated: true,
        username: verified.username || result.username || loginForm.username,
      });
    } catch (error) {
      setLoginError(error.message);
    } finally {
      setLoginPending(false);
    }
  };

  const logout = async () => {
    try {
      await api("/api/quickops/auth/logout", { method: "POST" });
    } catch {
      // A locally expired session is already logged out from the operator's perspective.
    }
    streamsRef.current.forEach((source) => source.close());
    streamsRef.current.clear();
    setSessions([]);
    setActiveSession(null);
    setMessagesBySession({});
    saveSessionAccessToken("");
    setAuth((current) => ({ ...current, authenticated: false, username: "" }));
  };

  if (auth.checking)
    return (
      <main className="login-shell login-shell-loading">
        <div className="login-loading">{t("正在验证 QuickOps 登录状态…")}</div>
      </main>
    );

  if (!auth.authenticated)
    return (
      <main className="login-shell">
        <section className="login-card" aria-labelledby="login-title">
          <div className="login-brand">
            QuickOps <span>快维</span>
          </div>
          <div className="login-icon"><LockSimple size={22} weight="fill" /></div>
          <h1 id="login-title">{t("登录运维工作台")}</h1>
          <p>{t("验证身份后才能访问主机、终端和会话数据。")}</p>
          {!auth.configured ? (
            <div className="login-config-error">
              {t("服务端尚未配置登录凭据。请设置")} <code>QUICKOPS_AUTH_USERNAME</code> {locale === "en-US" ? "and" : "和"}
              <code>QUICKOPS_AUTH_PASSWORD</code> {t("后重启服务。")}
            </div>
          ) : (
            <form onSubmit={submitLogin}>
              <label>
                {t("账号")}
                <input
                  autoFocus
                  autoComplete="username"
                  value={loginForm.username}
                  onChange={(event) =>
                    setLoginForm({ ...loginForm, username: event.target.value })
                  }
                  required
                />
              </label>
              <label>
                {t("密码")}
                <input
                  type="password"
                  autoComplete="current-password"
                  value={loginForm.password}
                  onChange={(event) =>
                    setLoginForm({ ...loginForm, password: event.target.value })
                  }
                  required
                />
              </label>
              {loginError && <div className="login-error" role="alert">{loginError}</div>}
              <button type="submit" disabled={loginPending}>
                {loginPending ? t("正在登录…") : t("登录")}
              </button>
            </form>
          )}
        </section>
      </main>
    );

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          QuickOps <span>快维</span>
        </div>
        <button className="new-session" onClick={newSession}>
          <Plus size={18} weight="bold" />
          {t("新建会话")}
        </button>
        <div className="sidebar-title">{t("最近会话")}</div>
        <div className="session-list">
          {sessions.length ? (
            sessions.map((s) => (
              <div
                key={s.id}
                className={
                  activeSession?.id === s.id ? "session active" : "session"
                }
              >
                <button className="session-main" onClick={() => loadSession(s)}>
                  <span>{s.title}</span>
                </button>
                <div className="session-tail">
                  {(runningBySession[s.id] || completedNoticeBySession[s.id]) && (
                    <span className="session-status">
                      {runningBySession[s.id] ? (
                        <i className="session-running" title={t("任务执行中")} />
                      ) : (
                        <i className="session-completed" title={t("任务已完成")} />
                      )}
                    </span>
                  )}
                  <div className="session-actions">
                    <button
                      onClick={(event) => renameSession(event, s)}
                      title={t("重命名会话")}
                      aria-label={`${t("重命名会话")} ${s.title}`}
                    >
                      <PencilSimple size={13} />
                    </button>
                    <button
                      onClick={(event) => deleteSession(event, s)}
                      title={t("删除会话")}
                      aria-label={`${t("删除会话")} ${s.title}`}
                    >
                      <Trash size={13} />
                    </button>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="session-empty">{t("暂无会话")}</div>
          )}
        </div>
        <div className="operator-card">
          <UserCircle size={36} weight="fill" />
          <div>
            <strong>{auth.username || "operator"}</strong>
            <span>{t("运维工程师")}</span>
          </div>
          <button
            className="settings-button"
            onClick={logout}
            aria-label={t("退出登录")}
            title={t("退出登录")}
          >
            <SignOut size={18} />
          </button>
          <button
            className="settings-button"
            onClick={() => openSettings("general")}
            aria-label={t("打开设置")}
          >
            <Gear size={18} />
          </button>
        </div>
      </aside>
      <section className="workspace">
        <header className="workspace-head">
          <div>
            <h1>{activeSession?.title || t("新会话")}</h1>
            <div className="session-meta">
              <span>{timeOf(activeSession?.updated_at, locale)}</span>
              <i />
              <span>{t("会话 ID：")}{activeSession?.id?.slice(-12) || t("未创建")}</span>
              <button
                type="button"
                className="session-id-copy"
                onClick={copySessionId}
                aria-label={t("复制会话 ID")}
                title={t("复制会话 ID")}
                disabled={!activeSession?.id}
              >
                <Copy size={14} />
              </button>
            </div>
          </div>
          <div className="head-actions">
            <button
              className="outline-button"
              onClick={exportReport}
              disabled={!messages.length}
            >
              <DownloadSimple size={17} />
              {t("导出报告")}
            </button>
          </div>
        </header>
        <div
          className="conversation"
          aria-live="polite"
          ref={conversationRef}
          onScroll={(event) => {
            if (!event.nativeEvent.isTrusted) return;
            const element = event.currentTarget;
            shouldFollowOutputRef.current =
              element.scrollHeight - element.scrollTop - element.clientHeight < 72;
          }}
        >
          {messages.length ? (
            messages.map((m) => (
              <ConversationMessage
                key={m.id}
                message={m}
                onDecision={decideApproval}
                approvalPending={approvalPending}
                onCopy={copyMessage}
                onBranch={branchMessage}
                onEdit={editAndResend}
                t={t}
                canEdit={
                  inputMode === "ai" &&
                  m.id === lastAgentUserMessageId &&
                  !requestPending
                }
              />
            ))
          ) : (
            <div className="empty-state">
              <Robot size={42} weight="duotone" />
              <h2>{t("从一个运维目标开始")}</h2>
              <p>{t("描述排查目标，或切换到手动命令直接使用目标主机的终端。")}</p>
            </div>
          )}
          <div className="conversation-end" />
        </div>
        <div className="composer-wrap">
          {activeFeedback && (
            <UserChoicePrompt
              feedback={activeFeedback}
              onSubmit={answerFeedback}
              pending={feedbackPending === activeFeedback.id}
              t={t}
            />
          )}
          {activeApproval && (
            <ApprovalPrompt
              approval={activeApproval}
              onDecision={decideApproval}
              pending={approvalPending === activeApproval.id}
              t={t}
            />
          )}
          {editingMessage && (
            <div className="editing-banner">
              <PencilSimple size={14} />
              <span>{t("编辑后发送将覆盖当前会话，并在报告中保留修订前记录")}</span>
              <button onClick={cancelEditing}>
                <X size={13} />{t("取消编辑")}
              </button>
            </div>
          )}
          <div className="composer-modebar">
            <div className="mode-tabs">
              <button
                className={inputMode === "ai" ? "active" : ""}
                onClick={() => setInputMode("ai")}
              >
                <Robot size={15} />
                {t("AI 会话")}
              </button>
              <button
                className={inputMode === "manual" ? "active" : ""}
                onClick={() => {
                  setInputMode("manual");
                  setEditingMessage(null);
                  setPermissionOpen(false);
                  setModelOpen(false);
                }}
              >
                <TerminalWindow size={15} />
                {t("手动命令")}
              </button>
            </div>
            {inputMode === "manual" && (
              <div className="terminal-session-tools">
                {activeSession?.id && (
                  <button
                    onClick={() => controlTerminal("restart")}
                    title={t("重启终端（重置当前路径和临时环境）")}
                    aria-label={t("重启终端")}
                  >
                    <ArrowClockwise size={14} />
                  </button>
                )}
              </div>
            )}
            {inputMode === "ai" && (
              <div className="composer-tools">
                {activeSession?.asset_service && (
                  <button
                    className="mounted-asset-chip"
                    onClick={() =>
                      setAssetCenter({ service: activeSession.asset_service, tab: "status" })
                    }
                    title={t("上传文件将同时归档到已挂载服务的文档库")}
                  >
                    <HardDrives size={14} />
                    {activeSession.asset_service.name}
                  </button>
                )}
                <div className="model-control" ref={modelControlRef}>
                  <button
                    className="model-trigger"
                    onClick={() => {
                      setModelOpen(!modelOpen);
                      setPermissionOpen(false);
                    }}
                    aria-expanded={modelOpen}
                  >
                    <Robot size={16} />
                    {selectedModel?.name || t("选择模型")}
                    <CaretDown size={13} />
                  </button>
                  {modelOpen && (
                    <div className="model-menu">
                      <div className="menu-label">{t("选择模型")}</div>
                      {models.map((m) => (
                        <button
                          key={m.id}
                          className={
                            selectedModel?.id === m.id ? "selected" : ""
                          }
                          onClick={() => selectModel(m)}
                        >
                          <span className="model-mark">
                            {m.name.slice(0, 1)}
                          </span>
                          <span className="model-copy">
                            <strong>{m.name}</strong>
                            <small>{m.provider}</small>
                          </span>
                          {m.is_default && <em>{t("默认")}</em>}
                          {selectedModel?.id === m.id && <Check size={16} />}
                        </button>
                      ))}
                      <div className="menu-separator" />
                      <button
                        className="model-config-action"
                        onClick={openNewModel}
                      >
                        <Plus size={15} />
                        <span>
                          <strong>{t("配置自定义模型")}</strong>
                          <small>{t("前往设置中心")}</small>
                        </span>
                      </button>
                    </div>
                  )}
                </div>
                <div className="permission-control" ref={permissionControlRef}>
                  <button
                    className="permission-trigger"
                    onClick={() => {
                      setPermissionOpen(!permissionOpen);
                      setModelOpen(false);
                    }}
                    aria-expanded={permissionOpen}
                  >
                    <PermissionIcon size={16} />
                    {t(permission.label)}
                    <CaretDown size={13} />
                  </button>
                  {permissionOpen && (
                    <div className="permission-menu">
                      {permissionCatalog.map((o) => {
                        const Icon = o.icon;
                        const disabled = !enabledModes.includes(o.id);
                        return (
                          <button
                            key={o.id}
                            className={permission.id === o.id ? "selected" : ""}
                            disabled={disabled}
                            onClick={() => selectPermission(o)}
                          >
                            <Icon size={18} />
                            <span>
                              <strong>{t(o.label)}</strong>
                              <small>
                                {disabled ? t("服务端尚未启用") : t(o.note)}
                              </small>
                            </span>
                            {permission.id === o.id && <Check size={16} />}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
          <div className={`composer ${inputMode === "manual" ? "manual" : ""}`}>
            {inputMode === "ai" && (
              <button
                className="attach-button"
                onClick={() => fileRef.current?.click()}
              >
                <Paperclip size={21} />
              </button>
            )}
            <input
              ref={fileRef}
              type="file"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                if (file.size > 25 * 1024 * 1024) {
                  e.target.value = "";
                  notify(t("单个附件不能超过 25 MB"));
                  return;
                }
                if (file.type.startsWith("image/") && !selectedModel?.supports_vision) {
                  e.target.value = "";
                  notify(t("当前模型未启用图像理解能力"));
                  return;
                }
                setSessionAttachment(file);
                e.target.value = "";
              }}
              accept="image/*,.md,.txt,.log,.csv,.json,.yaml,.yml,.xml,.ini,.conf,.pdf,.doc,.docx,.xls,.xlsx"
            />
            {inputMode === "manual" && (
              <div
                className="terminal-path-prompt"
                title={terminalBySession[activeSession?.id]?.cwd || t("正在获取当前路径")}
                aria-label={`${t("正在获取当前路径")}：${terminalBySession[activeSession?.id]?.cwd || t("正在获取")}`}
              >
                <span>
                  {terminalBySession[activeSession?.id]?.cwd || t("正在获取路径…")}
                </span>
                <b>$</b>
              </div>
            )}
            <div className="composer-input-area">
              {inputMode === "ai" && attachment && (
                <ComposerAttachment
                  file={attachment}
                  onRemove={() => setSessionAttachment(null)}
                  t={t}
                />
              )}
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  if (inputMode === "manual") resetCommandHistoryCursor();
                  resizeTextarea(e.currentTarget);
                }}
                onCompositionStart={() => {
                  isComposingRef.current = true;
                }}
                onCompositionEnd={(e) => {
                  isComposingRef.current = false;
                  setInput(e.currentTarget.value);
                  resizeTextarea(e.currentTarget);
                }}
                onPaste={(e) => {
                  if (inputMode !== "ai") return;
                  const image = [...(e.clipboardData?.items || [])].find(
                    (item) => item.kind === "file" && item.type.startsWith("image/"),
                  );
                  if (!image) return;
                  e.preventDefault();
                  if (!selectedModel?.supports_vision) {
                    notify(t("当前模型未启用图像理解能力"));
                    return;
                  }
                  const source = image.getAsFile();
                  if (!source) return;
                  if (source.size > 25 * 1024 * 1024) {
                    notify(t("单个附件不能超过 25 MB"));
                    return;
                  }
                  const extension = source.type.split("/")[1]?.replace("jpeg", "jpg") || "png";
                  const pasted = new File(
                    [source],
                    `pasted-image-${new Date().toISOString().replaceAll(":", "-")}.${extension}`,
                    { type: source.type, lastModified: Date.now() },
                  );
                  setSessionAttachment(pasted);
                }}
                onKeyDown={(e) => {
                  if (
                    e.isComposing ||
                    e.nativeEvent?.isComposing ||
                    isComposingRef.current ||
                    e.keyCode === 229
                  ) return;
                  if (
                    inputMode === "manual" &&
                    !e.shiftKey &&
                    !e.altKey &&
                    !e.metaKey &&
                    !e.ctrlKey &&
                    (e.key === "ArrowUp" || e.key === "ArrowDown")
                  ) {
                    e.preventDefault();
                    navigateCommandHistory(e.key === "ArrowUp" ? -1 : 1);
                    return;
                  }
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (!requestPending) submit();
                  }
                }}
                placeholder={
                  inputMode === "ai"
                    ? t("输入你的运维问题或下一步指令…")
                    : t("在当前终端会话中输入 Shell 命令…")
                }
                rows={1}
              />
            </div>
            <button
              className={`send-button ${requestPending && activeRunId ? "stop" : ""}`}
              onClick={requestPending && activeRunId ? cancelRun : submit}
              disabled={
                requestPending
                  ? !activeRunId
                  : !input.trim() && !(inputMode === "ai" && attachment)
              }
              title={requestPending && activeRunId ? t("中止回复") : t("发送消息")}
              aria-label={requestPending && activeRunId ? t("中止回复") : t("发送消息")}
            >
              {requestPending && activeRunId ? (
                <Stop size={17} weight="fill" />
              ) : (
                <PaperPlaneTilt size={20} weight="fill" />
              )}
            </button>
          </div>
        </div>
      </section>
      <aside className="context-rail">
        <section className="context-section host-section">
          <h3>{t("目标主机")}</h3>
          <div className="host-name">
            <span className="online-dot" />
            {host.name || host.hostname || runtime.hostId || t("未连接")}
            {(host.is_local ||
              host.kind === "local" ||
              host.source === "local") && (
              <span className="local-chip">{t("本机")}</span>
            )}
          </div>
          <dl>
            <dt>IP</dt>
            <dd>{host.ip || host.address || "127.0.0.1"}</dd>
            <dt>{t("环境")}</dt>
            <dd>{host.environment || t("本地测试")}</dd>
            <dt>{t("平台")}</dt>
            <dd>{host.platform || host.os || host.role || "—"}</dd>
            <dt>{t("标签")}</dt>
            <dd>
              {(host.tags || ["local"]).map((tag) => (
                <span key={tag} className="tag">
                  {tag}
                </span>
              ))}
            </dd>
          </dl>
        </section>
        <section className="context-section signals">
          <h3>{t("主机信号（实时）")}</h3>
          <Signal
            icon={Cpu}
            label={t("CPU 使用率")}
            value={`${cpu.toFixed(1)}%`}
            width={`${Math.min(cpu, 100)}%`}
            tone={cpu > 80 ? "orange" : "teal"}
          />
          <Signal
            icon={Activity}
            label={t("负载（1m）")}
            value={String(load)}
            width={`${Math.min(Number(load) * 20 || 0, 100)}%`}
          />
          <Signal
            icon={HardDrives}
            label={t("内存使用率")}
            value={`${memory.toFixed(1)}%`}
            width={`${Math.min(memory, 100)}%`}
            tone={memory > 80 ? "orange" : "teal"}
          />
          <Signal
            icon={HardDrives}
            label={t("磁盘使用率")}
            value={`${disk.toFixed(1)}%`}
            width={`${Math.min(disk, 100)}%`}
          />
          <Signal
            icon={WifiHigh}
            label={t("网络（出/入）")}
            value={network}
            width="45%"
          />
        </section>
        <section className="context-section asset-rail-section">
          <div className="asset-rail-head">
            <h3>{t("主机资产")}</h3>
            <button
              onClick={() => setAssetCenter({ service: null, tab: "status" })}
              title={t("添加服务")}
              aria-label={t("添加服务")}
            >
              <Plus size={14} />
            </button>
          </div>
          <div className="asset-rail-list">
            {assetServices.map((service) => (
              <article key={service.id} className={expandedAssetRailId === service.id ? "expanded" : ""}>
                <button
                  className="asset-rail-service"
                  onClick={() => setExpandedAssetRailId((current) => current === service.id ? null : service.id)}
                  aria-expanded={expandedAssetRailId === service.id}
                >
                  <span className={`asset-status-dot ${service.status}`} />
                  <strong>{service.name}</strong>
                  {activeSession?.asset_service?.id === service.id && (
                      <em>{t("已挂载")}</em>
                  )}
                  <CaretDown size={12}/>
                </button>
                {expandedAssetRailId === service.id && <div className="asset-rail-actions">
                  {["status", "events", "documents"].map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setAssetCenter({ service, tab })}
                    >
                      {t(tab === "status" ? "状态" : tab === "events" ? "事件" : "文档")}
                    </button>
                  ))}
                </div>}
              </article>
            ))}
            {!assetServices.length && (
              <button
                className="asset-rail-empty"
                onClick={() => setAssetCenter({ service: null, tab: "status" })}
              >
                <Plus size={15} /> {t("添加服务")}
              </button>
            )}
          </div>
        </section>
      </aside>
      {toast && (
        <div className="toast">
          <CheckCircle size={18} weight="fill" />
          {toast}
        </div>
      )}
      {settingsOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) =>
            e.target === e.currentTarget && setSettingsOpen(false)
          }
        >
          <section
            className="settings-center"
            role="dialog"
            aria-modal="true"
            aria-label={t("设置中心")}
          >
            <aside className="settings-nav">
              <div className="settings-brand">
                <Gear size={19} />
                <div>
                  <strong>{t("设置")}</strong>
                  <span>{t("QuickOps 控制中心")}</span>
                </div>
              </div>
              <nav>
                <button
                  className={settingsPage === "general" ? "active" : ""}
                  onClick={() => setSettingsPage("general")}
                >
                  <Gear size={16} />
                  {t("通用")}
                </button>
                <button
                  className={settingsPage === "models" ? "active" : ""}
                  onClick={() => setSettingsPage("models")}
                >
                  <Robot size={16} />
                  {t("模型")}
                </button>
                <button
                  className={settingsPage === "toolbox" ? "active" : ""}
                  onClick={() => setSettingsPage("toolbox")}
                >
                  <Wrench size={16} />
                  {t("工具箱")}
                </button>
              </nav>
            </aside>
            <div className="settings-content">
              <div className="settings-content-head">
                <div>
                  <span>
                    {t("设置 / ")}
                    {settingsPage === "general"
                      ? t("通用")
                      : settingsPage === "models"
                        ? t("模型")
                        : t("工具箱")}
                  </span>
                  <h2>
                    {settingsPage === "general"
                      ? t("通用设置")
                      : settingsPage === "models"
                        ? t("模型管理")
                        : t("工具箱")}
                  </h2>
                </div>
                <button
                  onClick={() => setSettingsOpen(false)}
                  aria-label={t("关闭设置")}
                >
                  <X size={19} />
                </button>
              </div>
              {settingsPage === "general" && (
                <div className="settings-page form-page">
                  <label>
                    {t("界面语言")}
                    <select
                      value={generalSettings.language}
                      onChange={(e) =>
                        setGeneralSettings({
                          ...generalSettings,
                          language: e.target.value,
                        })
                      }
                    >
                      <option value="zh-CN">{t("简体中文")}</option>
                      <option value="en-US">English</option>
                    </select>
                  </label>
                  <label>
                    {t("界面配色")}
                    <div className="theme-selector" role="group" aria-label={t("界面配色")}>
                      <button type="button" className={generalSettings.theme !== "light" ? "active" : ""} onClick={() => setGeneralSettings({...generalSettings, theme:"dark"})}><Moon size={15}/>{t("夜间")}</button>
                      <button type="button" className={generalSettings.theme === "light" ? "active" : ""} onClick={() => setGeneralSettings({...generalSettings, theme:"light"})}><Sun size={15}/>{t("日间")}</button>
                    </div>
                  </label>
                  <label>
                    {t("新会话默认权限")}
                    <select
                      value={generalSettings.default_permission}
                      onChange={(e) =>
                        setGeneralSettings({
                          ...generalSettings,
                          default_permission: e.target.value,
                        })
                      }
                    >
                      {permissionCatalog.map((mode) => (
                        <option key={mode.apiId} value={mode.apiId}>
                          {t(mode.label)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("主机信号刷新间隔（秒）")}
                    <input
                      type="number"
                      min="2"
                      max="60"
                      value={generalSettings.host_refresh_interval}
                      onChange={(e) =>
                        setGeneralSettings({
                          ...generalSettings,
                          host_refresh_interval: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <div className="settings-save">
                    <button className="primary" onClick={saveGeneralSettings}>
                      {t("保存通用设置")}
                    </button>
                  </div>
                </div>
              )}
              {settingsPage === "models" && (
                <div className="model-settings-body">
                  <div className="saved-models">
                    <div className="settings-section-title">
                      {t("已配置模型")}{" "}
                      <button onClick={openNewModel}>
                        <Plus size={14} />
                        {t("新增")}
                      </button>
                    </div>
                    {models.map((m) => (
                      <div
                        key={m.id}
                        className={`saved-model ${editingModel?.id === m.id ? "active" : ""}`}
                      >
                        <button
                          className="saved-model-main"
                          onClick={() => editModel(m)}
                        >
                          <span className="model-mark">
                            {m.name.slice(0, 1)}
                          </span>
                          <span>
                            <strong>{m.name}</strong>
                            <small>
                              {m.provider} · {m.model_id}
                            </small>
                          </span>
                          {m.is_default && <em>{t("默认")}</em>}
                        </button>
                        <div className="saved-model-actions">
                          {!m.is_default && (
                            <button
                              onClick={() => makeDefault(m)}
                              title={t("设为默认")}
                            >
                              <Check size={14} />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  <form onSubmit={saveModel}>
                    <h3>{editingModel ? t("编辑模型") : t("新增模型")}</h3>
                    <label>
                      {t("显示名称")}
                      <input
                        autoFocus
                        value={modelForm.name}
                        onChange={(e) =>
                          setModelForm({ ...modelForm, name: e.target.value })
                        }
                        required
                      />
                    </label>
                    <label>
                      {t("接口协议")}
                      <select
                        value={modelForm.provider}
                        onChange={(e) =>
                          setModelForm({
                            ...modelForm,
                            provider: e.target.value,
                          })
                        }
                      >
                        <option>SiliconFlow</option>
                        <option>Alibaba Cloud</option>
                        <option>DeepSeek</option>
                        <option>vLLM</option>
                        <option>SGLang</option>
                        <option>OpenAI Compatible</option>
                      </select>
                    </label>
                    <label>
                      {t("模型 ID")}
                      <input
                        value={modelForm.model_id}
                        onChange={(e) =>
                          setModelForm({
                            ...modelForm,
                            model_id: e.target.value,
                          })
                        }
                        placeholder="deepseek-ai/DeepSeek-V4-Flash"
                        required
                      />
                    </label>
                    <label>
                      Base URL
                      <input
                        value={modelForm.base_url}
                        onChange={(e) =>
                          setModelForm({
                            ...modelForm,
                            base_url: e.target.value,
                          })
                        }
                        placeholder="https://api.example.com/v1"
                        required
                      />
                    </label>
                    <label>
                      API Key
                      <input
                        type="password"
                        value={modelForm.api_key}
                        onChange={(e) =>
                          setModelForm({
                            ...modelForm,
                            api_key: e.target.value,
                          })
                        }
                        placeholder={
                          editingModel ? t("留空表示保留现有密钥") : t("输入访问密钥")
                        }
                        required={!editingModel}
                      />
                    </label>
                    <label>
                      {t("思考模式")}
                      <select
                        value={modelForm.thinking_mode}
                        onChange={(e) =>
                          setModelForm({
                            ...modelForm,
                            thinking_mode: e.target.value,
                          })
                        }
                      >
                        <option value="auto">{t("自动（遵循模型默认）")}</option>
                        <option value="on">{t("开启")}</option>
                        <option value="off">{t("关闭")}</option>
                      </select>
                    </label>
                    <label>
                      {t("最大上下文（k tokens）")}
                      <input
                        type="number"
                        min="8"
                        max="4096"
                        step="1"
                        value={modelForm.max_context_k}
                        onChange={(e) =>
                          setModelForm({
                            ...modelForm,
                            max_context_k: Number(e.target.value),
                          })
                        }
                        placeholder="128"
                        required
                      />
                    </label>
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={modelForm.supports_vision}
                        onChange={(e) => setModelForm({...modelForm, supports_vision:e.target.checked})}
                      />
                      {t("图像理解（多模态）")}
                    </label>
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={modelForm.is_default}
                        onChange={(e) =>
                          setModelForm({
                            ...modelForm,
                            is_default: e.target.checked,
                          })
                        }
                      />
                      {t("设为默认模型")}
                    </label>
                    <div className="security-note">
                      <Warning size={15} />
                      {t("密钥仅提交并保存在服务端受限存储中；已配置模型可修改或停用，不可删除。")}
                    </div>
                    <div className="modal-actions">
                      <button type="button" onClick={openNewModel}>
                        {t("清空")}
                      </button>
                      <button type="submit" className="primary">
                        {t("保存配置")}
                      </button>
                    </div>
                  </form>
                </div>
              )}
              {settingsPage === "toolbox" && (
                <div className="settings-page toolbox-page">
                  <div className="settings-callout">
                    <Wrench size={22} />
                    <div>
                      <strong>{t("按需启用小维能力")}</strong>
                      <p>{t("扩展工具默认关闭。启用后会在下一次 AI 运行时加入小维的工具箱，并继续受当前权限模式与审批策略约束。")}</p>
                    </div>
                  </div>
                  {toolboxLoading ? (
                    <div className="toolbox-empty">{t("正在读取工具目录…")}</div>
                  ) : toolboxGroups.length ? (
                    <div className="toolbox-groups">
                      {toolboxGroups.map(([category, tools]) => (
                        <section className="toolbox-group" key={category}>
                          <h3>{category}</h3>
                          {tools.map((tool) => (
                            <article className={`toolbox-item ${!tool.available ? "unavailable" : ""}`} key={tool.id}>
                              <div>
                                <div className="toolbox-title">
                                  <strong>{tool.name}</strong>
                                  {tool.usage_tier === "recommended" && (
                                    <em className="tool-tier recommended">{t("推荐")}</em>
                                  )}
                                </div>
                                <p>{tool.description || t("为小维提供对应的专业操作能力。")}</p>
                                {!tool.available && <small>{tool.unavailable_reason}</small>}
                              </div>
                              <button
                                role="switch"
                                aria-checked={tool.enabled}
                                aria-label={`${tool.enabled ? t("停用") : t("启用")} ${tool.name}`}
                                className={`tool-switch ${tool.enabled ? "on" : ""}`}
                                disabled={!tool.available || toolboxSaving === tool.id}
                                onClick={() => toggleTool(tool)}
                              ><span /></button>
                            </article>
                          ))}
                        </section>
                      ))}
                    </div>
                  ) : (
                    <div className="toolbox-empty">{t("服务端尚未提供可用的扩展工具。")}</div>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>
      )}
      {assetCenter && (
        <AssetCenter
          key={`${assetCenter.service?.id || "new"}-${assetCenter.tab}`}
          assets={assetServices}
          initialService={assetCenter.service}
          initialTab={assetCenter.tab}
          activeSession={activeSession}
          onClose={() => setAssetCenter(null)}
          onRefresh={refreshAssets}
          onMount={mountAsset}
          onCreateInvestigationSession={createInvestigationSession}
          notify={notify}
          t={t}
        />
      )}
    </main>
  );
}
